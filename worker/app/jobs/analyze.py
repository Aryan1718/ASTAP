import json
import logging
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from shutil import rmtree

from shared.config import settings
from shared.db import SessionLocal
from shared.repository import (
    claim_job,
    get_job_by_stage,
    get_run,
    list_jobs_for_run,
    mark_job_failed,
    mark_job_succeeded_with_artifacts,
    mark_run_failed,
    mark_run_succeeded,
    update_run_summary,
)
from shared.security_recipes import list_security_recipes
from shared.storage import download_storage_object_text, upload_file_to_storage
from shared.targets import DiscoverTargetsArtifact, GeneratedTestManifest
from worker.app.providers.openai_analyze_provider import OpenAIAnalyzeProvider

logger = logging.getLogger(__name__)
HEURISTICS_VERSION = 1
RECIPE_SEVERITY_BY_ID = {recipe.recipe_id: recipe.severity.value for recipe in list_security_recipes()}


def analyze_job(run_id: str, job_id: str) -> None:
    session = SessionLocal()
    temp_dir = Path(tempfile.mkdtemp(prefix="analyze-"))
    try:
        job = claim_job(session, job_id)
        if job is None:
            return

        run = get_run(session, run_id)
        if run is None:
            raise RuntimeError("Run not found")

        discover_job = _require_job(session, run.id, "discover")
        generate_tests_job = _require_job(session, run.id, "generate_tests")
        execute_tests_job = _require_job(session, run.id, "execute_tests")

        discover_payload = _load_discover_artifact(discover_job)
        manifest = _load_generated_manifest(generate_tests_job)
        execution_results = _load_execution_results(execute_tests_job)
        failure_records = _build_failure_records(execute_tests_job, manifest)
        summary_payload = _build_summary_payload(run.id, execution_results, failure_records)

        summary_path = temp_dir / "summary.json"
        failures_path = temp_dir / "failures.json"
        summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
        failures_path.write_text(
            json.dumps({"run_id": run.id, "heuristics_version": HEURISTICS_VERSION, "failures": failure_records}, indent=2),
            encoding="utf-8",
        )

        llm_summary_path: Path | None = None
        analysis_mode = "deterministic_only"
        llm_summary_available = False
        analyze_config = settings.analyze_config()
        if analyze_config.enable_llm and settings.openai_api_key:
            evidence_packet = _build_llm_evidence_packet(
                summary_payload=summary_payload,
                failure_records=failure_records,
                manifest=manifest,
                discover_payload=discover_payload,
                max_failures=analyze_config.max_failures_for_llm,
            )
            try:
                provider = OpenAIAnalyzeProvider(api_key=settings.openai_api_key, config=analyze_config)
                llm_summary = provider.generate_summary(evidence_packet)
                llm_summary_path = temp_dir / "llm_summary.md"
                llm_summary_path.write_text(llm_summary + "\n", encoding="utf-8")
                analysis_mode = "deterministic_plus_llm"
                llm_summary_available = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Analyze LLM summary failed for run %s: %s", run.id, exc)
                analysis_mode = "deterministic_llm_failed"

        summary_payload["analysis_mode"] = analysis_mode
        summary_payload["llm_summary_available"] = llm_summary_available
        summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

        artifacts = _upload_analysis_artifacts(
            run=run,
            summary_path=summary_path,
            failures_path=failures_path,
            llm_summary_path=llm_summary_path,
        )
        output_json = _build_analysis_output_json(summary_payload, artifacts)

        mark_job_succeeded_with_artifacts(session, job.id, output_json=output_json, artifacts_json=artifacts)
        update_run_summary(session, run.id, _build_run_summary(summary_payload))
        _finalize_run(session, run.id)
    except Exception as exc:  # noqa: BLE001
        mark_job_failed(session, job_id, f"{type(exc).__name__}: {exc}")
        mark_run_failed(session, run_id)
        raise
    finally:
        session.close()
        rmtree(temp_dir, ignore_errors=True)


