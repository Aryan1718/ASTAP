import ast
import json
import logging
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree

from shared.config import GenerateTestsConfig, settings
from shared.db import SessionLocal
from shared.models import Target
from shared.repository import (
    claim_job,
    get_job_by_stage,
    get_run,
    list_targets_for_run,
    mark_job_failed,
    mark_job_succeeded_with_artifacts,
    mark_run_failed,
    mark_run_running,
    set_job_rq_id,
)
from shared.queue import get_queue
from shared.security_recipes import SecurityRecipeMatch, match_security_recipes
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
    generated_security_test_relative_path,
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


@dataclass(slots=True)
class RecipeGenerationCandidate:
    target_row: SlimTargetRow
    target_artifact: RichTargetArtifact
    recipe_match: SecurityRecipeMatch


@dataclass(slots=True)
class GenericGenerationCandidate:
    target_row: SlimTargetRow
    target_artifact: RichTargetArtifact


@dataclass(slots=True)
class RunnabilityGateResult:
    allowed: bool
    reason: str | None = None


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

        recipe_candidates, skipped_entries = select_recipe_candidates_for_generation(
            db_targets=db_targets,
            targets_by_key=targets_by_key,
            config=config,
        )
        fallback_candidates: list[GenericGenerationCandidate] = []
        if not recipe_candidates:
            skipped_entries = [entry for entry in skipped_entries if entry.skip_reason != "no_security_recipe_match"]
            fallback_candidates, fallback_skipped = select_generic_fallback_candidates_for_generation(
                db_targets=db_targets,
                targets_by_key=targets_by_key,
                config=config,
            )
            skipped_entries.extend(fallback_skipped)

        manifest_entries: list[GeneratedTestManifestEntry] = list(skipped_entries)
        uploaded_artifacts: list[dict] = []
        generated_count = 0
        skipped_count = len(skipped_entries)
        runnable_candidates_count = 0
        empty_reason: str | None = None

        for candidate in recipe_candidates:
            gate_result = evaluate_runnability(candidate.target_artifact)
            if not gate_result.allowed:
                manifest_entries.append(
                    build_skipped_manifest_entry(
                        candidate.target_row,
                        gate_result.reason or "runnability_gate_failed",
                        generation_mode="security_recipe",
                        recipe_match=candidate.recipe_match,
                    )
                )
                skipped_count += 1
                continue

            runnable_candidates_count += 1
            packet = build_generation_packet(
                run.id,
                repo_path,
                candidate.target_row,
                candidate.target_artifact,
                candidate.recipe_match,
            )
            if packet is None:
                manifest_entries.append(
                    build_skipped_manifest_entry(
                        candidate.target_row,
                        "source_context_missing",
                        generation_mode="security_recipe",
                        recipe_match=candidate.recipe_match,
                    )
                )
                skipped_count += 1
                continue

            output_path = Path(
                generated_security_test_relative_path(
                    config.output_dir,
                    candidate.target_row.symbol,
                    candidate.recipe_match.recipe_id,
                    candidate.target_row.target_key,
                )
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
                        candidate.target_row.target_key,
                        run.id,
                        repair_exc,
                    )
                    manifest_entries.append(
                        build_skipped_manifest_entry(
                            candidate.target_row,
                            str(repair_exc),
                            generation_mode="security_recipe",
                            recipe_match=candidate.recipe_match,
                        )
                    )
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
                    "target_key": candidate.target_row.target_key,
                    "recipe_id": candidate.recipe_match.recipe_id,
                }
            )
            manifest_entries.append(
                GeneratedTestManifestEntry(
                    target_key=candidate.target_row.target_key,
                    target_type=candidate.target_row.target_type,
                    symbol=candidate.target_row.symbol,
                    source_file=candidate.target_row.file_path,
                    generated_test_file=output_path.as_posix(),
                    test_kind=candidate.recipe_match.test_kind,
                    status=GeneratedTestStatus.generated,
                    generation_mode="security_recipe",
                    recipe_id=candidate.recipe_match.recipe_id,
                    recipe_name=candidate.recipe_match.name,
                    risk_tags=candidate.target_artifact.risk_tags,
                )
            )
            generated_count += 1

        for candidate in fallback_candidates:
            gate_result = evaluate_runnability(candidate.target_artifact)
            if not gate_result.allowed:
                manifest_entries.append(
                    build_skipped_manifest_entry(
                        candidate.target_row,
                        gate_result.reason or "runnability_gate_failed",
                        generation_mode="generic_fallback",
                    )
                )
                skipped_count += 1
                continue

            runnable_candidates_count += 1
            packet = build_generic_generation_packet(
                run.id,
                repo_path,
                candidate.target_row,
                candidate.target_artifact,
            )
            if packet is None:
                manifest_entries.append(
                    build_skipped_manifest_entry(
                        candidate.target_row,
                        "source_context_missing",
                        generation_mode="generic_fallback",
                    )
                )
                skipped_count += 1
                continue

            output_path = Path(
                generated_test_relative_path(
                    config.output_dir,
                    candidate.target_row.target_type,
                    candidate.target_row.symbol,
                    candidate.target_row.target_key,
                )
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
                        "Generate tests skipped target %s for run %s due to invalid fallback output: %s",
                        candidate.target_row.target_key,
                        run.id,
                        repair_exc,
                    )
                    manifest_entries.append(
                        build_skipped_manifest_entry(
                            candidate.target_row,
                            str(repair_exc),
                            generation_mode="generic_fallback",
                        )
                    )
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
                    "target_key": candidate.target_row.target_key,
                    "generation_mode": "generic_fallback",
                    "recipe_id": None,
                }
            )
            manifest_entries.append(
                GeneratedTestManifestEntry(
                    target_key=candidate.target_row.target_key,
                    target_type=candidate.target_row.target_type,
                    symbol=candidate.target_row.symbol,
                    source_file=candidate.target_row.file_path,
                    generated_test_file=output_path.as_posix(),
                    test_kind=test_kind_for_target_type(candidate.target_row.target_type),
                    status=GeneratedTestStatus.generated,
                    generation_mode="generic_fallback",
                    recipe_id=None,
                    recipe_name=None,
                    risk_tags=candidate.target_artifact.risk_tags,
                )
            )
            generated_count += 1

        total_supported_targets = len(recipe_candidates) if recipe_candidates else len(fallback_candidates)
        if not discover_payload.targets:
            empty_reason = "no_discoverable_python_targets"
        elif total_supported_targets == 0:
            empty_reason = "no_eligible_targets_after_runnability_filtering"
        elif runnable_candidates_count > 0 and generated_count == 0:
            empty_reason = "generation_failed_for_all_candidates"
        elif runnable_candidates_count == 0 and generated_count == 0:
            empty_reason = "no_eligible_targets_after_runnability_filtering"

        manifest = build_generated_test_manifest(run.id, manifest_entries, empty_reason=empty_reason)
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

        artifact_paths = [artifact["path"] for artifact in uploaded_artifacts if "path" in artifact]
        logger.info(
            "Generate tests completed for run %s: total_supported_targets=%s generated_files=%s skipped_targets=%s artifact_paths=%s",
            run.id,
            total_supported_targets,
            generated_count,
            skipped_count,
            artifact_paths,
        )

        if runnable_candidates_count > 0 and generated_count == 0:
            raise RuntimeError("Generate tests failed for all supported targets")

        mark_job_succeeded_with_artifacts(
            session,
            job_id=job.id,
            output_json={
                "supported_targets": total_supported_targets,
                "runnable_targets": runnable_candidates_count,
                "generated_files": generated_count,
                "skipped_targets": skipped_count,
                "manifest_path": manifest_key,
                "artifact_paths": artifact_paths,
                "empty_reason": empty_reason,
            },
            artifacts_json=uploaded_artifacts,
        )
        execute_tests = get_job_by_stage(session, run.id, "execute_tests")
        if execute_tests is None:
            raise RuntimeError("Execute tests job not found")

        rq_job = get_queue("execute_tests").enqueue("worker.app.jobs.execute_tests_job", run.id, execute_tests.id)
        set_job_rq_id(session, execute_tests.id, rq_job.id)
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


