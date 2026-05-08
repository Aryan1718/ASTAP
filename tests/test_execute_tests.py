import json
import tarfile
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.config import Settings
from shared.targets import (
    GeneratedTestManifestEntry,
    GeneratedTestStatus,
    build_generated_test_manifest,
)
from worker.app.jobs.execute_tests import (
    ExecutorClient,
    _executor_request_timeout_seconds,
    build_executor_request,
    detect_execution_plan,
    execute_tests_job,
)


def write_repo_fixture(repo_path: Path) -> None:
    app_dir = repo_path / "app"
    tests_dir = repo_path / "tests"
    app_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "main.py").write_text(
        """
def parse_config(path: str) -> dict:
    if not path:
        raise ValueError("path is required")
    return {"path": path}
""".strip(),
        encoding="utf-8",
    )
    (tests_dir / "test_existing.py").write_text(
        """
from app.main import parse_config


def test_existing_parse_config():
    assert parse_config("cfg") == {"path": "cfg"}
""".strip(),
        encoding="utf-8",
    )


def create_snapshot(repo_path: Path, snapshot_path: Path) -> None:
    with tarfile.open(snapshot_path, "w:gz") as archive:
        for path in repo_path.rglob("*"):
            archive.add(path, arcname=path.relative_to(repo_path))