def _require_job(session, run_id: str, stage: str):
    job = get_job_by_stage(session, run_id, stage)
    if job is None:
        raise RuntimeError(f"{stage} job not found")
    return job


def _load_discover_artifact(discover_job) -> DiscoverTargetsArtifact:
    artifact = next(
        (item for item in discover_job.artifacts_json if item.get("path") == "discover/targets.json"),
        None,
    )
    if artifact is None:
        raise RuntimeError("Discover targets artifact not found")
    return DiscoverTargetsArtifact.model_validate_json(
        download_storage_object_text(artifact["bucket"], artifact["key"])
    )


def _load_generated_manifest(generate_tests_job) -> GeneratedTestManifest:
    artifact = next(
        (item for item in generate_tests_job.artifacts_json if item.get("artifact_type") == "generated_tests_manifest"),
        None,
    )
    if artifact is None:
        raise RuntimeError("Generated tests manifest artifact not found")
    return GeneratedTestManifest.model_validate_json(
        download_storage_object_text(artifact["bucket"], artifact["key"])
    )


def _load_execution_results(execute_tests_job) -> dict:
    artifact = next(
        (item for item in execute_tests_job.artifacts_json if item.get("artifact_type") == "execution_results"),
        None,
    )
    if artifact is None:
        output_json = execute_tests_job.output_json if isinstance(execute_tests_job.output_json, dict) else {}
        if output_json:
            return output_json
        raise RuntimeError("Execute tests results artifact not found")
    return json.loads(download_storage_object_text(artifact["bucket"], artifact["key"]))


def _build_failure_records(execute_tests_job, manifest: GeneratedTestManifest) -> list[dict]:
    manifest_entries_by_path = {
        entry.generated_test_file: entry
        for entry in manifest.files
        if entry.generated_test_file
    }
    junit_artifacts = [
        artifact
        for artifact in execute_tests_job.artifacts_json
        if artifact.get("artifact_type") == "execution_junit" and isinstance(artifact.get("path"), str)
    ]
    failures: list[dict] = []
    for artifact in junit_artifacts:
        suite_key = _suite_key_from_junit_path(artifact["path"])
        xml_payload = download_storage_object_text(artifact["bucket"], artifact["key"])
        failures.extend(_parse_junit_failures(xml_payload, suite_key, manifest_entries_by_path))
    return failures


def _suite_key_from_junit_path(path: str) -> str:
    if path.endswith("existing-tests.xml"):
        return "existing"
    if path.endswith("generated-tests.xml"):
        return "generated"
    return "combined"


def _parse_junit_failures(xml_payload: str, suite_key: str, manifest_entries_by_path: dict[str, object]) -> list[dict]:
    root = ET.fromstring(xml_payload)
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    records: list[dict] = []
    for suite in suites:
        for testcase in suite.findall("testcase"):
            failure_node = testcase.find("failure")
            error_node = testcase.find("error")
            status = None
            detail_node = None
            if failure_node is not None:
                status = "failure"
                detail_node = failure_node
            elif error_node is not None:
                status = "error"
                detail_node = error_node
            if status is None or detail_node is None:
                continue

            file_path = testcase.attrib.get("file")
            classname = testcase.attrib.get("classname")
            test_name = testcase.attrib.get("name")
            message = detail_node.attrib.get("message") or ""
            traceback = (detail_node.text or "").strip()
            correlated_entry = _correlate_generated_failure(
                suite_key=suite_key,
                file_path=file_path,
                classname=classname,
                manifest_entries_by_path=manifest_entries_by_path,
            )
            record = {
                "suite": suite_key,
                "status": status,
                "test_name": test_name,
                "classname": classname,
                "file_path": file_path,
                "duration_seconds": _safe_float(testcase.attrib.get("time")),
                "message": message,
                "traceback_excerpt": traceback[:4000],
                "target_key": correlated_entry.target_key if correlated_entry else None,
                "symbol": correlated_entry.symbol if correlated_entry else None,
                "source_file": correlated_entry.source_file if correlated_entry else None,
                "recipe_id": correlated_entry.recipe_id if correlated_entry else None,
                "recipe_name": correlated_entry.recipe_name if correlated_entry else None,
                "generated_test_file": correlated_entry.generated_test_file if correlated_entry else None,
                "risk_tags": correlated_entry.risk_tags if correlated_entry else [],
            }
            records.append(record)
    return records


