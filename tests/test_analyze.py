import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.config import Settings
from shared.targets import GeneratedTestManifestEntry, GeneratedTestStatus, RichTargetArtifact, build_discover_targets_artifact, build_generated_test_manifest
from worker.app.jobs.analyze import analyze_job


def _make_target() -> RichTargetArtifact:
    return RichTargetArtifact(
        target_key="abc123",
        target_type="SERVICE_FUNCTION",
        file_path="app/main.py",
        symbol="parse_config",
        signature="parse_config(path: str) -> dict",
        line_start=1,
        line_end=4,
        class_name=None,
        decorators=[],
        framework_hints=["pytest"],
        http_method=None,
        route_path=None,
        recommended_test_kind="unit",
        priority_score=0.9,
        language="python",
        docstring=None,
        dependency_hints=[],
        risk_tags=["filesystem_access", "path_traversal_candidate"],
        input_sources=["function_parameter"],
        dangerous_sinks=["filesystem_access"],
        auth_hints=[],
        execution_context={},
        source_excerpt="def parse_config(path: str) -> dict: ...",
    )


def test_analyze_job_builds_deterministic_and_llm_outputs_and_finalizes_run(monkeypatch: pytest.MonkeyPatch) -> None:
    uploads: dict[str, str] = {}
    marks: dict[str, object] = {}
    summaries: dict[str, dict] = {}

    discover_payload = build_discover_targets_artifact("run-1", [_make_target()])
    manifest = build_generated_test_manifest(
        "run-1",
        [
            GeneratedTestManifestEntry(
                target_key="abc123",
                target_type="SERVICE_FUNCTION",
                symbol="parse_config",
                source_file="app/main.py",
                generated_test_file="generated_tests/security/test_parse_config_path_traversal_abc123.py",
                test_kind="security",
                status=GeneratedTestStatus.generated,
                generation_mode="security_recipe",
                recipe_id="path_traversal",
                recipe_name="Path Traversal",
                risk_tags=["filesystem_access", "path_traversal_candidate"],
            )
        ],
    )
    execute_results = {
        "overall_result": "completed_with_failures",
        "error": None,
        "environment": {"platform_system": "Linux"},
        "existing_tests": {"status": "passed", "failed": 0, "errors": 0},
        "generated_tests": {"status": "failed", "failed": 1, "errors": 0},
    }
    generated_junit = """
<testsuite tests="1" failures="1" errors="0" skipped="0">
  <testcase classname="test_parse_config_path_traversal_abc123" name="test_generated_path_traversal_signal" file="generated_tests/security/test_parse_config_path_traversal_abc123.py" time="0.7">
    <failure message="assert parse_config('../etc/passwd') == {'path': 'safe'}">AssertionError: expected sanitized path</failure>
  </testcase>
</testsuite>
""".strip()
    existing_junit = """
<testsuite tests="1" failures="0" errors="0" skipped="0">
  <testcase classname="tests.test_existing" name="test_existing_parse_config" time="0.2" />
</testsuite>
""".strip()

    class FakeSession:
        def close(self) -> None:
            return None

    class FakeProvider:
        def __init__(self, api_key: str, config) -> None:
            self.api_key = api_key
            self.config = config

        def generate_summary(self, evidence_packet: dict) -> str:
            assert evidence_packet["overall_assessment"] == "generated_tests_found_new_failures"
            return "# Run Analysis\n\n## Overall\nGenerated tests exposed a failure.\n"

    monkeypatch.setattr("worker.app.jobs.analyze.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.analyze.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            created_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
        ),
    )
    monkeypatch.setattr("worker.app.jobs.analyze.list_prior_project_runs", lambda session, project_id, before_created_at, exclude_run_id: [])
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_job_by_stage",
        lambda session, run_id, stage: (
            SimpleNamespace(
                stage="discover",
                artifacts_json=[
                    {
                        "artifact_type": "discover_targets",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/discover/targets.json",
                        "path": "discover/targets.json",
                    }
                ],
                output_json={},
            )
            if stage == "discover"
            else SimpleNamespace(
                stage="generate_tests",
                artifacts_json=[
                    {
                        "artifact_type": "generated_tests_manifest",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/generated_tests/test_index.json",
                        "path": "generated_tests/test_index.json",
                    }
                ],
                output_json={},
            )
            if stage == "generate_tests"
            else SimpleNamespace(
                stage="execute_tests",
                status="succeeded",
                artifacts_json=[
                    {
                        "artifact_type": "execution_results",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/execute_tests/results.json",
                        "path": "execute_tests/results.json",
                    },
                    {
                        "artifact_type": "execution_junit",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/execute_tests/junit/existing-tests.xml",
                        "path": "execute_tests/junit/existing-tests.xml",
                    },
                    {
                        "artifact_type": "execution_junit",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/execute_tests/junit/generated-tests.xml",
                        "path": "execute_tests/junit/generated-tests.xml",
                    },
                ],
                output_json=execute_results,
            )
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.download_storage_object_text",
        lambda bucket, key: (
            json.dumps(discover_payload.model_dump(mode="json"))
            if key.endswith("discover/targets.json")
            else json.dumps(manifest.model_dump(mode="json"))
            if key.endswith("generated_tests/test_index.json")
            else json.dumps(execute_results)
            if key.endswith("execute_tests/results.json")
            else existing_junit
            if key.endswith("existing-tests.xml")
            else generated_junit
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.mark_job_succeeded_with_artifacts",
        lambda session, job_id, output_json, artifacts_json: marks.update(
            {"job_id": job_id, "output_json": output_json, "artifacts_json": artifacts_json}
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.list_jobs_for_run",
        lambda session, run_id: [
            SimpleNamespace(stage="discover", status="succeeded"),
            SimpleNamespace(stage="generate_tests", status="succeeded"),
            SimpleNamespace(stage="execute_tests", status="succeeded"),
            SimpleNamespace(stage="analyze", status="succeeded"),
        ],
    )
    monkeypatch.setattr("worker.app.jobs.analyze.update_run_summary", lambda session, run_id, summary: summaries.update({run_id: summary}))
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_succeeded", lambda session, run_id: marks.update({"run_succeeded": run_id}))
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_failed", lambda session, run_id: marks.update({"run_failed": run_id}))
    monkeypatch.setattr(
        "worker.app.jobs.analyze.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            OPENAI_API_KEY="test-key",
            ANALYZE_ENABLE_LLM=True,
        ),
    )
    monkeypatch.setattr("worker.app.jobs.analyze.OpenAIAnalyzeProvider", FakeProvider)

    analyze_job("run-1", "job-1")

    summary_key = "workspace-1/project-1/run-1/analyze/summary.json"
    failures_key = "workspace-1/project-1/run-1/analyze/failures.json"
    report_key = "workspace-1/project-1/run-1/analyze/llm_summary.md"
    assert summary_key in uploads
    assert failures_key in uploads
    assert report_key in uploads

    summary_payload = json.loads(uploads[summary_key])
    failures_payload = json.loads(uploads[failures_key])
    assert summary_payload["overall_assessment"] == "generated_tests_found_new_failures"
    assert summary_payload["heuristics_version"] == 2
    assert summary_payload["analysis_mode"] == "deterministic_plus_llm"
    assert summary_payload["llm_summary_available"] is True
    assert summary_payload["trend"]["status"] == "unavailable"
    assert summary_payload["counts"]["high_signal_failures"] == 1
    assert summary_payload["counts"]["low_signal_failures"] == 0
    assert summary_payload["highlights"][0]["target_key"] == "abc123"
    assert summary_payload["highlights"][0]["severity"] == "high"
    assert summary_payload["highlights"][0]["confidence"] == "high"
    assert summary_payload["highlights"][0]["failure_category"] == "product_failure"
    assert failures_payload["failures"][0]["recipe_id"] == "path_traversal"
    assert failures_payload["failures"][0]["confidence_score"] >= 0.8
    assert summaries["run-1"]["headline"].startswith("Generated test for")
    assert summaries["run-1"]["trend_status"] == "unavailable"
    assert summaries["run-1"]["top_finding_severity"] == "high"
    assert summaries["run-1"]["top_finding_confidence"] == "high"
    assert marks["run_succeeded"] == "run-1"


def test_analyze_job_classifies_infrastructure_error_without_llm_and_marks_run_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    uploads: dict[str, str] = {}
    marks: dict[str, object] = {}

    discover_payload = build_discover_targets_artifact("run-1", [_make_target()])
    manifest = build_generated_test_manifest("run-1", [])
    execute_results = {
        "overall_result": "environment_setup_failed",
        "error": {"type": "environment_setup_failed", "message": "Dependency install failed"},
        "existing_tests": {"status": "error", "failed": 0, "errors": 0},
        "generated_tests": {"status": "skipped", "failed": 0, "errors": 0},
    }

    class FakeSession:
        def close(self) -> None:
            return None

    monkeypatch.setattr("worker.app.jobs.analyze.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.analyze.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            created_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
        ),
    )
    monkeypatch.setattr("worker.app.jobs.analyze.list_prior_project_runs", lambda session, project_id, before_created_at, exclude_run_id: [])
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_job_by_stage",
        lambda session, run_id, stage: (
            SimpleNamespace(
                artifacts_json=[{"bucket": "runs", "key": "workspace-1/project-1/run-1/discover/targets.json", "path": "discover/targets.json"}],
                output_json={},
            )
            if stage == "discover"
            else SimpleNamespace(
                artifacts_json=[{"artifact_type": "generated_tests_manifest", "bucket": "runs", "key": "workspace-1/project-1/run-1/generated_tests/test_index.json"}],
                output_json={},
            )
            if stage == "generate_tests"
            else SimpleNamespace(
                status="failed",
                artifacts_json=[{"artifact_type": "execution_results", "bucket": "runs", "key": "workspace-1/project-1/run-1/execute_tests/results.json"}],
                output_json=execute_results,
            )
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.download_storage_object_text",
        lambda bucket, key: (
            json.dumps(discover_payload.model_dump(mode="json"))
            if key.endswith("discover/targets.json")
            else json.dumps(manifest.model_dump(mode="json"))
            if key.endswith("generated_tests/test_index.json")
            else json.dumps(execute_results)
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr("worker.app.jobs.analyze.mark_job_succeeded_with_artifacts", lambda session, job_id, output_json, artifacts_json: marks.update({"output_json": output_json}))
    monkeypatch.setattr(
        "worker.app.jobs.analyze.list_jobs_for_run",
        lambda session, run_id: [
            SimpleNamespace(stage="discover", status="succeeded"),
            SimpleNamespace(stage="generate_tests", status="succeeded"),
            SimpleNamespace(stage="execute_tests", status="failed"),
            SimpleNamespace(stage="analyze", status="succeeded"),
        ],
    )
    monkeypatch.setattr("worker.app.jobs.analyze.update_run_summary", lambda session, run_id, summary: None)
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_succeeded", lambda session, run_id: marks.update({"run_succeeded": run_id}))
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_failed", lambda session, run_id: marks.update({"run_failed": run_id}))
    monkeypatch.setattr(
        "worker.app.jobs.analyze.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            ANALYZE_ENABLE_LLM=False,
        ),
    )

    analyze_job("run-1", "job-1")

    summary_payload = json.loads(uploads["workspace-1/project-1/run-1/analyze/summary.json"])
    assert summary_payload["overall_assessment"] == "infrastructure_error"
    assert summary_payload["highlights"][0]["severity"] == "critical"
    assert summary_payload["highlights"][0]["failure_category"] == "environment_issue"
    assert summary_payload["analysis_mode"] == "deterministic_only"
    assert summary_payload["llm_summary_available"] is False
    assert marks["output_json"]["infrastructure_status"] == "error"
    assert marks["run_failed"] == "run-1"


def test_analyze_job_downgrades_repeated_generated_import_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    uploads: dict[str, str] = {}

    discover_payload = build_discover_targets_artifact("run-1", [_make_target()])
    manifest = build_generated_test_manifest(
        "run-1",
        [
            GeneratedTestManifestEntry(
                target_key="abc123",
                target_type="SERVICE_FUNCTION",
                symbol="parse_config",
                source_file="app/main.py",
                generated_test_file="generated_tests/security/test_parse_config_path_traversal_abc123.py",
                test_kind="security",
                status=GeneratedTestStatus.generated,
                generation_mode="security_recipe",
                recipe_id="path_traversal",
                recipe_name="Path Traversal",
                risk_tags=["filesystem_access", "path_traversal_candidate"],
            ),
            GeneratedTestManifestEntry(
                target_key="def456",
                target_type="SERVICE_FUNCTION",
                symbol="parse_config_again",
                source_file="app/main.py",
                generated_test_file="generated_tests/security/test_parse_config_again_path_traversal_def456.py",
                test_kind="security",
                status=GeneratedTestStatus.generated,
                generation_mode="security_recipe",
                recipe_id="path_traversal",
                recipe_name="Path Traversal",
                risk_tags=["filesystem_access", "path_traversal_candidate"],
            ),
        ],
    )
    execute_results = {
        "overall_result": "completed_with_failures",
        "error": None,
        "existing_tests": {"status": "passed", "failed": 0, "errors": 0},
        "generated_tests": {"status": "failed", "failed": 0, "errors": 2},
    }
    generated_junit = """
<testsuite tests="2" failures="0" errors="2" skipped="0">
  <testcase classname="test_parse_config_path_traversal_abc123" name="test_generated_path_traversal_signal" file="generated_tests/security/test_parse_config_path_traversal_abc123.py" time="0.7">
    <error message="ImportError: cannot import name TestClient">ImportError: cannot import name TestClient</error>
  </testcase>
  <testcase classname="test_parse_config_again_path_traversal_def456" name="test_generated_path_traversal_signal_2" file="generated_tests/security/test_parse_config_again_path_traversal_def456.py" time="0.5">
    <error message="ImportError: cannot import name TestClient">ImportError: cannot import name TestClient</error>
  </testcase>
</testsuite>
""".strip()

    class FakeSession:
        def close(self) -> None:
            return None

    monkeypatch.setattr("worker.app.jobs.analyze.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.analyze.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            created_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
        ),
    )
    monkeypatch.setattr("worker.app.jobs.analyze.list_prior_project_runs", lambda session, project_id, before_created_at, exclude_run_id: [])
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_job_by_stage",
        lambda session, run_id, stage: (
            SimpleNamespace(
                stage="discover",
                artifacts_json=[
                    {
                        "artifact_type": "discover_targets",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/discover/targets.json",
                        "path": "discover/targets.json",
                    }
                ],
                output_json={},
            )
            if stage == "discover"
            else SimpleNamespace(
                stage="generate_tests",
                artifacts_json=[
                    {
                        "artifact_type": "generated_tests_manifest",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/generated_tests/test_index.json",
                        "path": "generated_tests/test_index.json",
                    }
                ],
                output_json={},
            )
            if stage == "generate_tests"
            else SimpleNamespace(
                stage="execute_tests",
                status="succeeded",
                artifacts_json=[
                    {
                        "artifact_type": "execution_results",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/execute_tests/results.json",
                        "path": "execute_tests/results.json",
                    },
                    {
                        "artifact_type": "execution_junit",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/execute_tests/junit/generated-tests.xml",
                        "path": "execute_tests/junit/generated-tests.xml",
                    },
                ],
                output_json=execute_results,
            )
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.download_storage_object_text",
        lambda bucket, key: (
            json.dumps(discover_payload.model_dump(mode="json"))
            if key.endswith("discover/targets.json")
            else json.dumps(manifest.model_dump(mode="json"))
            if key.endswith("generated_tests/test_index.json")
            else json.dumps(execute_results)
            if key.endswith("execute_tests/results.json")
            else generated_junit
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.mark_job_succeeded_with_artifacts",
        lambda session, job_id, output_json, artifacts_json: None,
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.list_jobs_for_run",
        lambda session, run_id: [
            SimpleNamespace(stage="discover", status="succeeded"),
            SimpleNamespace(stage="generate_tests", status="succeeded"),
            SimpleNamespace(stage="execute_tests", status="succeeded"),
            SimpleNamespace(stage="analyze", status="succeeded"),
        ],
    )
    monkeypatch.setattr("worker.app.jobs.analyze.update_run_summary", lambda session, run_id, summary: None)
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_succeeded", lambda session, run_id: None)
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_failed", lambda session, run_id: None)
    monkeypatch.setattr(
        "worker.app.jobs.analyze.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            ANALYZE_ENABLE_LLM=False,
        ),
    )

    analyze_job("run-1", "job-1")

    summary_payload = json.loads(uploads["workspace-1/project-1/run-1/analyze/summary.json"])
    first = summary_payload["highlights"][0]
    assert summary_payload["overall_assessment"] == "generated_tests_unrunnable"
    assert summary_payload["counts"]["low_signal_failures"] == 2
    assert summary_payload["counts"]["unrunnable_failures"] == 2
    assert first["severity"] == "low"
    assert first["confidence"] == "low"
    assert first["failure_category"] == "generated_test_issue"
    assert "repeated_setup_error" in first["heuristic_tags"]