def select_recipe_candidates_for_generation(
    *,
    db_targets: list[Target],
    targets_by_key: dict[str, RichTargetArtifact],
    config: GenerateTestsConfig,
) -> tuple[list[RecipeGenerationCandidate], list[GeneratedTestManifestEntry]]:
    selected: list[RecipeGenerationCandidate] = []
    skipped: list[GeneratedTestManifestEntry] = []
    for target in db_targets:
        if target.target_type == "SERVICE_FUNCTION" and not config.enable_service_functions:
            skipped.append(build_skipped_manifest_entry(_slim_target_row_from_db(target), "target_type_disabled:SERVICE_FUNCTION"))
            continue
        if target.target_type == "API_ENDPOINT" and not config.enable_api_endpoints:
            skipped.append(build_skipped_manifest_entry(_slim_target_row_from_db(target), "target_type_disabled:API_ENDPOINT"))
            continue
        if target.target_type not in SUPPORTED_TARGET_TYPES:
            skipped.append(build_skipped_manifest_entry(_slim_target_row_from_db(target), f"unsupported_target_type:{target.target_type}"))
            continue

        artifact_target = targets_by_key.get(target.target_key)
        if artifact_target is None:
            skipped.append(build_skipped_manifest_entry(_slim_target_row_from_db(target), "target_key_missing_from_discover_artifact"))
            continue

        target_row = _slim_target_row_from_db(target)
        recipe_matches = match_security_recipes(artifact_target)
        if not recipe_matches:
            skipped.append(build_skipped_manifest_entry(target_row, "no_security_recipe_match"))
            continue

        for recipe_match in recipe_matches:
            candidate = RecipeGenerationCandidate(
                target_row=target_row,
                target_artifact=artifact_target,
                recipe_match=recipe_match,
            )
            if len(selected) >= config.max_targets_per_run:
                skipped.append(
                    build_skipped_manifest_entry(
                        target_row,
                        "max_targets_limit_reached",
                        recipe_match=recipe_match,
                    )
                )
                continue
            selected.append(candidate)
    return selected, skipped