def _correlate_generated_failure(*, suite_key: str, file_path: str | None, classname: str | None, manifest_entries_by_path: dict[str, object]):
    if suite_key != "generated":
        return None

    candidates = list(manifest_entries_by_path.values())
    if file_path:
        exact = [entry for entry in candidates if entry.generated_test_file == file_path or entry.generated_test_file.endswith(file_path)]
        if len(exact) == 1:
            return exact[0]
        basename_matches = [entry for entry in candidates if Path(entry.generated_test_file).name == Path(file_path).name]
        if len(basename_matches) == 1:
            return basename_matches[0]
    if classname:
        stem_matches = [entry for entry in candidates if Path(entry.generated_test_file).stem == classname.split(".")[-1]]
        if len(stem_matches) == 1:
            return stem_matches[0]
    return None


def _build_summary_payload(run_id: str, execution_results: dict, failure_records: list[dict]) -> dict:
    existing_suite = execution_results.get("existing_tests") or {}
    generated_suite = execution_results.get("generated_tests") or {}
    overall_result = execution_results.get("overall_result")
    execution_error = execution_results.get("error")

    infrastructure_status = "error" if execution_error or str(overall_result).startswith("environment_") else "ok"
    baseline_repo_status = str(existing_suite.get("status") or "unknown")
    generated_tests_status = str(generated_suite.get("status") or "unknown")
    _apply_failure_heuristics(
        failure_records=failure_records,
        baseline_repo_status=baseline_repo_status,
        infrastructure_status=infrastructure_status,
    )
    generated_failure_records = [record for record in failure_records if record["suite"] == "generated"]

    generated_unrunnable = _generated_suite_unrunnable(generated_failure_records)
    if infrastructure_status == "error":
        overall_assessment = "infrastructure_error"
    elif baseline_repo_status == "passed" and generated_tests_status in {"passed", "skipped"}:
        overall_assessment = "all_passed"
    elif baseline_repo_status != "passed" and not generated_failure_records:
        overall_assessment = "baseline_repo_failed"
    elif baseline_repo_status == "passed" and generated_failure_records and not generated_unrunnable:
        overall_assessment = "generated_tests_found_new_failures"
    elif generated_unrunnable:
        overall_assessment = "generated_tests_unrunnable"
    else:
        overall_assessment = "mixed_results"

    highlights = _build_highlights(overall_assessment, failure_records)
    low_signal_failures = len([record for record in failure_records if _is_low_signal(record)])
    unrunnable_failures = len(
        [
            record
            for record in failure_records
            if record.get("failure_category") in {"generated_test_issue", "environment_issue"}
            and any(tag in record.get("heuristic_tags", []) for tag in ["setup_failure", "repeated_setup_error"])
        ]
    )
    flaky_suspects = len([record for record in failure_records if record.get("failure_category") == "flaky_suspect"])
    counts = {
        "existing_failed": int(existing_suite.get("failed", 0)) + int(existing_suite.get("errors", 0)),
        "generated_failed": int(generated_suite.get("failed", 0)) + int(generated_suite.get("errors", 0)),
        "high_signal_failures": len([record for record in generated_failure_records if record.get("target_key")]),
        "infrastructure_errors": 1 if infrastructure_status == "error" else 0,
        "low_signal_failures": low_signal_failures,
        "unrunnable_failures": unrunnable_failures,
        "flaky_suspects": flaky_suspects,
    }

    return {
        "version": 1,
        "heuristics_version": HEURISTICS_VERSION,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_assessment": overall_assessment,
        "baseline_repo_status": baseline_repo_status,
        "generated_tests_status": generated_tests_status,
        "infrastructure_status": infrastructure_status,
        "analysis_mode": "deterministic_only",
        "llm_summary_available": False,
        "counts": counts,
        "highlights": highlights,
        "artifacts": {
            "summary_json": "analyze/summary.json",
            "failures_json": "analyze/failures.json",
        },
    }