def test_analyze_job_marks_generated_collection_failures_as_unrunnable(monkeypatch: pytest.MonkeyPatch) -> None:
    uploads: dict[str, str] = {}

    discover_payload = build_discover_targets_artifact("run-1", [_make_target()])
    manifest = build_generated_test_manifest(
        "run-1",
        [
            GeneratedTestManifestEntry(
                target_key="abc123",
                target_type="SERVICE_FUNCTION",
                symbol="parse_config",
                source_file="app/main.py",
                generated_test_file="generated_tests/services/test_parse_config_abc123.py",
                test_kind="unit",
                status=GeneratedTestStatus.generated,
                generation_mode="generic_fallback",
                risk_tags=["filesystem_access"],
            )
        ],
    )
    execute_results = {
        "overall_result": "generated_tests_quality_failed",
        "error": None,
        "existing_tests": {"status": "passed", "failed": 0, "errors": 0},
        "generated_tests": {
            "status": "skipped",
            "quality_status": "unrunnable",
            "quality_failure_reason": "no_generated_tests_collected",
            "failed": 0,
            "errors": 0,
            "file_results": [
                {
                    "path": "generated_tests/services/test_parse_config_abc123.py",
                    "target_key": "abc123",
                    "symbol": "parse_config",
                    "status": "collection_failed",
                    "message": "ImportError: cannot import name TestClient",
                }
            ],
        },
    }

    class FakeSession:
        def close(self) -> None:
            return None

    monkeypatch.setattr("worker.app.jobs.analyze.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.analyze.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            created_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
        ),
    )
    monkeypatch.setattr("worker.app.jobs.analyze.list_prior_project_runs", lambda session, project_id, before_created_at, exclude_run_id: [])
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_job_by_stage",
        lambda session, run_id, stage: (
            SimpleNamespace(
                stage="discover",
                artifacts_json=[{"artifact_type": "discover_targets", "bucket": "runs", "key": "workspace-1/project-1/run-1/discover/targets.json", "path": "discover/targets.json"}],
                output_json={},
            )
            if stage == "discover"
            else SimpleNamespace(
                stage="generate_tests",
                artifacts_json=[{"artifact_type": "generated_tests_manifest", "bucket": "runs", "key": "workspace-1/project-1/run-1/generated_tests/test_index.json", "path": "generated_tests/test_index.json"}],
                output_json={},
            )
            if stage == "generate_tests"
            else SimpleNamespace(
                stage="execute_tests",
                status="succeeded",
                artifacts_json=[{"artifact_type": "execution_results", "bucket": "runs", "key": "workspace-1/project-1/run-1/execute_tests/results.json", "path": "execute_tests/results.json"}],
                output_json=execute_results,
            )
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.download_storage_object_text",
        lambda bucket, key: (
            json.dumps(discover_payload.model_dump(mode="json"))
            if key.endswith("discover/targets.json")
            else json.dumps(manifest.model_dump(mode="json"))
            if key.endswith("generated_tests/test_index.json")
            else json.dumps(execute_results)
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr("worker.app.jobs.analyze.mark_job_succeeded_with_artifacts", lambda session, job_id, output_json, artifacts_json: None)
    monkeypatch.setattr(
        "worker.app.jobs.analyze.list_jobs_for_run",
        lambda session, run_id: [
            SimpleNamespace(stage="discover", status="succeeded"),
            SimpleNamespace(stage="generate_tests", status="succeeded"),
            SimpleNamespace(stage="execute_tests", status="succeeded"),
            SimpleNamespace(stage="analyze", status="succeeded"),
        ],
    )
    monkeypatch.setattr("worker.app.jobs.analyze.update_run_summary", lambda session, run_id, summary: None)
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_succeeded", lambda session, run_id: None)
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_failed", lambda session, run_id: None)
    monkeypatch.setattr(
        "worker.app.jobs.analyze.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            ANALYZE_ENABLE_LLM=False,
        ),
    )

    analyze_job("run-1", "job-1")

    summary_payload = json.loads(uploads["workspace-1/project-1/run-1/analyze/summary.json"])
    failures_payload = json.loads(uploads["workspace-1/project-1/run-1/analyze/failures.json"])
    assert summary_payload["overall_assessment"] == "generated_tests_unrunnable"
    assert summary_payload["generated_tests_status"] == "unrunnable"
    assert summary_payload["counts"]["high_signal_failures"] == 0
    assert summary_payload["counts"]["low_signal_failures"] == 1
    assert failures_payload["failures"][0]["failure_category"] == "generated_test_issue"
    assert "generated_suite_unrunnable" in failures_payload["failures"][0]["heuristic_tags"]


def test_analyze_job_builds_trend_comparison_against_previous_analyzed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    uploads: dict[str, str] = {}

    discover_payload = build_discover_targets_artifact("run-1", [_make_target()])
    manifest = build_generated_test_manifest(
        "run-1",
        [
            GeneratedTestManifestEntry(
                target_key="abc123",
                target_type="SERVICE_FUNCTION",
                symbol="parse_config",
                source_file="app/main.py",
                generated_test_file="generated_tests/security/test_parse_config_path_traversal_abc123.py",
                test_kind="security",
                status=GeneratedTestStatus.generated,
                generation_mode="security_recipe",
                recipe_id="path_traversal",
                recipe_name="Path Traversal",
                risk_tags=["filesystem_access", "path_traversal_candidate"],
            )
        ],
    )
    execute_results = {
        "overall_result": "completed_with_failures",
        "error": None,
        "existing_tests": {"status": "passed", "failed": 0, "errors": 0},
        "generated_tests": {"status": "failed", "failed": 1, "errors": 0},
    }
    generated_junit = """
<testsuite tests="1" failures="1" errors="0" skipped="0">
  <testcase classname="test_parse_config_path_traversal_abc123" name="test_generated_path_traversal_signal" file="generated_tests/security/test_parse_config_path_traversal_abc123.py" time="0.7">
    <failure message="assert parse_config('../etc/passwd') == {'path': 'safe'}">AssertionError: expected sanitized path</failure>
  </testcase>
</testsuite>
""".strip()
    previous_summary = {
        "overall_assessment": "generated_tests_unrunnable",
    }
    previous_failures = {
        "run_id": "run-0",
        "heuristics_version": 2,
        "failures": [
            {
                "suite": "generated",
                "status": "error",
                "test_name": "test_old_import_issue",
                "classname": "test_old_import_issue",
                "file_path": "generated_tests/security/test_old_import_issue.py",
                "message": "ImportError: cannot import name TestClient",
                "traceback_excerpt": "ImportError: cannot import name TestClient",
                "target_key": "old111",
                "symbol": "legacy_parse",
                "source_file": "app/legacy.py",
                "recipe_id": "path_traversal",
                "recipe_name": "Path Traversal",
                "generated_test_file": "generated_tests/security/test_old_import_issue.py",
                "risk_tags": ["filesystem_access"],
                "failure_category": "generated_test_issue",
                "confidence": "low",
                "severity": "low",
                "fingerprint": "generated|old111|path_traversal|generated_test_issue|test_old_import_issue.py",
            }
        ],
    }

    class FakeSession:
        def close(self) -> None:
            return None

    monkeypatch.setattr("worker.app.jobs.analyze.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.analyze.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            created_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.list_prior_project_runs",
        lambda session, project_id, before_created_at, exclude_run_id: [
            SimpleNamespace(
                id="run-0",
                project_id=project_id,
                created_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
                ref_requested="main",
                ref_resolved="abc123",
            )
        ],
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_job_by_stage",
        lambda session, run_id, stage: (
            SimpleNamespace(
                stage="analyze",
                status="succeeded",
                artifacts_json=[
                    {
                        "artifact_type": "analysis_summary",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-0/analyze/summary.json",
                        "path": "analyze/summary.json",
                    },
                    {
                        "artifact_type": "analysis_failures",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-0/analyze/failures.json",
                        "path": "analyze/failures.json",
                    },
                ],
                output_json={},
            )
            if run_id == "run-0" and stage == "analyze"
            else SimpleNamespace(
                stage="discover",
                artifacts_json=[
                    {
                        "artifact_type": "discover_targets",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/discover/targets.json",
                        "path": "discover/targets.json",
                    }
                ],
                output_json={},
            )
            if stage == "discover"
            else SimpleNamespace(
                stage="generate_tests",
                artifacts_json=[
                    {
                        "artifact_type": "generated_tests_manifest",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/generated_tests/test_index.json",
                        "path": "generated_tests/test_index.json",
                    }
                ],
                output_json={},
            )
            if stage == "generate_tests"
            else SimpleNamespace(
                stage="execute_tests",
                status="succeeded",
                artifacts_json=[
                    {
                        "artifact_type": "execution_results",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/execute_tests/results.json",
                        "path": "execute_tests/results.json",
                    },
                    {
                        "artifact_type": "execution_junit",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/execute_tests/junit/generated-tests.xml",
                        "path": "execute_tests/junit/generated-tests.xml",
                    },
                ],
                output_json=execute_results,
            )
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.download_storage_object_text",
        lambda bucket, key: (
            json.dumps(previous_summary)
            if key.endswith("run-0/analyze/summary.json")
            else json.dumps(previous_failures)
            if key.endswith("run-0/analyze/failures.json")
            else json.dumps(discover_payload.model_dump(mode="json"))
            if key.endswith("discover/targets.json")
            else json.dumps(manifest.model_dump(mode="json"))
            if key.endswith("generated_tests/test_index.json")
            else json.dumps(execute_results)
            if key.endswith("execute_tests/results.json")
            else generated_junit
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr("worker.app.jobs.analyze.mark_job_succeeded_with_artifacts", lambda session, job_id, output_json, artifacts_json: None)
    monkeypatch.setattr(
        "worker.app.jobs.analyze.list_jobs_for_run",
        lambda session, run_id: [
            SimpleNamespace(stage="discover", status="succeeded"),
            SimpleNamespace(stage="generate_tests", status="succeeded"),
            SimpleNamespace(stage="execute_tests", status="succeeded"),
            SimpleNamespace(stage="analyze", status="succeeded"),
        ],
    )
    monkeypatch.setattr("worker.app.jobs.analyze.update_run_summary", lambda session, run_id, summary: None)
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_succeeded", lambda session, run_id: None)
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_failed", lambda session, run_id: None)
    monkeypatch.setattr(
        "worker.app.jobs.analyze.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            ANALYZE_ENABLE_LLM=False,
        ),
    )

    analyze_job("run-1", "job-1")

    summary_payload = json.loads(uploads["workspace-1/project-1/run-1/analyze/summary.json"])
    assert summary_payload["trend"]["status"] == "available"
    assert summary_payload["trend"]["comparison_run"]["run_id"] == "run-0"
    assert summary_payload["trend"]["counts"]["new_findings"] == 1
    assert summary_payload["trend"]["counts"]["fixed_findings"] == 1
    assert summary_payload["trend"]["new_findings"][0]["target_key"] == "abc123"


def test_analyze_job_downgrades_windows_only_path_traversal_signal_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    uploads: dict[str, str] = {}

    discover_payload = build_discover_targets_artifact("run-1", [_make_target()])
    manifest = build_generated_test_manifest(
        "run-1",
        [
            GeneratedTestManifestEntry(
                target_key="abc123",
                target_type="SERVICE_FUNCTION",
                symbol="parse_config",
                source_file="app/main.py",
                generated_test_file="generated_tests/security/test_parse_config_path_traversal_abc123.py",
                test_kind="security",
                status=GeneratedTestStatus.generated,
                generation_mode="security_recipe",
                recipe_id="path_traversal",
                recipe_name="Path Traversal",
                risk_tags=["filesystem_access", "path_traversal_candidate"],
            )
        ],
    )
    execute_results = {
        "overall_result": "completed_with_failures",
        "error": None,
        "environment": {"platform_system": "Linux"},
        "existing_tests": {"status": "passed", "failed": 0, "errors": 0},
        "generated_tests": {"status": "failed", "failed": 1, "errors": 0},
    }
    generated_junit = """
<testsuite tests="1" failures="1" errors="0" skipped="0">
  <testcase classname="test_parse_config_path_traversal_abc123" name="test_save_rdb_rejects_path_traversal_windows" file="generated_tests/security/test_parse_config_path_traversal_abc123.py" time="0.2">
    <failure message="Failed: DID NOT RAISE any of (&lt;class 'OSError'&gt;, &lt;class 'IOError'&gt;)">tmp_path = PosixPath('/workspace/tmp/pytest-of-unknown/pytest-0/test_save_rdb_rejects_path_tra1')
E   Failed: DID NOT RAISE any of (&lt;class 'OSError'&gt;, &lt;class 'IOError'&gt;)
E   traversal_path = tmp_path / "..\\..\\windows\\win.ini"</failure>
  </testcase>
</testsuite>
""".strip()

    class FakeSession:
        def close(self) -> None:
            return None

    monkeypatch.setattr("worker.app.jobs.analyze.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.analyze.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            created_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
        ),
    )
    monkeypatch.setattr("worker.app.jobs.analyze.list_prior_project_runs", lambda session, project_id, before_created_at, exclude_run_id: [])
    monkeypatch.setattr(
        "worker.app.jobs.analyze.get_job_by_stage",
        lambda session, run_id, stage: (
            SimpleNamespace(
                artifacts_json=[{"artifact_type": "discover_targets", "bucket": "runs", "key": "workspace-1/project-1/run-1/discover/targets.json", "path": "discover/targets.json"}],
                output_json={},
            )
            if stage == "discover"
            else SimpleNamespace(
                artifacts_json=[{"artifact_type": "generated_tests_manifest", "bucket": "runs", "key": "workspace-1/project-1/run-1/generated_tests/test_index.json", "path": "generated_tests/test_index.json"}],
                output_json={},
            )
            if stage == "generate_tests"
            else SimpleNamespace(
                status="succeeded",
                artifacts_json=[
                    {"artifact_type": "execution_results", "bucket": "runs", "key": "workspace-1/project-1/run-1/execute_tests/results.json", "path": "execute_tests/results.json"},
                    {"artifact_type": "execution_junit", "bucket": "runs", "key": "workspace-1/project-1/run-1/execute_tests/junit/generated-tests.xml", "path": "execute_tests/junit/generated-tests.xml"},
                ],
                output_json=execute_results,
            )
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.download_storage_object_text",
        lambda bucket, key: (
            json.dumps(discover_payload.model_dump(mode="json"))
            if key.endswith("discover/targets.json")
            else json.dumps(manifest.model_dump(mode="json"))
            if key.endswith("generated_tests/test_index.json")
            else json.dumps(execute_results)
            if key.endswith("execute_tests/results.json")
            else generated_junit
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.analyze.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr("worker.app.jobs.analyze.mark_job_succeeded_with_artifacts", lambda session, job_id, output_json, artifacts_json: None)
    monkeypatch.setattr(
        "worker.app.jobs.analyze.list_jobs_for_run",
        lambda session, run_id: [
            SimpleNamespace(stage="discover", status="succeeded"),
            SimpleNamespace(stage="generate_tests", status="succeeded"),
            SimpleNamespace(stage="execute_tests", status="succeeded"),
            SimpleNamespace(stage="analyze", status="succeeded"),
        ],
    )
    monkeypatch.setattr("worker.app.jobs.analyze.update_run_summary", lambda session, run_id, summary: None)
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_succeeded", lambda session, run_id: None)
    monkeypatch.setattr("worker.app.jobs.analyze.mark_run_failed", lambda session, run_id: None)
    monkeypatch.setattr(
        "worker.app.jobs.analyze.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            ANALYZE_ENABLE_LLM=False,
        ),
    )

    analyze_job("run-1", "job-1")

    summary_payload = json.loads(uploads["workspace-1/project-1/run-1/analyze/summary.json"])
    highlight = summary_payload["highlights"][0]
    assert highlight["failure_category"] == "generated_test_issue"
    assert highlight["severity"] == "low"
    assert highlight["confidence"] == "medium"
    assert "windows_only_path_case" in highlight["heuristic_tags"]
