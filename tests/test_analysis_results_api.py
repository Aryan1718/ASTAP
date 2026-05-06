import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.app.auth import CurrentUser, get_current_user
from api.app.main import app
from shared.db import get_session


class DummySession:
    def close(self) -> None:
        return None


def _authorized_client(monkeypatch):
    app.dependency_overrides[get_session] = lambda: DummySession()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id="user-1", email="user@example.com")
    monkeypatch.setattr(
        "api.app.main.get_workspace_for_user",
        lambda session, user_id: SimpleNamespace(id="workspace-1", owner_user_id=user_id),
    )
    return TestClient(app)


def test_analysis_summary_endpoint_returns_summary_payload(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    monkeypatch.setattr(
        "api.app.analysis_results.get_run",
        lambda session, run_id, workspace_id=None: SimpleNamespace(id=run_id, workspace_id="workspace-1") if workspace_id == "workspace-1" else None,
    )
    monkeypatch.setattr(
        "api.app.analysis_results.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(
            run_id=run_id,
            stage=stage,
            status="succeeded",
            artifacts_json=[
                {
                    "artifact_type": "analysis_summary",
                    "bucket": "runs",
                    "key": "workspace-1/project-1/run-1/analyze/summary.json",
                    "path": "analyze/summary.json",
                },
                {
                    "artifact_type": "analysis_report",
                    "bucket": "runs",
                    "key": "workspace-1/project-1/run-1/analyze/llm_summary.md",
                    "path": "analyze/llm_summary.md",
                },
            ],
            output_json={},
        ),
    )
    monkeypatch.setattr(
        "api.app.analysis_results.download_storage_object_text",
        lambda bucket, key: json.dumps(
            {
                "heuristics_version": 1,
                "overall_assessment": "generated_tests_found_new_failures",
                "baseline_repo_status": "passed",
                "generated_tests_status": "failed",
                "infrastructure_status": "ok",
                "analysis_mode": "deterministic_plus_llm",
                "llm_summary_available": True,
                "counts": {
                    "existing_failed": 0,
                    "generated_failed": 1,
                    "high_signal_failures": 1,
                    "infrastructure_errors": 0,
                    "low_signal_failures": 0,
                    "unrunnable_failures": 0,
                    "flaky_suspects": 0,
                },
                "highlights": [
                    {
                        "kind": "generated_failure",
                        "priority": "high",
                        "headline": "Generated test for `parse_config` failed under `Path Traversal`.",
                        "severity": "high",
                        "confidence": "high",
                        "confidence_score": 0.97,
                        "failure_category": "product_failure",
                        "target_key": "abc123",
                        "risk_tags": ["filesystem_access"],
                        "heuristic_tags": ["baseline_suite_passed", "target_mapped"],
                        "evidence": ["AssertionError"],
                    }
                ],
                "trend": {
                    "status": "available",
                    "comparison_run": {
                        "run_id": "run-0",
                        "created_at": "2026-05-05T00:00:00+00:00",
                        "ref_requested": "main",
                        "ref_resolved": "abc123",
                        "overall_assessment": "all_passed",
                    },
                    "counts": {
                        "new_findings": 1,
                        "recurring_findings": 0,
                        "fixed_findings": 0,
                        "recurring_noise": 0,
                    },
                    "headline": "1 new finding appeared versus the previous analyzed run.",
                    "new_findings": [
                        {
                            "fingerprint": "generated|abc123|path_traversal|product_failure|test_parse_config_path_traversal_abc123.py",
                            "suite": "generated",
                            "failure_category": "product_failure",
                            "headline": "Generated test for `parse_config` failed under `Path Traversal`.",
                            "target_key": "abc123",
                            "symbol": "parse_config",
                            "recipe_id": "path_traversal",
                            "recipe_name": "Path Traversal",
                            "generated_test_file": "generated_tests/security/test_parse_config_path_traversal_abc123.py",
                            "confidence": "high",
                            "severity": "high",
                        }
                    ],
                    "fixed_findings": [],
                },
            }
        ),
    )

    response = client.get("/runs/run-1/analysis-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_assessment"] == "generated_tests_found_new_failures"
    assert payload["heuristics_version"] == 1
    assert payload["analysis_mode"] == "deterministic_plus_llm"
    assert payload["counts"]["high_signal_failures"] == 1
    assert payload["highlights"][0]["severity"] == "high"
    assert payload["trend"]["counts"]["new_findings"] == 1
    assert payload["trend"]["comparison_run"]["run_id"] == "run-0"
    assert payload["artifacts"][0]["path"] == "analyze/summary.json"


def test_analysis_report_endpoint_returns_markdown(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    monkeypatch.setattr(
        "api.app.analysis_results.get_run",
        lambda session, run_id, workspace_id=None: SimpleNamespace(id=run_id, workspace_id="workspace-1") if workspace_id == "workspace-1" else None,
    )
    monkeypatch.setattr(
        "api.app.analysis_results.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(
            run_id=run_id,
            stage=stage,
            status="succeeded",
            artifacts_json=[
                {
                    "artifact_type": "analysis_report",
                    "bucket": "runs",
                    "key": "workspace-1/project-1/run-1/analyze/llm_summary.md",
                    "path": "analyze/llm_summary.md",
                }
            ],
            output_json={},
        ),
    )
    monkeypatch.setattr(
        "api.app.analysis_results.download_storage_object_text",
        lambda bucket, key: "# Run Analysis\n\n## Overall\nGenerated tests exposed a failure.\n",
    )

    response = client.get("/runs/run-1/analysis-report")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "path": "analyze/llm_summary.md",
        "content": "# Run Analysis\n\n## Overall\nGenerated tests exposed a failure.\n",
    }


def teardown_function() -> None:
    app.dependency_overrides.clear()