def _generated_suite_unrunnable(failure_records: list[dict]) -> bool:
    if not failure_records:
        return False
    unrunnable_hits = 0
    for record in failure_records:
        if any(
            tag in record.get("heuristic_tags", [])
            for tag in ["setup_failure", "repeated_setup_error", "generated_suite_unrunnable"]
        ):
            unrunnable_hits += 1
    return unrunnable_hits == len(failure_records)


def _build_highlights(overall_assessment: str, failure_records: list[dict]) -> list[dict]:
    if overall_assessment == "infrastructure_error":
        return [
            {
                "kind": "infrastructure_error",
                "priority": "high",
                "headline": "Execution environment setup failed before tests completed.",
                "severity": "critical",
                "confidence": "high",
                "confidence_score": 1.0,
                "failure_category": "environment_issue",
                "heuristic_tags": ["environment_setup_failed"],
                "evidence": ["Dependency installation or environment preparation failed during execute_tests."],
            }
        ]

    highlights: list[dict] = []
    seen_groups: set[str] = set()
    for record in sorted(failure_records, key=_highlight_rank, reverse=True):
        group_key = record.get("group_key")
        if isinstance(group_key, str) and group_key in seen_groups:
            continue
        if isinstance(group_key, str):
            seen_groups.add(group_key)
        highlights.append(
            {
                "kind": "generated_failure" if record["suite"] == "generated" else "baseline_failure",
                "priority": _highlight_priority(record),
                "headline": _headline_for_record(record),
                "suite": record["suite"],
                "test_name": record.get("test_name"),
                "target_key": record.get("target_key"),
                "symbol": record.get("symbol"),
                "source_file": record.get("source_file"),
                "recipe_id": record.get("recipe_id"),
                "recipe_name": record.get("recipe_name"),
                "generated_test_file": record.get("generated_test_file"),
                "risk_tags": record.get("risk_tags", []),
                "severity": record.get("severity", "medium"),
                "confidence": record.get("confidence", "medium"),
                "confidence_score": record.get("confidence_score", 0.5),
                "failure_category": record.get("failure_category", "product_failure"),
                "heuristic_tags": record.get("heuristic_tags", []),
                "evidence": _failure_evidence(record),
            }
        )
        if len(highlights) == 5:
            break
    return highlights


def _generated_failure_headline(record: dict) -> str:
    symbol = record.get("symbol") or "generated target"
    recipe_name = record.get("recipe_name") or record.get("recipe_id") or "generated scenario"
    category = record.get("failure_category")
    if category == "generated_test_issue":
        return f"Generated test for `{symbol}` likely failed because of setup or runnability issues under `{recipe_name}`."
    if category == "flaky_suspect":
        return f"Generated test for `{symbol}` looks flaky under `{recipe_name}`."
    return f"Generated test for `{symbol}` likely exposed a product failure under `{recipe_name}`."


def _failure_evidence(record: dict) -> list[str]:
    evidence = []
    if record.get("message"):
        evidence.append(str(record["message"])[:300])
    if record.get("traceback_excerpt"):
        evidence.append(str(record["traceback_excerpt"]).splitlines()[0][:300])
    if record.get("generated_test_file"):
        evidence.append(f"Generated test file: {record['generated_test_file']}")
    if record.get("heuristic_tags"):
        evidence.append(f"Heuristics: {', '.join(record['heuristic_tags'][:4])}")
    return evidence[:3]


