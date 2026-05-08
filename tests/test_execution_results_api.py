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


def _patch_run_and_job(monkeypatch, *, status="succeeded", artifacts_json=None, output_json=None):
    monkeypatch.setattr(
        "api.app.execution_results.get_run",
        lambda session, run_id, workspace_id=None: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
        )
        if workspace_id == "workspace-1"
        else None,
    )
    monkeypatch.setattr(
        "api.app.execution_results.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(
            run_id=run_id,
            stage=stage,
            status=status,
            artifacts_json=artifacts_json or [],
            output_json=output_json or {},
        ),
    )


def test_execution_summary_endpoint_returns_results_payload(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(
        monkeypatch,
        artifacts_json=[
            {
                "artifact_type": "execution_results",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/execute_tests/results.json",
                "path": "execute_tests/results.json",
            },
            {
                "artifact_type": "execution_log",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/execute_tests/logs/existing-tests.log",
                "path": "execute_tests/logs/existing-tests.log",
            },
        ],
    )
    monkeypatch.setattr(
        "api.app.execution_results.download_storage_object_text",
        lambda bucket, key: json.dumps(
            {
                "framework": "pytest",
                "overall_result": "completed_with_failures",
                "environment": {
                    "python_version": "3.12.3",
                    "platform_system": "Linux",
                    "execution_image": "astsp-executor:latest",
                    "working_directory": "repo",
                    "generated_tests_root": ".astap/generated_tests",
                },
                "execution_plan": {
                    "framework": "pytest",
                    "install_commands": [],
                    "existing_test_command": {
                        "command": ["python", "-m", "pytest", "tests"],
                        "source": "repo_detection.pytest",
                    },
                    "generated_test_command": {
                        "command": ["python", "-m", "pytest", ".astap/generated_tests"],
                        "source": "platform_default.generated_pytest",
                    },
                    "suite_timeout_seconds": 600,
                    "detection_notes": ["Detected requirements.txt for dependency installation"],
                },
                "attempted_commands": [
                    ["python", "-m", "pytest", "tests"],
                ],
                "existing_tests": {
                    "suite_key": "existing",
                    "status": "passed",
                    "command": ["python", "-m", "pytest", "tests"],
                    "command_source": "repo_detection.pytest",
                    "exit_code": 0,
                    "collected": 3,
                    "passed": 3,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 0,
                    "duration_seconds": 1.25,
                    "log_path": "execute_tests/logs/existing-tests.log",
                    "junit_path": "execute_tests/junit/existing-tests.xml",
                },
                "generated_tests": {
                    "suite_key": "generated",
                    "status": "failed",
                    "command": ["python", "-m", "pytest", ".astap/generated_tests"],
                    "exit_code": 1,
                    "collected": 2,
                    "passed": 1,
                    "failed": 1,
                    "errors": 0,
                    "skipped": 0,
                    "duration_seconds": 0.8,
                    "log_path": "execute_tests/logs/generated-tests.log",
                    "junit_path": "execute_tests/junit/generated-tests.xml",
                },
                "combined_tests": None,
            }
        ),
    )

    response = client.get("/runs/run-1/execution-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-1"
    assert payload["stage_status"] == "succeeded"
    assert payload["environment"]["python_version"] == "3.12.3"
    assert payload["environment"]["platform_system"] == "Linux"
    assert payload["execution_plan"]["existing_test_command"]["source"] == "repo_detection.pytest"
    assert payload["attempted_commands"][0] == ["python", "-m", "pip", "install", "pytest"]
    assert payload["existing_tests"]["passed"] == 3
    assert payload["existing_tests"]["command_source"] == "repo_detection.pytest"
    assert payload["generated_tests"]["failed"] == 1
    assert payload["artifacts"][0]["path"] == "execute_tests/results.json"


def test_execution_summary_endpoint_falls_back_to_job_output_json(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(
        monkeypatch,
        artifacts_json=[],
        output_json={
            "framework": "pytest",
            "python_version": "3.12.2",
            "overall_result": "completed_successfully",
            "execution_plan": {
                "framework": "pytest",
                "install_commands": [],
                "existing_test_command": {
                    "command": ["python", "-m", "pytest", "tests"],
                    "source": "repo_detection.pytest",
                },
                "generated_test_command": {
                    "command": ["python", "-m", "pytest", ".astap/generated_tests"],
                    "source": "platform_default.generated_pytest",
                },
                "suite_timeout_seconds": 600,
                "detection_notes": [],
            },
            "attempted_commands": [["python", "-m", "pytest", "tests"]],
            "existing_tests": {
                "suite_key": "existing",
                "status": "passed",
                "command_source": "repo_detection.pytest",
                "collected": 5,
                "passed": 5,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "duration_seconds": 2.4,
            },
            "generated_tests": {
                "suite_key": "generated",
                "status": "skipped",
                "collected": 0,
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "duration_seconds": 0.0,
            },
            "combined_tests": None,
        },
    )

    response = client.get("/runs/run-1/execution-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["environment"]["python_version"] == "3.12.2"
    assert payload["execution_plan"]["suite_timeout_seconds"] == 600
    assert payload["attempted_commands"][0] == ["python", "-m", "pytest", "tests"]
    assert payload["generated_tests"]["status"] == "skipped"


def test_execution_log_endpoint_returns_requested_suite_log(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(
        monkeypatch,
        artifacts_json=[
            {
                "artifact_type": "execution_log",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/execute_tests/logs/generated-tests.log",
                "path": "execute_tests/logs/generated-tests.log",
            }
        ],
    )
    monkeypatch.setattr(
        "api.app.execution_results.download_storage_object_text",
        lambda bucket, key: "generated suite log content\n",
    )

    response = client.get("/runs/run-1/execution-log", params={"suite": "generated"})

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "suite_key": "generated",
        "path": "execute_tests/logs/generated-tests.log",
        "content": "generated suite log content\n",
    }


def test_execution_log_endpoint_rejects_unknown_suite(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(monkeypatch)

    response = client.get("/runs/run-1/execution-log", params={"suite": "bogus"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported suite key"


def teardown_function() -> None:
    app.dependency_overrides.clear()