def select_generic_fallback_candidates_for_generation(
    *,
    db_targets: list[Target],
    targets_by_key: dict[str, RichTargetArtifact],
    config: GenerateTestsConfig,
) -> tuple[list[GenericGenerationCandidate], list[GeneratedTestManifestEntry]]:
    selected: list[GenericGenerationCandidate] = []
    skipped: list[GeneratedTestManifestEntry] = []

    for target in db_targets:
        target_row = _slim_target_row_from_db(target)
        if target.target_type == "SERVICE_FUNCTION" and not config.enable_service_functions:
            skipped.append(
                build_skipped_manifest_entry(target_row, "target_type_disabled:SERVICE_FUNCTION", generation_mode="generic_fallback")
            )
            continue
        if target.target_type == "API_ENDPOINT" and not config.enable_api_endpoints:
            skipped.append(
                build_skipped_manifest_entry(target_row, "target_type_disabled:API_ENDPOINT", generation_mode="generic_fallback")
            )
            continue
        if target.target_type not in SUPPORTED_TARGET_TYPES:
            skipped.append(
                build_skipped_manifest_entry(target_row, f"unsupported_target_type:{target.target_type}", generation_mode="generic_fallback")
            )
            continue

        artifact_target = targets_by_key.get(target.target_key)
        if artifact_target is None:
            skipped.append(
                build_skipped_manifest_entry(target_row, "target_key_missing_from_discover_artifact", generation_mode="generic_fallback")
            )
            continue
        if not is_generic_fallback_eligible(artifact_target):
            skipped.append(
                build_skipped_manifest_entry(target_row, "not_eligible_for_generic_fallback", generation_mode="generic_fallback")
            )
            continue
        if len(selected) >= config.max_targets_per_run:
            skipped.append(
                build_skipped_manifest_entry(target_row, "max_targets_limit_reached", generation_mode="generic_fallback")
            )
            continue

        selected.append(GenericGenerationCandidate(target_row=target_row, target_artifact=artifact_target))

    return selected, skipped