def _apply_failure_heuristics(*, failure_records: list[dict], baseline_repo_status: str, infrastructure_status: str) -> None:
    baseline_passed = baseline_repo_status == "passed"
    group_counts = Counter(_group_key_for_record(record) for record in failure_records)
    generated_failures = [record for record in failure_records if record["suite"] == "generated"]
    generated_failure_count = len(generated_failures)
    for record in failure_records:
        detail = _detail_text(record)
        error_kind = _error_kind(detail)
        group_key = _group_key_for_record(record)
        group_size = group_counts[group_key]
        recipe_severity = RECIPE_SEVERITY_BY_ID.get(record.get("recipe_id"))

        heuristic_tags: list[str] = []
        score = 0.5
        failure_category = "product_failure"
        severity = "medium"

        if record["suite"] == "existing":
            score = 0.82
            severity = "high"
            failure_category = "baseline_failure"
            heuristic_tags.append("baseline_suite_failure")
        elif infrastructure_status == "error":
            score = 0.1
            severity = "critical"
            failure_category = "environment_issue"
            heuristic_tags.append("environment_setup_failed")
        else:
            if baseline_passed:
                score += 0.15
                heuristic_tags.append("baseline_suite_passed")
            if record.get("target_key"):
                score += 0.2
                heuristic_tags.append("target_mapped")
            else:
                score -= 0.12
                heuristic_tags.append("generated_test_unmapped")

            if recipe_severity == "high":
                score += 0.12
                severity = "high"
                heuristic_tags.append("recipe_severity_high")
            elif recipe_severity == "medium":
                score += 0.05
                severity = "medium"
                heuristic_tags.append("recipe_severity_medium")
            elif recipe_severity == "low":
                heuristic_tags.append("recipe_severity_low")

            if error_kind == "assertion":
                score += 0.14
                heuristic_tags.append("assertion_failure")
            elif error_kind in {"import", "fixture", "collection", "syntax", "setup"}:
                score -= 0.38
                failure_category = "generated_test_issue"
                severity = "low"
                heuristic_tags.extend(["setup_failure", "generated_suite_unrunnable"])
            elif error_kind == "timeout":
                score -= 0.08
                severity = "medium"
                heuristic_tags.append("timeout_signal")

            if record["status"] == "error":
                score -= 0.08

            if group_size > 1:
                score -= min(0.1 + 0.04 * (group_size - 1), 0.26)
                heuristic_tags.append(f"repeated_error_cluster:{group_size}")
                if error_kind in {"import", "fixture", "collection", "syntax", "setup"}:
                    heuristic_tags.append("repeated_setup_error")
                    failure_category = "generated_test_issue"
                    severity = "low"

            if error_kind == "timeout" and group_size == 1 and generated_failure_count == 1:
                score -= 0.06
                failure_category = "flaky_suspect"
                heuristic_tags.append("single_test_only")
                heuristic_tags.append("possible_flaky_timeout")

        score = max(0.0, min(1.0, round(score, 2)))
        if score >= 0.8:
            confidence = "high"
        elif score >= 0.55:
            confidence = "medium"
        else:
            confidence = "low"

        if failure_category == "product_failure" and confidence == "low":
            failure_category = "generated_test_issue"
        if failure_category == "generated_test_issue" and severity != "critical":
            severity = "low"
        if failure_category == "flaky_suspect" and severity == "high":
            severity = "medium"

        record["severity"] = severity
        record["confidence"] = confidence
        record["confidence_score"] = score
        record["failure_category"] = failure_category
        record["heuristic_tags"] = sorted(set(heuristic_tags))
        record["group_key"] = group_key


def _detail_text(record: dict) -> str:
    return f"{record.get('message', '')}\n{record.get('traceback_excerpt', '')}".lower()


def _error_kind(detail: str) -> str:
    if any(token in detail for token in ["modulenotfounderror", "importerror"]):
        return "import"
    if any(token in detail for token in ["fixture", "conftest", "setup failed", "setup error"]):
        return "fixture"
    if "collection" in detail:
        return "collection"
    if "syntaxerror" in detail:
        return "syntax"
    if "timeout" in detail or "timed out" in detail:
        return "timeout"
    if "assert" in detail or "assertionerror" in detail:
        return "assertion"
    if any(token in detail for token in ["environment", "dependency install failed", "pip install"]):
        return "setup"
    return "generic"


