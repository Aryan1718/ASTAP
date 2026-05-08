import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.app.auth import CurrentUser, get_current_user
from api.app.main import app
from shared.db import get_session
from shared.targets import (
    GeneratedTestManifestEntry,
    GeneratedTestStatus,
    build_generated_test_manifest,
)


def _build_manifest_payload(run_id: str = "run-1") -> str:
    manifest = build_generated_test_manifest(
        run_id,
        [
            GeneratedTestManifestEntry(
                target_key="abc123",
                target_type="SERVICE_FUNCTION",
                symbol="parse_config",
                source_file="app/utils.py",
                generated_test_file="generated_tests/services/test_parse_config_a1b2c3.py",
                test_kind="unit",
                status=GeneratedTestStatus.generated,
            ),
            GeneratedTestManifestEntry(
                target_key="def456",
                target_type="API_ENDPOINT",
                symbol="get_user",
                source_file="app/api.py",
                generated_test_file="generated_tests/api/test_get_user_f9e8d7.py",
                test_kind="api",
                status=GeneratedTestStatus.generated,
            ),
            GeneratedTestManifestEntry(
                target_key="skip789",
                target_type="WORKFLOW_STEP",
                symbol="ignored",
                source_file="app/workflow.py",
                status=GeneratedTestStatus.skipped,
                skip_reason="unsupported_target_type:WORKFLOW_STEP",
            ),
        ],
    )
    return json.dumps(manifest.model_dump(mode="json"))


def _make_zip_bytes(path: str, content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(path, content)
    return buffer.getvalue()


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


def _patch_run_and_job(monkeypatch, *, artifacts_json, output_json=None):
    monkeypatch.setattr(
        "api.app.generated_tests.get_run",
        lambda session, run_id, workspace_id=None: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
        )
        if workspace_id == "workspace-1"
        else None,
    )
    monkeypatch.setattr(
        "api.app.generated_tests.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(
            run_id=run_id,
            stage=stage,
            status="succeeded",
            artifacts_json=artifacts_json,
            output_json=output_json or {},
        ),
    )