def test_execute_tests_job_runs_existing_and_generated_suites_and_uploads_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "repo"
    write_repo_fixture(repo_path)
    snapshot_path = tmp_path / "snapshot.tar.gz"
    create_snapshot(repo_path, snapshot_path)

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
    generated_test_content = """
from app.main import parse_config


def test_generated_path_traversal_signal():
    assert parse_config("../etc/passwd") == {"path": "safe"}
""".strip() + "\n"

    uploads: dict[str, str] = {}
    marks: dict[str, object] = {}
    enqueued: dict[str, object] = {}

    class FakeSession:
        def close(self) -> None:
            return None

    executor_requests: list[dict] = []

    class FakeExecutorClient:
        def __init__(self, *, base_url: str) -> None:
            self.base_url = base_url

        def execute(self, payload: dict):
            executor_requests.append(payload)
            workspace_dir = Path(payload["workspace_path"])

            existing_junit = workspace_dir / "out" / "execute_tests" / "junit" / "existing-tests.xml"
            generated_junit = workspace_dir / "out" / "execute_tests" / "junit" / "generated-tests.xml"
            existing_junit.parent.mkdir(parents=True, exist_ok=True)
            generated_junit.parent.mkdir(parents=True, exist_ok=True)
            if len(executor_requests) == 1:
                existing_junit.write_text(
                    '<testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0"></testsuite>',
                    encoding="utf-8",
                )
                return SimpleNamespace(
                    python_version="Python 3.12.9",
                    platform_system="Linux",
                    isolation={
                        "network_mode": "bridge",
                        "read_only_rootfs": True,
                        "repo_mount_read_only": False,
                        "cap_drop_all": True,
                        "no_new_privileges": True,
                        "cpus": 1.0,
                        "memory_mb": 1024,
                        "pids": 256,
                        "tmpfs_mb": 128,
                        "worker_has_docker_socket": False,
                    },
                    steps={
                        "bootstrap": [
                            {
                                "command": ["python", "-m", "venv", "/workspace/out/venv"],
                                "exit_code": 0,
                                "stdout": "",
                                "stderr": "",
                                "duration_seconds": 0.1,
                            }
                        ],
                        "install": [],
                        "existing_suite": {
                            "command": [
                                "python",
                                "-m",
                                "pytest",
                                "tests",
                                "--ignore=.astap/generated_tests",
                                "--junitxml=/workspace/out/execute_tests/junit/existing-tests.xml",
                            ],
                            "exit_code": 0,
                            "stdout": "1 passed\n",
                            "stderr": "",
                            "duration_seconds": 1.25,
                        },
                        "generated_collect": {
                            "command": [
                                "python",
                                "-m",
                                "pytest",
                                ".astap/generated_tests",
                                "--collect-only",
                                "--continue-on-collection-errors",
                                "-q",
                            ],
                            "exit_code": 0,
                            "stdout": ".astap/generated_tests/security/test_parse_config_path_traversal_abc123.py::test_generated_path_traversal_signal\n1 test collected\n",
                            "stderr": "",
                            "duration_seconds": 0.2,
                        },
                        "generated_suite": None,
                    },
                    error=None,
                )

            generated_junit.write_text(
                '<testsuite name="pytest" tests="1" failures="1" errors="0" skipped="0"><testcase classname="test_parse_config_path_traversal_abc123" name="test_generated_path_traversal_signal" file=".astap/generated_tests/security/test_parse_config_path_traversal_abc123.py" time="0.75"><failure message="AssertionError">AssertionError</failure></testcase></testsuite>',
                encoding="utf-8",
            )
            return SimpleNamespace(
                python_version="Python 3.12.9",
                platform_system="Linux",
                isolation={
                    "network_mode": "bridge",
                    "read_only_rootfs": True,
                    "repo_mount_read_only": False,
                    "cap_drop_all": True,
                    "no_new_privileges": True,
                    "cpus": 1.0,
                    "memory_mb": 1024,
                    "pids": 256,
                    "tmpfs_mb": 128,
                    "worker_has_docker_socket": False,
                },
                steps={
                    "bootstrap": [],
                    "install": [],
                    "existing_suite": None,
                    "generated_collect": None,
                    "generated_suite": {
                        "command": [
                            "python",
                            "-m",
                            "pytest",
                            ".astap/generated_tests/security/test_parse_config_path_traversal_abc123.py",
                            "--junitxml=/workspace/out/execute_tests/junit/generated-tests.xml",
                        ],
                        "exit_code": 1,
                        "stdout": "1 failed\n",
                        "stderr": "AssertionError\n",
                        "duration_seconds": 0.75,
                    },
                },
                error=None,
            )

    monkeypatch.setattr("worker.app.jobs.execute_tests.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.execute_tests.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            snapshot_bucket="runs",
            snapshot_key="workspace-1/project-1/run-1/snapshot/snapshot.tar.gz",
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(
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
                    "key": "workspace-1/project-1/run-1/generated_tests/security/test_parse_config_path_traversal_abc123.py",
                    "path": "generated_tests/security/test_parse_config_path_traversal_abc123.py",
                },
            ],
            output_json={},
        )
        if stage == "generate_tests"
        else SimpleNamespace(id="analyze-job-1")
        if stage == "analyze"
        else None,
    )
    monkeypatch.setattr("worker.app.jobs.execute_tests.mark_run_running", lambda session, run_id: None)
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.download_storage_object",
        lambda bucket, object_key, destination: destination.write_bytes(snapshot_path.read_bytes()),
    )

    def fake_download_text(bucket: str, object_key: str) -> str:
        if object_key.endswith("test_index.json"):
            return json.dumps(manifest.model_dump(mode="json"))
        if object_key.endswith(".py"):
            return generated_test_content
        raise AssertionError(object_key)

    monkeypatch.setattr("worker.app.jobs.execute_tests.download_storage_object_text", fake_download_text)
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.mark_job_succeeded_with_artifacts",
        lambda session, job_id, output_json, artifacts_json: marks.update(
            {"job_id": job_id, "output_json": output_json, "artifacts_json": artifacts_json}
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.get_queue",
        lambda name: SimpleNamespace(enqueue=lambda fn, run_id, job_id: SimpleNamespace(id=f"rq-{name}")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.set_job_rq_id",
        lambda session, job_id, rq_job_id: enqueued.update({"job_id": job_id, "rq_job_id": rq_job_id}),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            EXECUTE_TESTS_IMAGE="astsp-executor:latest",
            EXECUTE_TESTS_SHARED_WORKSPACE_ROOT=str(tmp_path / "shared"),
            EXECUTOR_BASE_URL="http://executor:8080",
        ),
    )
    monkeypatch.setattr("worker.app.jobs.execute_tests.ExecutorClient", FakeExecutorClient)

    execute_tests_job("run-1", "job-1")

    results_key = "workspace-1/project-1/run-1/execute_tests/results.json"
    existing_log_key = "workspace-1/project-1/run-1/execute_tests/logs/existing-tests.log"
    generated_log_key = "workspace-1/project-1/run-1/execute_tests/logs/generated-tests.log"
    existing_junit_key = "workspace-1/project-1/run-1/execute_tests/junit/existing-tests.xml"
    generated_junit_key = "workspace-1/project-1/run-1/execute_tests/junit/generated-tests.xml"

    assert results_key in uploads
    assert existing_log_key in uploads
    assert generated_log_key in uploads
    assert existing_junit_key in uploads
    assert generated_junit_key in uploads

    results_payload = json.loads(uploads[results_key])
    assert results_payload["overall_result"] == "completed_with_failures"
    assert results_payload["execution_plan"]["framework"] == "pytest"
    assert results_payload["execution_plan"]["existing_test_command"]["source"] == "repo_detection.pytest"
    assert results_payload["attempted_commands"][0] == ["python", "-m", "pytest", "tests", "--ignore=.astap/generated_tests"]
    assert results_payload["environment"]["execution_mode"] == "bounded_container"
    assert results_payload["environment"]["platform_system"] == "Linux"
    assert results_payload["environment"]["worker_has_docker_socket"] is False
    assert results_payload["isolation"]["network_mode"] == "bridge"
    assert results_payload["install"]["offline"] is False
    assert results_payload["existing_tests"]["status"] == "passed"
    assert results_payload["existing_tests"]["command_source"] == "repo_detection.pytest"
    assert results_payload["existing_tests"]["passed"] == 1
    assert results_payload["generated_tests"]["status"] == "failed"
    assert results_payload["generated_tests"]["command_source"] == "platform_default.generated_pytest"
    assert results_payload["generated_tests"]["failed"] == 1
    assert results_payload["generated_tests"]["quality_status"] == "runnable"
    assert results_payload["generated_tests"]["files_generated"] == 1
    assert results_payload["generated_tests"]["files_collected"] == 1
    assert results_payload["generated_tests"]["files_executed"] == 1
    assert executor_requests[0]["workspace_path"].startswith(str(tmp_path / "shared"))
    assert executor_requests[0]["commands"]["generated_collect"][-3:] == ["--collect-only", "--continue-on-collection-errors", "-q"]
    assert executor_requests[0]["commands"]["generated_suite"] is None
    assert executor_requests[1]["commands"]["generated_suite"][3] == ".astap/generated_tests/security/test_parse_config_path_traversal_abc123.py"

    assert marks["output_json"]["overall_result"] == "completed_with_failures"
    assert marks["output_json"]["existing_tests"]["status"] == "passed"
    assert marks["output_json"]["generated_tests"]["status"] == "failed"
    assert marks["output_json"]["execution_plan"]["suite_timeout_seconds"] == 600
    assert marks["output_json"]["isolation"]["repo_mount_read_only"] is False
    assert enqueued == {"job_id": "analyze-job-1", "rq_job_id": "rq-analyze"}


