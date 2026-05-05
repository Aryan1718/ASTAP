import ast
import json
import logging
import tempfile
import zipfile
from pathlib import Path
from shutil import rmtree

from shared.config import GenerateTestsConfig, settings
from shared.db import SessionLocal
from shared.models import Target
from shared.repository import (
    claim_job,
    get_run,
    list_targets_for_run,
    mark_job_failed,
    mark_job_succeeded_with_artifacts,
    mark_run_failed,
    mark_run_running,
    mark_run_succeeded,
)
from shared.targets import (
    DiscoverTargetsArtifact,
    GeneratedTestManifestEntry,
    GeneratedTestStatus,
    GenerationPacket,
    RichTargetArtifact,
    SlimTargetRow,
    SourceContext,
    artifact_target_by_key,
    build_generated_test_manifest,
    generated_test_relative_path,
)
from shared.storage import download_storage_object, download_storage_object_text, upload_file_to_storage
from worker.app.jobs.common import safe_extract_tar_gz
from worker.app.providers.openai_provider import OpenAIGenerateTestsProvider

logger = logging.getLogger(__name__)

SUPPORTED_TARGET_TYPES = {"SERVICE_FUNCTION", "API_ENDPOINT"}
DANGEROUS_PATTERNS = (
    "subprocess.",
    "os.system(",
    "shutil.rmtree(",
    "requests.",
    "httpx.",
    "urllib.request",
)