def build_generation_packet(
    run_id: str,
    repo_path: Path,
    target_db: SlimTargetRow,
    target_artifact: RichTargetArtifact,
    recipe_match: SecurityRecipeMatch,
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
        generation_mode="security_recipe",
        recipe_id=recipe_match.recipe_id,
        recipe_name=recipe_match.name,
        recipe_payload_templates=recipe_match.payload_templates,
        recipe_expected_secure_behaviors=recipe_match.expected_secure_behaviors,
        recipe_rationale=recipe_match.rationale,
    )


def build_generic_generation_packet(
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
        generation_mode="generic_fallback",
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


def build_skipped_manifest_entry(
    target: SlimTargetRow,
    reason: str,
    *,
    generation_mode: str | None = None,
    recipe_match: SecurityRecipeMatch | None = None,
) -> GeneratedTestManifestEntry:
    return GeneratedTestManifestEntry(
        target_key=target.target_key,
        target_type=target.target_type,
        symbol=target.symbol,
        source_file=target.file_path,
        status=GeneratedTestStatus.skipped,
        test_kind=recipe_match.test_kind if recipe_match is not None else None,
        generation_mode=generation_mode or ("security_recipe" if recipe_match is not None else None),
        recipe_id=recipe_match.recipe_id if recipe_match is not None else None,
        recipe_name=recipe_match.name if recipe_match is not None else None,
        risk_tags=target.metadata.risk_tags,
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
            f"# generation_mode: {packet.generation_mode}",
            f"# recipe_id: {packet.recipe_id or 'n/a'}",
            f"# recipe_name: {packet.recipe_name or 'n/a'}",
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


def _slim_target_row_from_db(target: Target) -> SlimTargetRow:
    return SlimTargetRow(
        run_id=target.run_id,
        target_key=target.target_key,
        target_type=target.target_type,
        file_path=target.file_path,
        symbol=target.symbol,
        signature=target.signature,
        metadata=target.target_metadata,
    )


def evaluate_runnability(target: RichTargetArtifact) -> RunnabilityGateResult:
    execution_context = target.execution_context
    module_path = execution_context.get("module_path")
    import_hint = execution_context.get("import_hint")
    if not isinstance(module_path, str) or not module_path:
        return RunnabilityGateResult(allowed=False, reason="runnability_missing_module_path")
    if not isinstance(import_hint, str) or not import_hint:
        return RunnabilityGateResult(allowed=False, reason="runnability_missing_import_hint")

    if target.target_type == "API_ENDPOINT":
        api_framework = execution_context.get("api_framework")
        if api_framework == "fastapi":
            fastapi_candidate = execution_context.get("fastapi_test_client_candidate")
            router_symbol = execution_context.get("fastapi_router_symbol")
            if not fastapi_candidate:
                return RunnabilityGateResult(allowed=False, reason="runnability_missing_fastapi_test_client_context")
            if not isinstance(router_symbol, str) or not router_symbol:
                return RunnabilityGateResult(allowed=False, reason="runnability_missing_fastapi_router_symbol")
        elif api_framework == "flask":
            flask_candidate = execution_context.get("flask_test_client_candidate")
            app_symbol = execution_context.get("flask_app_symbol")
            if not flask_candidate:
                return RunnabilityGateResult(allowed=False, reason="runnability_missing_flask_test_client_context")
            if not isinstance(app_symbol, str) or not app_symbol:
                return RunnabilityGateResult(allowed=False, reason="runnability_missing_flask_app_symbol")
        else:
            return RunnabilityGateResult(allowed=False, reason="runnability_unsupported_api_framework")

    return RunnabilityGateResult(allowed=True)


def is_generic_fallback_eligible(target: RichTargetArtifact) -> bool:
    execution_context = target.execution_context
    module_path = execution_context.get("module_path")
    import_hint = execution_context.get("import_hint")
    if not isinstance(module_path, str) or not module_path:
        return False
    if not isinstance(import_hint, str) or not import_hint:
        return False
    if target.target_type == "SERVICE_FUNCTION":
        return True
    if target.target_type == "API_ENDPOINT":
        return execution_context.get("api_framework") in {"fastapi", "flask"}
    return False