def test_execute_tests_job_repairs_collection_failures_once_and_runs_repaired_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "repo"
    write_repo_fixture(repo_path)
    snapshot_path = tmp_path / "snapshot.tar.gz"
    create_snapshot(repo_path, snapshot_path)

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
            )
        ],
    )
    broken_generated_test = (
        "from app.missing import parse_config\n\n"
        "def test_generated_parse_config():\n"
        "    assert parse_config('cfg') == {'path': 'cfg'}\n"
    )
    repaired_generated_test = (
        "from app.main import parse_config\n\n"
        "def test_generated_parse_config():\n"
        "    assert parse_config('cfg') == {'path': 'cfg'}\n"
    )

    uploads: dict[str, str] = {}
    marks: dict[str, object] = {}
    enqueued: dict[str, object] = {}
    executor_requests: list[dict] = []

    class FakeSession:
        def close(self) -> None:
            return None

    class FakeProvider:
        def __init__(self, api_key: str, config) -> None:
            self.api_key = api_key
            self.config = config

        def repair_collection_failure(self, **kwargs) -> str:
            assert "ModuleNotFoundError" in kwargs["error_message"]
            return repaired_generated_test

    class FakeExecutorClient:
        def __init__(self, *, base_url: str) -> None:
            self.base_url = base_url

        def execute(self, payload: dict):
            executor_requests.append(payload)
            workspace_dir = Path(payload["workspace_path"])
            existing_junit = workspace_dir / "out" / "execute_tests" / "junit" / "existing-tests.xml"
            generated_junit = workspace_dir / "out" / "execute_tests" / "junit" / "generated-tests.xml"
            existing_junit.parent.mkdir(parents=True, exist_ok=True)
            generated_junit.parent.mkdir(parents=True, exist_ok=True)

            if len(executor_requests) == 1:
                existing_junit.write_text(
                    '<testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0"></testsuite>',
                    encoding="utf-8",
                )
                return SimpleNamespace(
                    python_version="Python 3.12.9",
                    platform_system="Linux",
                    isolation={"network_mode": "bridge", "worker_has_docker_socket": False},
                    steps={
                        "bootstrap": [],
                        "install": [],
                        "existing_suite": {
                            "command": ["python", "-m", "pytest", "tests", "--ignore=.astap/generated_tests"],
                            "exit_code": 0,
                            "stdout": "1 passed\n",
                            "stderr": "",
                            "duration_seconds": 0.3,
                        },
                        "generated_collect": {
                            "command": [
                                "python",
                                "-m",
                                "pytest",
                                ".astap/generated_tests",
                                "--collect-only",
                                "--continue-on-collection-errors",
                                "-q",
                            ],
                            "exit_code": 1,
                            "stdout": "",
                            "stderr": "ModuleNotFoundError: No module named 'app.missing'\n",
                            "duration_seconds": 0.2,
                        },
                        "generated_suite": None,
                    },
                    error=None,
                )

            if len(executor_requests) == 2:
                return SimpleNamespace(
                    python_version="Python 3.12.9",
                    platform_system="Linux",
                    isolation={"network_mode": "bridge", "worker_has_docker_socket": False},
                    steps={
                        "bootstrap": [],
                        "install": [],
                        "existing_suite": None,
                        "generated_collect": {
                            "command": [
                                "python",
                                "-m",
                                "pytest",
                                ".astap/generated_tests/services/test_parse_config_abc123.py",
                                "--collect-only",
                                "--continue-on-collection-errors",
                                "-q",
                            ],
                            "exit_code": 0,
                            "stdout": ".astap/generated_tests/services/test_parse_config_abc123.py::test_generated_parse_config\n1 test collected\n",
                            "stderr": "",
                            "duration_seconds": 0.1,
                        },
                        "generated_suite": None,
                    },
                    error=None,
                )

            generated_junit.write_text(
                '<testsuite name="pytest" tests="1" failures="0" errors="0" skipped="0"><testcase classname="test_parse_config_abc123" name="test_generated_parse_config" file=".astap/generated_tests/services/test_parse_config_abc123.py" time="0.2" /></testsuite>',
                encoding="utf-8",
            )
            return SimpleNamespace(
                python_version="Python 3.12.9",
                platform_system="Linux",
                isolation={"network_mode": "bridge", "worker_has_docker_socket": False},
                steps={
                    "bootstrap": [],
                    "install": [],
                    "existing_suite": None,
                    "generated_collect": None,
                    "generated_suite": {
                        "command": [
                            "python",
                            "-m",
                            "pytest",
                            ".astap/generated_tests/services/test_parse_config_abc123.py",
                            "--junitxml=/workspace/out/execute_tests/junit/generated-tests.xml",
                        ],
                        "exit_code": 0,
                        "stdout": "1 passed\n",
                        "stderr": "",
                        "duration_seconds": 0.2,
                    },
                },
                error=None,
            )

    monkeypatch.setattr("worker.app.jobs.execute_tests.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.execute_tests.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            snapshot_bucket="runs",
            snapshot_key="workspace-1/project-1/run-1/snapshot/snapshot.tar.gz",
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(
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
                    "key": "workspace-1/project-1/run-1/generated_tests/services/test_parse_config_abc123.py",
                    "path": "generated_tests/services/test_parse_config_abc123.py",
                },
            ],
            output_json={},
        )
        if stage == "generate_tests"
        else SimpleNamespace(id="analyze-job-1")
        if stage == "analyze"
        else None,
    )
    monkeypatch.setattr("worker.app.jobs.execute_tests.mark_run_running", lambda session, run_id: None)
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.download_storage_object",
        lambda bucket, object_key, destination: destination.write_bytes(snapshot_path.read_bytes()),
    )

    def fake_download_text(bucket: str, object_key: str) -> str:
        if object_key.endswith("test_index.json"):
            return json.dumps(manifest.model_dump(mode="json"))
        if object_key.endswith(".py"):
            return broken_generated_test
        raise AssertionError(object_key)

    monkeypatch.setattr("worker.app.jobs.execute_tests.download_storage_object_text", fake_download_text)
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.mark_job_succeeded_with_artifacts",
        lambda session, job_id, output_json, artifacts_json: marks.update(
            {"job_id": job_id, "output_json": output_json, "artifacts_json": artifacts_json}
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.get_queue",
        lambda name: SimpleNamespace(enqueue=lambda fn, run_id, job_id: SimpleNamespace(id=f"rq-{name}")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.set_job_rq_id",
        lambda session, job_id, rq_job_id: enqueued.update({"job_id": job_id, "rq_job_id": rq_job_id}),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            OPENAI_API_KEY="test-key",
            EXECUTE_TESTS_IMAGE="astsp-executor:latest",
            EXECUTE_TESTS_SHARED_WORKSPACE_ROOT=str(tmp_path / "shared"),
            EXECUTOR_BASE_URL="http://executor:8080",
        ),
    )
    monkeypatch.setattr("worker.app.jobs.execute_tests.ExecutorClient", FakeExecutorClient)
    monkeypatch.setattr("worker.app.jobs.execute_tests.OpenAIGenerateTestsProvider", FakeProvider)

    execute_tests_job("run-1", "job-1")

    results_payload = json.loads(uploads["workspace-1/project-1/run-1/execute_tests/results.json"])
    generated_suite = results_payload["generated_tests"]
    assert results_payload["overall_result"] == "completed_successfully"
    assert generated_suite["status"] == "passed"
    assert generated_suite["quality_status"] == "runnable"
    assert generated_suite["repair_passes_run"] == 1
    assert generated_suite["files_repaired"] == 1
    assert generated_suite["files_repaired_and_collected"] == 1
    assert generated_suite["repair_log_path"] == "execute_tests/logs/generated-repair.log"
    assert generated_suite["collect_log_path"] == "execute_tests/logs/generated-collect-repair.log"
    assert generated_suite["file_results"][0]["attempt_count"] == 2
    assert generated_suite["file_results"][0]["final_attempt"] == 2
    assert generated_suite["file_results"][0]["repair_status"] == "repaired"
    assert generated_suite["file_results"][0]["status"] == "passed"
    assert generated_suite["file_results"][0]["initial_attempt_artifact_path"].endswith("attempt_1/services/test_parse_config_abc123.py")
    assert generated_suite["file_results"][0]["final_attempt_artifact_path"].endswith("attempt_2/services/test_parse_config_abc123.py")
    assert len(executor_requests) == 3
    assert executor_requests[1]["commands"]["generated_collect"][3] == ".astap/generated_tests/services/test_parse_config_abc123.py"
    assert executor_requests[2]["commands"]["generated_suite"][3] == ".astap/generated_tests/services/test_parse_config_abc123.py"
    assert "workspace-1/project-1/run-1/execute_tests/generated_test_attempts/attempt_1/services/test_parse_config_abc123.py" in uploads
    assert "workspace-1/project-1/run-1/execute_tests/generated_test_attempts/attempt_2/services/test_parse_config_abc123.py" in uploads
    assert enqueued == {"job_id": "analyze-job-1", "rq_job_id": "rq-analyze"}