def test_generated_tests_manifest_endpoint_returns_expected_payload(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(
        monkeypatch,
        artifacts_json=[
            {
                "artifact_type": "generated_tests_manifest",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/generated_tests/test_index.json",
            }
        ],
    )
    monkeypatch.setattr(
        "api.app.generated_tests.download_storage_object_text",
        lambda bucket, key: _build_manifest_payload(),
    )

    response = client.get("/runs/run-1/generated-tests/manifest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-1"
    assert len(payload["files"]) == 3
    assert payload["files"][0]["generated_test_file"] == "generated_tests/services/test_parse_config_a1b2c3.py"


def test_generated_tests_tree_endpoint_builds_flat_nodes(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(
        monkeypatch,
        artifacts_json=[
            {
                "artifact_type": "generated_tests_manifest",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/generated_tests/test_index.json",
            }
        ],
    )
    monkeypatch.setattr(
        "api.app.generated_tests.download_storage_object_text",
        lambda bucket, key: _build_manifest_payload(),
    )

    response = client.get("/runs/run-1/generated-tests/tree")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-1"
    assert payload["root"] == "generated_tests"
    assert {"path": "generated_tests", "name": "generated_tests", "type": "directory"} in payload["nodes"]
    assert {"path": "generated_tests/services", "name": "services", "type": "directory"} in payload["nodes"]
    assert {
        "path": "generated_tests/services/test_parse_config_a1b2c3.py",
        "name": "test_parse_config_a1b2c3.py",
        "type": "file",
        "target_key": "abc123",
        "target_type": "SERVICE_FUNCTION",
        "test_kind": "unit",
        "symbol": "parse_config",
    } in payload["nodes"]


def test_generated_test_file_endpoint_returns_exact_content(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(
        monkeypatch,
        artifacts_json=[
            {
                "artifact_type": "generated_tests_manifest",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/generated_tests/test_index.json",
            },
            {
                "artifact_type": "generated_test_file",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/generated_tests/services/test_parse_config_a1b2c3.py",
                "path": "generated_tests/services/test_parse_config_a1b2c3.py",
            },
        ],
    )

    def fake_download_text(bucket: str, key: str) -> str:
        if key.endswith("test_index.json"):
            return _build_manifest_payload()
        if key.endswith("test_parse_config_a1b2c3.py"):
            return "def test_parse_config():\n    assert True\n"
        raise AssertionError(key)

    monkeypatch.setattr("api.app.generated_tests.download_storage_object_text", fake_download_text)

    response = client.get(
        "/runs/run-1/generated-tests/file",
        params={"path": "generated_tests/services/test_parse_config_a1b2c3.py"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "path": "generated_tests/services/test_parse_config_a1b2c3.py",
        "language": "python",
        "content": "def test_parse_config():\n    assert True\n",
    }


def test_generated_test_file_endpoint_rejects_invalid_path(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(monkeypatch, artifacts_json=[])
    monkeypatch.setattr("api.app.generated_tests.download_storage_object_text", lambda bucket, key: _build_manifest_payload())

    response = client.get("/runs/run-1/generated-tests/file", params={"path": "../secrets.txt"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid generated test path"


def test_generated_tests_endpoints_block_when_workspace_is_missing(monkeypatch) -> None:
    app.dependency_overrides[get_session] = lambda: DummySession()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id="user-1", email="user@example.com")
    monkeypatch.setattr("api.app.main.get_workspace_for_user", lambda session, user_id: None)
    client = TestClient(app)

    response = client.get("/runs/run-1/generated-tests/manifest")

    assert response.status_code == 403
    assert response.json()["detail"] == "Workspace not found for user"


def test_generated_tests_manifest_returns_404_when_artifact_missing(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(monkeypatch, artifacts_json=[])
    monkeypatch.setattr(
        "api.app.generated_tests.download_storage_object_text",
        lambda bucket, key: (_ for _ in ()).throw(FileNotFoundError(key)),
    )

    response = client.get("/runs/run-1/generated-tests/manifest")

    assert response.status_code == 404
    assert response.json()["detail"] == "Generated tests manifest not found"


def test_generated_tests_file_endpoint_falls_back_to_known_paths_and_zip(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(
        monkeypatch,
        artifacts_json=[],
        output_json={"artifact_paths": ["generated_tests.zip"]},
    )

    def fake_download_text(bucket: str, key: str) -> str:
        assert key == "workspace-1/project-1/run-1/generated_tests/test_index.json"
        return _build_manifest_payload()

    monkeypatch.setattr("api.app.generated_tests.download_storage_object_text", fake_download_text)
    monkeypatch.setattr(
        "api.app.generated_tests.download_storage_object_bytes",
        lambda bucket, key: _make_zip_bytes(
            "generated_tests/services/test_parse_config_a1b2c3.py",
            "def test_zip_fallback():\n    assert True\n",
        ),
    )

    response = client.get(
        "/runs/run-1/generated-tests/file",
        params={"path": "generated_tests/services/test_parse_config_a1b2c3.py"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "def test_zip_fallback():\n    assert True\n"


def test_generated_test_cases_endpoint_returns_all_cases_from_execution_junit(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(
        monkeypatch,
        artifacts_json=[
            {
                "artifact_type": "generated_tests_manifest",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/generated_tests/test_index.json",
            }
        ],
    )

    def fake_get_job_by_stage(session, run_id, stage):
        if stage == "generate_tests":
            return SimpleNamespace(
                run_id=run_id,
                stage=stage,
                status="succeeded",
                artifacts_json=[
                    {
                        "artifact_type": "generated_tests_manifest",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/generated_tests/test_index.json",
                    }
                ],
                output_json={},
            )
        if stage == "execute_tests":
            return SimpleNamespace(
                run_id=run_id,
                stage=stage,
                status="succeeded",
                artifacts_json=[
                    {
                        "artifact_type": "execution_junit",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/execute_tests/junit/generated-tests.xml",
                        "path": "execute_tests/junit/generated-tests.xml",
                    }
                ],
                output_json={},
            )
        return None

    monkeypatch.setattr("api.app.generated_tests.get_job_by_stage", fake_get_job_by_stage)

    generated_junit = """
<testsuite tests="3" failures="1" errors="0" skipped="1">
  <testcase classname="test_parse_config_a1b2c3" name="test_allows_safe_input" file="generated_tests/services/test_parse_config_a1b2c3.py" time="0.2" />
  <testcase classname="test_parse_config_a1b2c3" name="test_blocks_traversal" file="generated_tests/services/test_parse_config_a1b2c3.py" time="0.3">
    <failure message="IndexError: index out of range">traceback</failure>
  </testcase>
  <testcase classname="test_get_user_f9e8d7" name="test_windows_variant" file="generated_tests/api/test_get_user_f9e8d7.py" time="0.1">
    <skipped message="windows only" />
  </testcase>
</testsuite>
""".strip()

    def fake_download_text(bucket: str, key: str) -> str:
        if key.endswith("test_index.json"):
            return _build_manifest_payload()
        if key.endswith("generated-tests.xml"):
            return generated_junit
        raise AssertionError(key)

    monkeypatch.setattr("api.app.generated_tests.download_storage_object_text", fake_download_text)

    response = client.get("/runs/run-1/generated-tests/cases")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "execution_junit"
    assert [case["name"] for case in payload["cases"]] == [
        "test_allows_safe_input",
        "test_blocks_traversal",
        "test_windows_variant",
    ]
    assert [case["status"] for case in payload["cases"]] == ["passed", "failed", "skipped"]


def test_generated_test_cases_endpoint_falls_back_to_parsing_generated_files(monkeypatch) -> None:
    client = _authorized_client(monkeypatch)
    _patch_run_and_job(
        monkeypatch,
        artifacts_json=[
            {
                "artifact_type": "generated_tests_manifest",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/generated_tests/test_index.json",
            },
            {
                "artifact_type": "generated_test_file",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/generated_tests/services/test_parse_config_a1b2c3.py",
                "path": "generated_tests/services/test_parse_config_a1b2c3.py",
            },
            {
                "artifact_type": "generated_test_file",
                "bucket": "runs",
                "key": "workspace-1/project-1/run-1/generated_tests/api/test_get_user_f9e8d7.py",
                "path": "generated_tests/api/test_get_user_f9e8d7.py",
            },
        ],
    )

    def fake_get_job_by_stage(session, run_id, stage):
        if stage == "generate_tests":
            return SimpleNamespace(
                run_id=run_id,
                stage=stage,
                status="succeeded",
                artifacts_json=[
                    {
                        "artifact_type": "generated_tests_manifest",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/generated_tests/test_index.json",
                    },
                    {
                        "artifact_type": "generated_test_file",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/generated_tests/services/test_parse_config_a1b2c3.py",
                        "path": "generated_tests/services/test_parse_config_a1b2c3.py",
                    },
                    {
                        "artifact_type": "generated_test_file",
                        "bucket": "runs",
                        "key": "workspace-1/project-1/run-1/generated_tests/api/test_get_user_f9e8d7.py",
                        "path": "generated_tests/api/test_get_user_f9e8d7.py",
                    },
                ],
                output_json={},
            )
        if stage == "execute_tests":
            return None
        return None

    monkeypatch.setattr("api.app.generated_tests.get_job_by_stage", fake_get_job_by_stage)

    def fake_download_text(bucket: str, key: str) -> str:
        if key.endswith("test_index.json"):
            return _build_manifest_payload()
        if key.endswith("test_parse_config_a1b2c3.py"):
            return "def test_alpha():\n    assert True\n\ndef helper():\n    return None\n\ndef test_beta():\n    assert True\n"
        if key.endswith("test_get_user_f9e8d7.py"):
            return "async def test_gamma():\n    assert True\n"
        raise AssertionError(key)

    monkeypatch.setattr("api.app.generated_tests.download_storage_object_text", fake_download_text)

    response = client.get("/runs/run-1/generated-tests/cases")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "generated_files"
    assert [case["name"] for case in payload["cases"]] == ["test_alpha", "test_beta", "test_gamma"]
    assert all(case["status"] == "not_run" for case in payload["cases"])


def teardown_function() -> None:
    app.dependency_overrides.clear()