def generate_tests_job(run_id: str, job_id: str) -> None:
    session = SessionLocal()
    temp_dir = Path(tempfile.mkdtemp(prefix="generate-tests-"))
    try:
        job = claim_job(session, job_id)
        if job is None:
            return

        config = settings.generate_tests_config()
        api_key = settings.require_openai_api_key_for_generate_tests()

        run = get_run(session, run_id)
        if run is None:
            raise RuntimeError("Run not found")
        if not run.snapshot_bucket or not run.snapshot_key:
            raise RuntimeError("Run snapshot metadata is missing")

        mark_run_running(session, run_id)

        snapshot_path = temp_dir / "snapshot.tar.gz"
        repo_path = temp_dir / "repo"
        output_root = temp_dir / config.output_dir
        output_root.mkdir(parents=True, exist_ok=True)

        download_storage_object(run.snapshot_bucket, run.snapshot_key, snapshot_path)
        safe_extract_tar_gz(snapshot_path, repo_path)

        discover_payload = load_discover_targets(run.workspace_id, run.project_id, run.id)
        targets_by_key = artifact_target_by_key(discover_payload.targets)
        provider = OpenAIGenerateTestsProvider(api_key=api_key, config=config)
        db_targets = list_targets_for_run(session, run.id)

        selected_targets = select_targets_for_generation(
            db_targets=db_targets,
            targets_by_key=targets_by_key,
            config=config,
        )

        manifest_entries: list[GeneratedTestManifestEntry] = []
        uploaded_artifacts: list[dict] = []
        generated_count = 0
        skipped_count = 0

        for target_row, target_artifact in selected_targets:
            packet = build_generation_packet(run.id, repo_path, target_row, target_artifact)
            if packet is None:
                manifest_entries.append(
                    build_skipped_manifest_entry(target_row, "source_context_missing")
                )
                skipped_count += 1
                continue

            output_path = Path(
                generated_test_relative_path(config.output_dir, target_row.target_type, target_row.symbol, target_row.target_key)
            )
            full_output_path = temp_dir / output_path
            full_output_path.parent.mkdir(parents=True, exist_ok=True)

            generated_code = ""
            try:
                generated_code = provider.generate_test_code(packet)
                validated_code = validate_generated_test_code(generated_code)
            except Exception as exc:  # noqa: BLE001
                try:
                    repaired_code = provider.repair_test_code(
                        packet=packet,
                        invalid_code=generated_code,
                        error_message=str(exc),
                    )
                    validated_code = validate_generated_test_code(repaired_code)
                except Exception as repair_exc:  # noqa: BLE001
                    logger.warning(
                        "Generate tests skipped target %s for run %s due to invalid output: %s",
                        target_row.target_key,
                        run.id,
                        repair_exc,
                    )
                    manifest_entries.append(build_skipped_manifest_entry(target_row, str(repair_exc)))
                    skipped_count += 1
                    continue

            file_content = render_generated_test_file(packet, validated_code)
            full_output_path.write_text(file_content, encoding="utf-8")

            object_key = f"{run.workspace_id}/{run.project_id}/{run.id}/{output_path.as_posix()}"
            upload_file_to_storage(
                bucket=settings.supabase_storage_bucket,
                object_key=object_key,
                source=full_output_path,
                content_type="text/x-python",
            )
            uploaded_artifacts.append(
                {
                    "artifact_type": "generated_test_file",
                    "bucket": settings.supabase_storage_bucket,
                    "key": object_key,
                    "path": output_path.as_posix(),
                    "target_key": target_row.target_key,
                }
            )
            manifest_entries.append(
                GeneratedTestManifestEntry(
                    target_key=target_row.target_key,
                    target_type=target_row.target_type,
                    symbol=target_row.symbol,
                    source_file=target_row.file_path,
                    generated_test_file=output_path.as_posix(),
                    test_kind=test_kind_for_target_type(target_row.target_type),
                    status=GeneratedTestStatus.generated,
                )
            )
            generated_count += 1

        for skipped_entry in build_unselected_target_entries(
            db_targets=db_targets,
            selected_target_keys={target_row.target_key for target_row, _ in selected_targets},
            targets_by_key=targets_by_key,
            config=config,
        ):
            manifest_entries.append(skipped_entry)
            skipped_count += 1

        manifest = build_generated_test_manifest(run.id, manifest_entries)
        manifest_path = output_root / "test_index.json"
        manifest_path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8")

        manifest_key = f"{run.workspace_id}/{run.project_id}/{run.id}/{config.output_dir}/test_index.json"
        upload_file_to_storage(
            bucket=settings.supabase_storage_bucket,
            object_key=manifest_key,
            source=manifest_path,
            content_type="application/json",
        )
        uploaded_artifacts.append(
            {
                "artifact_type": "generated_tests_manifest",
                "bucket": settings.supabase_storage_bucket,
                "key": manifest_key,
                "path": f"{config.output_dir}/test_index.json",
            }
        )

        zip_path = temp_dir / "generated_tests.zip"
        create_stage_zip(output_root, zip_path)
        zip_key = f"{run.workspace_id}/{run.project_id}/{run.id}/{config.output_dir}.zip"
        upload_file_to_storage(
            bucket=settings.supabase_storage_bucket,
            object_key=zip_key,
            source=zip_path,
            content_type="application/zip",
        )
        uploaded_artifacts.append(
            {
                "artifact_type": "generated_tests_zip",
                "bucket": settings.supabase_storage_bucket,
                "key": zip_key,
                "path": f"{config.output_dir}.zip",
            }
        )

        total_supported_targets = len(selected_targets)
        artifact_paths = [artifact["path"] for artifact in uploaded_artifacts if "path" in artifact]
        logger.info(
            "Generate tests completed for run %s: total_supported_targets=%s generated_files=%s skipped_targets=%s artifact_paths=%s",
            run.id,
            total_supported_targets,
            generated_count,
            skipped_count,
            artifact_paths,
        )

        if total_supported_targets > 0 and generated_count == 0:
            raise RuntimeError("Generate tests failed for all supported targets")

        mark_job_succeeded_with_artifacts(
            session,
            job_id=job.id,
            output_json={
                "supported_targets": total_supported_targets,
                "generated_files": generated_count,
                "skipped_targets": skipped_count,
                "manifest_path": manifest_key,
                "artifact_paths": artifact_paths,
            },
            artifacts_json=uploaded_artifacts,
        )
        mark_run_succeeded(session, run.id)
    except Exception as exc:  # noqa: BLE001
        mark_job_failed(session, job_id, f"{type(exc).__name__}: {exc}")
        mark_run_failed(session, run_id)
        raise
    finally:
        session.close()
        rmtree(temp_dir, ignore_errors=True)


def load_discover_targets(workspace_id: str, project_id: str, run_id: str) -> DiscoverTargetsArtifact:
    object_key = f"{workspace_id}/{project_id}/{run_id}/discover/targets.json"
    payload = download_storage_object_text(settings.supabase_storage_bucket, object_key)
    return DiscoverTargetsArtifact.model_validate_json(payload)


def select_targets_for_generation(
    *,
    db_targets: list[Target],
    targets_by_key: dict[str, RichTargetArtifact],
    config: GenerateTestsConfig,
) -> list[tuple[SlimTargetRow, RichTargetArtifact]]:
    selected: list[tuple[SlimTargetRow, RichTargetArtifact]] = []
    for target in db_targets:
        if target.target_type == "SERVICE_FUNCTION" and not config.enable_service_functions:
            continue
        if target.target_type == "API_ENDPOINT" and not config.enable_api_endpoints:
            continue
        if target.target_type not in SUPPORTED_TARGET_TYPES:
            continue

        artifact_target = targets_by_key.get(target.target_key)
        if artifact_target is None:
            continue

        selected.append(
            (
                SlimTargetRow(
                    run_id=target.run_id,
                    target_key=target.target_key,
                    target_type=target.target_type,
                    file_path=target.file_path,
                    symbol=target.symbol,
                    signature=target.signature,
                    metadata=target.target_metadata,
                ),
                artifact_target,
            )
        )
        if len(selected) >= config.max_targets_per_run:
            break
    return selected