def test_detect_execution_plan_prefers_pyproject_test_extra_and_testpaths(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "pyproject.toml").write_text(
        """
[project]
name = "sample-project"
version = "0.1.0"

[project.optional-dependencies]
test = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["unit_tests", "integration_tests"]
""".strip(),
        encoding="utf-8",
    )

    config = Settings(
        DATABASE_URL="sqlite:///tmp.db",
        REDIS_URL="redis://localhost:6379/0",
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY="service-role-key",
        SUPABASE_STORAGE_BUCKET="runs",
    ).execute_tests_config()

    plan = detect_execution_plan(repo_path=repo_path, run_config={}, config=config)

    assert plan.install_commands[0].command == ["python", "-m", "pip", "install", ".[test]"]
    assert plan.install_commands[0].source == "repo.pyproject_toml"
    assert plan.existing_test_command.command[:5] == ["python", "-m", "pytest", "unit_tests", "integration_tests"]
    assert plan.existing_test_command.command[-1] == "--ignore=.astap/generated_tests"
    assert "Detected pyproject.toml for package installation" in plan.detection_notes


def test_detect_execution_plan_applies_run_config_overrides(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "requirements.txt").write_text("pytest==8.3.0\n", encoding="utf-8")

    config = Settings(
        DATABASE_URL="sqlite:///tmp.db",
        REDIS_URL="redis://localhost:6379/0",
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY="service-role-key",
        SUPABASE_STORAGE_BUCKET="runs",
    ).execute_tests_config()

    plan = detect_execution_plan(
        repo_path=repo_path,
        run_config={
            "execute_tests": {
                "install_commands": [
                    "python -m pip install -r requirements.txt",
                    ["python", "-m", "pip", "install", "-e", "."],
                ],
                "existing_test_command": "python -m pytest tests/unit -q",
                "generated_test_command": ["python", "-m", "pytest", ".astap/generated_tests", "-q"],
                "suite_timeout_seconds": 42,
            }
        },
        config=config,
    )

    assert [selection.command for selection in plan.install_commands] == [
        ["python", "-m", "pip", "install", "-r", "requirements.txt"],
        ["python", "-m", "pip", "install", "-e", "."],
    ]
    assert all(selection.source == "run_config.install_commands" for selection in plan.install_commands)
    assert plan.existing_test_command.command == ["python", "-m", "pytest", "tests/unit", "-q"]
    assert plan.existing_test_command.source == "run_config.existing_test_command"
    assert plan.generated_collect_command.command[-3:] == ["--collect-only", "--continue-on-collection-errors", "-q"]
    assert plan.generated_test_command.command == ["python", "-m", "pytest", ".astap/generated_tests", "-q"]
    assert plan.generated_test_command.source == "run_config.generated_test_command"
    assert plan.suite_timeout_seconds == 42