def _group_key_for_record(record: dict) -> str:
    detail = _detail_text(record)
    error_kind = _error_kind(detail)
    first_line = next((line.strip() for line in detail.splitlines() if line.strip()), "")
    path_component = "cluster"
    if error_kind not in {"import", "fixture", "collection", "syntax", "setup"}:
        path_component = Path(record.get("generated_test_file") or record.get("file_path") or "").name or "n/a"
    return "|".join(
        [
            str(record.get("suite") or "unknown"),
            error_kind,
            first_line[:160],
            path_component,
        ]
    )


def _is_low_signal(record: dict) -> bool:
    return record.get("confidence") == "low" or record.get("failure_category") in {"generated_test_issue", "flaky_suspect"}


def _severity_rank(value: str | None) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(value or "", 0)


def _category_rank(value: str | None) -> int:
    return {
        "product_failure": 5,
        "baseline_failure": 4,
        "environment_issue": 3,
        "flaky_suspect": 2,
        "generated_test_issue": 1,
    }.get(value or "", 0)


def _highlight_rank(record: dict) -> tuple:
    return (
        _category_rank(record.get("failure_category")),
        float(record.get("confidence_score", 0.0)),
        _severity_rank(record.get("severity")),
        1 if record.get("target_key") else 0,
        1 if record.get("suite") == "generated" else 0,
    )


def _highlight_priority(record: dict) -> str:
    if record.get("severity") in {"critical", "high"} and record.get("confidence") == "high":
        return "high"
    if record.get("confidence") == "low":
        return "low"
    return "medium"


def _headline_for_record(record: dict) -> str:
    if record.get("suite") == "generated":
        return _generated_failure_headline(record)
    if record.get("failure_category") == "environment_issue":
        return "Generated execution signals point to environment setup problems."
    return f"Existing test `{record.get('test_name') or 'unknown'}` failed before generated tests were considered."


def _build_llm_evidence_packet(
    *,
    summary_payload: dict,
    failure_records: list[dict],
    manifest: GeneratedTestManifest,
    discover_payload: DiscoverTargetsArtifact,
    max_failures: int,
) -> dict:
    discover_targets = {target.target_key: target for target in discover_payload.targets}
    top_failures = []
    for record in failure_records[:max_failures]:
        target = discover_targets.get(record.get("target_key"))
        top_failures.append(
            {
                "suite": record["suite"],
                "status": record["status"],
                "test_name": record.get("test_name"),
                "message": record.get("message"),
                "target_key": record.get("target_key"),
                "symbol": record.get("symbol"),
                "recipe_id": record.get("recipe_id"),
                "recipe_name": record.get("recipe_name"),
                "risk_tags": record.get("risk_tags", []),
                "source_file": target.file_path if target else record.get("source_file"),
                "severity": record.get("severity"),
                "confidence": record.get("confidence"),
                "confidence_score": record.get("confidence_score"),
                "failure_category": record.get("failure_category"),
                "heuristic_tags": record.get("heuristic_tags", []),
            }
        )
    return {
        "heuristics_version": summary_payload["heuristics_version"],
        "overall_assessment": summary_payload["overall_assessment"],
        "baseline_repo_status": summary_payload["baseline_repo_status"],
        "generated_tests_status": summary_payload["generated_tests_status"],
        "infrastructure_status": summary_payload["infrastructure_status"],
        "counts": summary_payload["counts"],
        "generated_manifest_counts": {
            "generated": len([entry for entry in manifest.files if entry.status == "generated"]),
            "skipped": len([entry for entry in manifest.files if entry.status != "generated"]),
        },
        "grouped_issue_summaries": _grouped_issue_summaries(failure_records),
        "highlights": summary_payload["highlights"],
        "top_failures": top_failures,
    }