def build_unselected_target_entries(
    *,
    db_targets: list[Target],
    selected_target_keys: set[str],
    targets_by_key: dict[str, RichTargetArtifact],
    config: GenerateTestsConfig,
) -> list[GeneratedTestManifestEntry]:
    entries: list[GeneratedTestManifestEntry] = []
    for target in db_targets:
        if target.target_key in selected_target_keys:
            continue

        if target.target_type == "SERVICE_FUNCTION" and not config.enable_service_functions:
            reason = "target_type_disabled:SERVICE_FUNCTION"
        elif target.target_type == "API_ENDPOINT" and not config.enable_api_endpoints:
            reason = "target_type_disabled:API_ENDPOINT"
        elif target.target_type not in SUPPORTED_TARGET_TYPES:
            reason = f"unsupported_target_type:{target.target_type}"
        elif target.target_key not in targets_by_key:
            reason = "target_key_missing_from_discover_artifact"
        else:
            reason = "max_targets_limit_reached"

        entries.append(
            GeneratedTestManifestEntry(
                target_key=target.target_key,
                target_type=target.target_type,
                symbol=target.symbol,
                source_file=target.file_path,
                status=GeneratedTestStatus.skipped,
                skip_reason=reason,
            )
        )
    return entries


def build_generation_packet(
    run_id: str,
    repo_path: Path,
    target_db: SlimTargetRow,
    target_artifact: RichTargetArtifact,
) -> GenerationPacket | None:
    line_start = target_artifact.line_start or target_db.metadata.line_start
    line_end = target_artifact.line_end or target_db.metadata.line_end
    if line_start is None or line_end is None:
        return None

    source_path = repo_path / target_db.file_path
    if not source_path.exists():
        return None

    source_context = read_source_context(source_path, target_db.file_path, line_start, line_end)
    return GenerationPacket(
        run_id=run_id,
        target_db=target_db,
        target_artifact=target_artifact,
        source_context=source_context,
    )


def read_source_context(source_path: Path, file_path: str, line_start: int, line_end: int) -> SourceContext:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    sliced_lines = lines[max(line_start - 1, 0):line_end]
    return SourceContext(
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        code="\n".join(sliced_lines).strip(),
    )


def build_skipped_manifest_entry(target: SlimTargetRow, reason: str) -> GeneratedTestManifestEntry:
    return GeneratedTestManifestEntry(
        target_key=target.target_key,
        target_type=target.target_type,
        symbol=target.symbol,
        source_file=target.file_path,
        status=GeneratedTestStatus.skipped,
        skip_reason=reason,
    )


def test_kind_for_target_type(target_type: str) -> str:
    if target_type == "SERVICE_FUNCTION":
        return "unit"
    if target_type == "API_ENDPOINT":
        return "api"
    raise ValueError(f"Unsupported target type: {target_type}")


def render_generated_test_file(packet: GenerationPacket, code: str) -> str:
    header = "\n".join(
        [
            "# Generated by Automated Testing Platform",
            f"# run_id: {packet.run_id}",
            f"# target_key: {packet.target_db.target_key}",
            f"# target_type: {packet.target_db.target_type}",
            f"# source_file: {packet.target_db.file_path}",
            "",
        ]
    )
    return f"{header}{code.strip()}\n"


def validate_generated_test_code(content: str) -> str:
    stripped = normalize_common_llm_artifacts(content).strip()
    if not stripped:
        raise ValueError("empty_model_output")
    if stripped.startswith("```") or "\n```" in stripped:
        raise ValueError("markdown_fences_not_allowed")
    if "def test_" not in stripped:
        raise ValueError("missing_pytest_tests")
    if any(pattern in stripped for pattern in DANGEROUS_PATTERNS):
        raise ValueError("dangerous_usage_detected")
    ast.parse(stripped)
    return stripped


def normalize_common_llm_artifacts(content: str) -> str:
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }
    normalized = content
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def create_stage_zip(stage_dir: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage_dir.rglob("*")):
            if path.is_dir():
                continue
            archive.write(path, arcname=path.relative_to(stage_dir.parent))