def test_build_executor_request_uses_bounded_workspace_mounts(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "shared" / "run-1"
    workspace_dir.mkdir(parents=True)
    run = SimpleNamespace(id="run-1", workspace_id="workspace-1")
    config = Settings(
        DATABASE_URL="sqlite:///tmp.db",
        REDIS_URL="redis://localhost:6379/0",
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY="service-role-key",
        SUPABASE_STORAGE_BUCKET="runs",
        EXECUTE_TESTS_SHARED_WORKSPACE_ROOT=str(tmp_path / "shared"),
        EXECUTE_TESTS_HOST_WORKSPACE_ROOT=str(tmp_path / "host-shared"),
    ).execute_tests_config()
    plan = detect_execution_plan(repo_path=tmp_path, run_config={}, config=config)

    payload = build_executor_request(
        run=run,
        config=config,
        workspace_dir=workspace_dir,
        execution_plan=plan,
        include_environment_setup=True,
        include_generated_collect=True,
        generated_collect_targets=None,
        generated_suite_targets=[".astap/generated_tests/services/test_example.py"],
    )

    assert payload["workspace_path"] == str(workspace_dir.resolve())
    assert payload["limits"] == {"cpus": 1.0, "memory_mb": 1024, "pids": 256, "tmpfs_mb": 128}
    assert payload["commands"]["bootstrap"] == [["python", "-m", "venv", "/workspace/out/venv"]]
    assert payload["commands"]["generated_collect"][-3:] == ["--collect-only", "--continue-on-collection-errors", "-q"]
    assert payload["commands"]["existing_suite"][-1] == "--junitxml=/workspace/out/execute_tests/junit/existing-tests.xml"
    assert payload["commands"]["generated_suite"][3] == ".astap/generated_tests/services/test_example.py"
    assert payload["commands"]["generated_suite"][-1] == "--junitxml=/workspace/out/execute_tests/junit/generated-tests.xml"


def test_execute_tests_job_marks_stage_failed_and_uploads_results_on_environment_setup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "repo"
    write_repo_fixture(repo_path)
    snapshot_path = tmp_path / "snapshot.tar.gz"
    create_snapshot(repo_path, snapshot_path)
    manifest = build_generated_test_manifest("run-1", [])

    uploads: dict[str, str] = {}
    failures: dict[str, object] = {}
    enqueued: dict[str, object] = {}

    class FakeSession:
        def close(self) -> None:
            return None

    class FakeExecutorClient:
        def __init__(self, *, base_url: str) -> None:
            self.base_url = base_url

        def execute(self, payload: dict):
            return SimpleNamespace(
                python_version="Python 3.12.9",
                isolation={"network_mode": "bridge", "worker_has_docker_socket": False},
                steps={
                    "bootstrap": [],
                    "install": [
                        {
                            "command": ["/workspace/out/venv/bin/python", "-m", "pip", "install", "-r", "requirements.txt"],
                            "exit_code": 1,
                            "stdout": "",
                            "stderr": "Temporary failure in name resolution",
                            "duration_seconds": 0.4,
                        }
                    ],
                    "existing_suite": None,
                    "generated_collect": None,
                    "generated_suite": None,
                },
                error={
                    "type": "environment_setup_failed",
                    "message": "Dependency install failed: /workspace/out/venv/bin/python -m pip install -r requirements.txt",
                },
            )

    monkeypatch.setattr("worker.app.jobs.execute_tests.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.execute_tests.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            snapshot_bucket="runs",
            snapshot_key="workspace-1/project-1/run-1/snapshot/snapshot.tar.gz",
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(
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
        if stage == "generate_tests"
        else SimpleNamespace(id="analyze-job-1")
        if stage == "analyze"
        else None,
    )
    monkeypatch.setattr("worker.app.jobs.execute_tests.mark_run_running", lambda session, run_id: None)
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.download_storage_object",
        lambda bucket, object_key, destination: destination.write_bytes(snapshot_path.read_bytes()),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.download_storage_object_text",
        lambda bucket, object_key: json.dumps(manifest.model_dump(mode="json")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.mark_job_failed",
        lambda session, job_id, error_message, output_json=None, artifacts_json=None: failures.update(
            {
                "job_id": job_id,
                "error_message": error_message,
                "output_json": output_json,
                "artifacts_json": artifacts_json,
            }
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.get_queue",
        lambda name: SimpleNamespace(enqueue=lambda fn, run_id, job_id: SimpleNamespace(id=f"rq-{name}")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.set_job_rq_id",
        lambda session, job_id, rq_job_id: enqueued.update({"job_id": job_id, "rq_job_id": rq_job_id}),
    )
    monkeypatch.setattr(
        "worker.app.jobs.execute_tests.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            EXECUTE_TESTS_IMAGE="astsp-executor:latest",
            EXECUTE_TESTS_SHARED_WORKSPACE_ROOT=str(tmp_path / "shared"),
            EXECUTOR_BASE_URL="http://executor:8080",
        ),
    )
    monkeypatch.setattr("worker.app.jobs.execute_tests.ExecutorClient", FakeExecutorClient)

    execute_tests_job("run-1", "job-1")

    results_payload = json.loads(uploads["workspace-1/project-1/run-1/execute_tests/results.json"])
    assert results_payload["overall_result"] == "environment_setup_failed"
    assert results_payload["error"]["type"] == "environment_setup_failed"
    assert results_payload["existing_tests"]["status"] == "error"
    assert results_payload["generated_tests"]["status"] == "skipped"
    assert "execute_tests/logs/environment-setup.log" in failures["output_json"]["artifacts"].values()
    assert failures["error_message"].startswith("environment_setup_failed:")
    assert enqueued == {"job_id": "analyze-job-1", "rq_job_id": "rq-analyze"}


def test_executor_request_timeout_scales_with_step_budgets() -> None:
    payload = {
        "install_timeout_seconds": 300,
        "suite_timeout_seconds": 600,
        "commands": {
            "bootstrap": [["python", "-m", "venv", "/workspace/out/venv"]],
            "install": [["python", "-m", "pip", "install", "-r", "requirements.txt"]],
            "existing_suite": ["python", "-m", "pytest", "tests"],
            "generated_collect": ["python", "-m", "pytest", ".astap/generated_tests", "--collect-only"],
            "generated_suite": ["python", "-m", "pytest", ".astap/generated_tests"],
        },
    }

    assert _executor_request_timeout_seconds(payload) == 2430


def test_executor_client_uses_computed_request_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "python_version": "Python 3.12.9",
                    "platform_system": "Linux",
                    "isolation": {"network_mode": "bridge"},
                    "steps": {"install": []},
                    "error": None,
                }
            ).encode("utf-8")

    def fake_urlopen(request: urllib.request.Request, timeout: float):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("worker.app.jobs.execute_tests.urllib.request.urlopen", fake_urlopen)

    payload = {
        "install_timeout_seconds": 300,
        "suite_timeout_seconds": 600,
        "commands": {
            "bootstrap": [["python", "-m", "venv", "/workspace/out/venv"]],
            "install": [["python", "-m", "pip", "install", "-r", "requirements.txt"]],
            "existing_suite": ["python", "-m", "pytest", "tests"],
            "generated_collect": ["python", "-m", "pytest", ".astap/generated_tests", "--collect-only"],
            "generated_suite": ["python", "-m", "pytest", ".astap/generated_tests"],
        },
    }

    client = ExecutorClient(base_url="http://executor:8080")
    result = client.execute(payload)

    assert observed["url"] == "http://executor:8080/executions"
    assert observed["timeout"] == 2430
    assert result.platform_system == "Linux"