def _upload_analysis_artifacts(*, run, summary_path: Path, failures_path: Path, llm_summary_path: Path | None) -> list[dict]:
    files = [
        ("analysis_summary", summary_path, "application/json"),
        ("analysis_failures", failures_path, "application/json"),
    ]
    if llm_summary_path is not None:
        files.append(("analysis_report", llm_summary_path, "text/markdown"))

    artifacts: list[dict] = []
    for artifact_type, source, content_type in files:
        relative_path = f"analyze/{source.name}"
        object_key = f"{run.workspace_id}/{run.project_id}/{run.id}/{relative_path}"
        upload_file_to_storage(
            bucket=settings.supabase_storage_bucket,
            object_key=object_key,
            source=source,
            content_type=content_type,
        )
        artifacts.append(
            {
                "artifact_type": artifact_type,
                "bucket": settings.supabase_storage_bucket,
                "key": object_key,
                "path": relative_path,
            }
        )
    return artifacts


def _build_analysis_output_json(summary_payload: dict, artifacts: list[dict]) -> dict:
    return {
        "heuristics_version": summary_payload["heuristics_version"],
        "overall_assessment": summary_payload["overall_assessment"],
        "baseline_repo_status": summary_payload["baseline_repo_status"],
        "generated_tests_status": summary_payload["generated_tests_status"],
        "infrastructure_status": summary_payload["infrastructure_status"],
        "analysis_mode": summary_payload["analysis_mode"],
        "llm_summary_available": summary_payload["llm_summary_available"],
        "counts": summary_payload["counts"],
        "highlights": summary_payload["highlights"],
        "artifacts": {artifact["artifact_type"]: artifact["path"] for artifact in artifacts},
    }


def _build_run_summary(summary_payload: dict) -> dict:
    highlights = summary_payload.get("highlights", [])
    headline = highlights[0]["headline"] if highlights else _default_headline(summary_payload["overall_assessment"])
    return {
        "overall_assessment": summary_payload["overall_assessment"],
        "headline": headline,
        "baseline_repo_status": summary_payload["baseline_repo_status"],
        "generated_tests_status": summary_payload["generated_tests_status"],
        "infrastructure_status": summary_payload["infrastructure_status"],
        "high_signal_failures_count": summary_payload["counts"]["high_signal_failures"],
        "top_finding_severity": highlights[0].get("severity") if highlights else None,
        "top_finding_confidence": highlights[0].get("confidence") if highlights else None,
        "flaky_suspects_count": summary_payload["counts"].get("flaky_suspects", 0),
        "llm_summary_available": summary_payload["llm_summary_available"],
    }


def _default_headline(overall_assessment: str) -> str:
    return {
        "all_passed": "Existing and generated test suites completed without failures.",
        "baseline_repo_failed": "The repository's existing tests already fail.",
        "generated_tests_found_new_failures": "Generated tests surfaced new failures while the baseline suite passed.",
        "generated_tests_unrunnable": "Generated tests could not run cleanly in the execution environment.",
        "infrastructure_error": "Execution could not complete because environment setup failed.",
    }.get(overall_assessment, "Run analysis completed.")


def _finalize_run(session, run_id: str) -> None:
    jobs = list_jobs_for_run(session, run_id)
    earlier_failed = any(job.stage != "analyze" and job.status == "failed" for job in jobs)
    if earlier_failed:
        mark_run_failed(session, run_id)
    else:
        mark_run_succeeded(session, run_id)


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _grouped_issue_summaries(failure_records: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for record in failure_records:
        group_key = record.get("group_key")
        if not isinstance(group_key, str):
            continue
        entry = grouped.setdefault(
            group_key,
            {
                "group_key": group_key,
                "count": 0,
                "failure_category": record.get("failure_category"),
                "confidence": record.get("confidence"),
                "severity": record.get("severity"),
                "sample_test_name": record.get("test_name"),
                "sample_message": record.get("message"),
            },
        )
        entry["count"] += 1
    return sorted(grouped.values(), key=lambda item: item["count"], reverse=True)[:5]
