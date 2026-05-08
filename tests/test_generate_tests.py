import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.config import GenerateTestsConfig, Settings
from shared.security_recipes import match_security_recipes
from shared.targets import (
    RichTargetArtifact,
    build_discover_targets_artifact,
    build_slim_target_row,
    compute_target_key,
    generated_test_relative_path,
    generated_security_test_relative_path,
)
from worker.app.jobs.generate_tests import (
    build_generation_packet,
    build_generic_generation_packet,
    evaluate_runnability,
    generate_tests_job,
    select_generic_fallback_candidates_for_generation,
    select_recipe_candidates_for_generation,
    validate_generated_test_code,
)


def make_rich_target(
    *,
    target_type: str,
    file_path: str,
    symbol: str,
    signature: str,
    line_start: int,
    line_end: int,
    http_method: str | None = None,
    route_path: str | None = None,
    framework_hints: list[str] | None = None,
    risk_tags: list[str] | None = None,
    input_sources: list[str] | None = None,
    dangerous_sinks: list[str] | None = None,
    execution_context: dict | None = None,
) -> RichTargetArtifact:
    resolved_framework_hints = framework_hints or ["pytest"]
    if execution_context is None:
        execution_context = {
            "module_path": "app.main",
            "import_hint": f"app.main:{symbol}",
            "framework_hints": resolved_framework_hints,
        }
        if target_type == "API_ENDPOINT":
            execution_context.update(
                {
                    "route_path": route_path,
                    "fastapi_router_symbol": "router" if "fastapi" in resolved_framework_hints else None,
                    "fastapi_test_client_candidate": "fastapi" in resolved_framework_hints,
                }
            )
    return RichTargetArtifact(
        target_key=compute_target_key(
            target_type=target_type,
            file_path=file_path,
            symbol=symbol,
            signature=signature,
            line_start=line_start,
            line_end=line_end,
        ),
        target_type=target_type,
        file_path=file_path,
        symbol=symbol,
        signature=signature,
        line_start=line_start,
        line_end=line_end,
        class_name=None,
        decorators=[],
        framework_hints=resolved_framework_hints,
        http_method=http_method,
        route_path=route_path,
        recommended_test_kind="api" if target_type == "API_ENDPOINT" else "unit",
        priority_score=0.9,
        language="python",
        dependency_hints=[],
        risk_tags=risk_tags or [],
        input_sources=input_sources or [],
        dangerous_sinks=dangerous_sinks or [],
        auth_hints=[],
        execution_context=execution_context,
        source_excerpt=None,
    )


def write_repo_fixture(repo_path: Path) -> None:
    app_dir = repo_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "main.py").write_text(
        """
from fastapi import APIRouter

router = APIRouter()


def parse_config(path: str) -> dict:
    if not path:
        raise ValueError("path is required")
    return {"path": path}


@router.get("/items/{item_id}")
def get_item(item_id: str) -> dict:
    return {"id": item_id}
""".strip(),
        encoding="utf-8",
    )


def create_snapshot(repo_path: Path, snapshot_path: Path) -> None:
    with tarfile.open(snapshot_path, "w:gz") as archive:
        for path in repo_path.rglob("*"):
            archive.add(path, arcname=path.relative_to(repo_path))


def test_generate_tests_job_creates_one_file_per_supported_target_and_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_path = tmp_path / "repo"
    write_repo_fixture(repo_path)
    snapshot_path = tmp_path / "snapshot.tar.gz"
    create_snapshot(repo_path, snapshot_path)

    service_target = make_rich_target(
        target_type="SERVICE_FUNCTION",
        file_path="app/main.py",
        symbol="parse_config",
        signature="parse_config(path: str) -> dict",
        line_start=6,
        line_end=9,
        risk_tags=["filesystem_access", "path_traversal_candidate"],
        input_sources=["function_parameter", "file_input"],
        dangerous_sinks=["filesystem_access"],
    )
    api_target = make_rich_target(
        target_type="API_ENDPOINT",
        file_path="app/main.py",
        symbol="get_item",
        signature="get_item(item_id: str) -> dict",
        line_start=12,
        line_end=14,
        http_method="GET",
        route_path="/items/{item_id}",
        framework_hints=["fastapi", "pytest"],
        risk_tags=["database_access", "sql_injection_candidate", "public_input"],
        input_sources=["path_parameter"],
        dangerous_sinks=["database_access"],
    )
    unsupported_target = make_rich_target(
        target_type="WORKFLOW_STEP",
        file_path="app/main.py",
        symbol="workflow_node",
        signature="workflow_node()",
        line_start=1,
        line_end=1,
    )
    discover_artifact = build_discover_targets_artifact("run-1", [service_target, api_target, unsupported_target])

    db_targets = [
        SimpleNamespace(
            run_id="run-1",
            target_key=target.target_key,
            target_type=target.target_type,
            file_path=target.file_path,
            symbol=target.symbol,
            signature=target.signature,
            target_metadata=build_slim_target_row("run-1", target).metadata.model_dump(exclude_none=True),
        )
        for target in [service_target, api_target, unsupported_target]
    ]

    uploads: dict[str, str] = {}
    marks: dict[str, object] = {}
    enqueued: dict[str, object] = {}
    provider_outputs = {
        service_target.target_key: "import pytest\n\ndef test_parse_config_returns_dict():\n    assert parse_config('cfg')['path'] == 'cfg'\n",
        api_target.target_key: (
            "def test_get_item_status_code():\n"
            "    assert 200 == 200\n\n"
            "def test_get_item_json_shape():\n"
            "    assert {'id': '1'}['id'] == '1'\n"
        ),
    }

    class FakeProvider:
        def __init__(self, api_key: str, config: GenerateTestsConfig) -> None:
            self.api_key = api_key
            self.config = config

        def generate_test_code(self, packet) -> str:
            return provider_outputs[packet.target_db.target_key]

    class FakeSession:
        def close(self) -> None:
            return None

    monkeypatch.setattr("worker.app.jobs.generate_tests.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.generate_tests.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            snapshot_bucket="runs",
            snapshot_key="workspace-1/project-1/run-1/snapshot/snapshot.tar.gz",
        ),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.mark_run_running", lambda session, run_id: None)
    monkeypatch.setattr("worker.app.jobs.generate_tests.list_targets_for_run", lambda session, run_id: db_targets)
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.download_storage_object",
        lambda bucket, object_key, destination: destination.write_bytes(snapshot_path.read_bytes()),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.download_storage_object_text",
        lambda bucket, object_key: json.dumps(discover_artifact.model_dump(mode="json")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8") if source.suffix != ".zip" else "zip"),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.OpenAIGenerateTestsProvider", FakeProvider)
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            OPENAI_API_KEY="test-key",
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.mark_job_succeeded_with_artifacts",
        lambda session, job_id, output_json, artifacts_json: marks.update(
            {"job_id": job_id, "output_json": output_json, "artifacts_json": artifacts_json}
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(id="exec-job-1") if stage == "execute_tests" else None,
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_queue",
        lambda name: SimpleNamespace(enqueue=lambda fn, run_id, job_id: SimpleNamespace(id=f"rq-{name}")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.set_job_rq_id",
        lambda session, job_id, rq_job_id: enqueued.update({"job_id": job_id, "rq_job_id": rq_job_id}),
    )

    generate_tests_job("run-1", "job-1")

    service_path = generated_security_test_relative_path("generated_tests", "parse_config", "path_traversal", service_target.target_key)
    api_path = generated_security_test_relative_path("generated_tests", "get_item", "sql_injection", api_target.target_key)
    manifest_key = "workspace-1/project-1/run-1/generated_tests/test_index.json"

    assert f"workspace-1/project-1/run-1/{service_path}" in uploads
    assert f"workspace-1/project-1/run-1/{api_path}" in uploads
    assert manifest_key in uploads

    manifest = json.loads(uploads[manifest_key])
    generated_entries = [entry for entry in manifest["files"] if entry["status"] == "generated"]
    skipped_entries = [entry for entry in manifest["files"] if entry["status"] == "skipped"]

    assert len(generated_entries) == 2
    assert {entry["generated_test_file"] for entry in generated_entries} == {service_path, api_path}
    assert {entry["recipe_id"] for entry in generated_entries} == {"path_traversal", "sql_injection"}
    assert skipped_entries == [
        {
            "target_key": unsupported_target.target_key,
            "target_type": "WORKFLOW_STEP",
            "symbol": "workflow_node",
            "source_file": "app/main.py",
            "generated_test_file": None,
            "test_kind": None,
            "status": "skipped",
            "generation_mode": None,
            "recipe_id": None,
            "recipe_name": None,
            "risk_tags": [],
            "skip_reason": "unsupported_target_type:WORKFLOW_STEP",
        }
    ]
    assert manifest["empty_reason"] is None
    assert marks["output_json"] == {
        "supported_targets": 2,
        "runnable_targets": 2,
        "generated_files": 2,
        "skipped_targets": 1,
        "manifest_path": manifest_key,
        "artifact_paths": [service_path, api_path, "generated_tests/test_index.json", "generated_tests.zip"],
        "empty_reason": None,
    }
    assert enqueued == {"job_id": "exec-job-1", "rq_job_id": "rq-execute_tests"}


def test_generate_tests_retry_reuses_same_artifact_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_path = tmp_path / "repo"
    write_repo_fixture(repo_path)
    snapshot_path = tmp_path / "snapshot.tar.gz"
    create_snapshot(repo_path, snapshot_path)

    target = make_rich_target(
        target_type="SERVICE_FUNCTION",
        file_path="app/main.py",
        symbol="parse_config",
        signature="parse_config(path: str) -> dict",
        line_start=6,
        line_end=9,
        risk_tags=["filesystem_access", "path_traversal_candidate"],
        input_sources=["function_parameter"],
        dangerous_sinks=["filesystem_access"],
    )
    discover_artifact = build_discover_targets_artifact("run-1", [target])
    db_target = SimpleNamespace(
        run_id="run-1",
        target_key=target.target_key,
        target_type=target.target_type,
        file_path=target.file_path,
        symbol=target.symbol,
        signature=target.signature,
        target_metadata=build_slim_target_row("run-1", target).metadata.model_dump(exclude_none=True),
    )
    uploads: dict[str, str] = {}
    generated_versions = iter(
        [
            "def test_parse_config_first_pass():\n    assert True\n",
            "def test_parse_config_second_pass():\n    assert True\n",
        ]
    )

    class FakeProvider:
        def __init__(self, api_key: str, config: GenerateTestsConfig) -> None:
            self.api_key = api_key
            self.config = config

        def generate_test_code(self, packet) -> str:
            return next(generated_versions)

    class FakeSession:
        def close(self) -> None:
            return None

    monkeypatch.setattr("worker.app.jobs.generate_tests.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.generate_tests.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            snapshot_bucket="runs",
            snapshot_key="workspace-1/project-1/run-1/snapshot/snapshot.tar.gz",
        ),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.mark_run_running", lambda session, run_id: None)
    monkeypatch.setattr("worker.app.jobs.generate_tests.list_targets_for_run", lambda session, run_id: [db_target])
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.download_storage_object",
        lambda bucket, object_key, destination: destination.write_bytes(snapshot_path.read_bytes()),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.download_storage_object_text",
        lambda bucket, object_key: json.dumps(discover_artifact.model_dump(mode="json")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8") if source.suffix != ".zip" else "zip"),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.OpenAIGenerateTestsProvider", FakeProvider)
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            OPENAI_API_KEY="test-key",
        ),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.mark_job_succeeded_with_artifacts", lambda session, job_id, output_json, artifacts_json: None)
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(id="exec-job") if stage == "execute_tests" else None,
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_queue",
        lambda name: SimpleNamespace(enqueue=lambda fn, run_id, job_id: SimpleNamespace(id=f"rq-{job_id}")),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.set_job_rq_id", lambda session, job_id, rq_job_id: None)

    generate_tests_job("run-1", "job-1")
    generate_tests_job("run-1", "job-2")

    file_key = f"workspace-1/project-1/run-1/{generated_security_test_relative_path('generated_tests', 'parse_config', 'path_traversal', target.target_key)}"
    assert "test_parse_config_second_pass" in uploads[file_key]
    assert len([key for key in uploads if key.endswith(".py")]) == 1


def test_generate_tests_skips_unsupported_target_types() -> None:
    supported = make_rich_target(
        target_type="SERVICE_FUNCTION",
        file_path="app/main.py",
        symbol="parse_config",
        signature="parse_config(path: str) -> dict",
        line_start=1,
        line_end=4,
        risk_tags=["filesystem_access", "path_traversal_candidate"],
        input_sources=["function_parameter"],
        dangerous_sinks=["filesystem_access"],
    )
    db_targets = [
        SimpleNamespace(
            run_id="run-1",
            target_key=supported.target_key,
            target_type=supported.target_type,
            file_path=supported.file_path,
            symbol=supported.symbol,
            signature=supported.signature,
            target_metadata=build_slim_target_row("run-1", supported).metadata.model_dump(exclude_none=True),
        ),
        SimpleNamespace(
            run_id="run-1",
            target_key="unsupported-1",
            target_type="MCP_TOOL",
            file_path="app/main.py",
            symbol="tool",
            signature="tool()",
            target_metadata={},
        ),
    ]

    selected, skipped = select_recipe_candidates_for_generation(
        db_targets=db_targets,
        targets_by_key={supported.target_key: supported},
        config=GenerateTestsConfig(),
    )

    assert len(selected) == 1
    assert selected[0].target_row.target_key == supported.target_key
    assert selected[0].recipe_match.recipe_id == "path_traversal"
    assert skipped[0].skip_reason == "unsupported_target_type:MCP_TOOL"


def test_generate_tests_selects_generic_fallback_when_no_security_recipe_matches() -> None:
    service_target = make_rich_target(
        target_type="SERVICE_FUNCTION",
        file_path="app/main.py",
        symbol="parse_config",
        signature="parse_config(path: str | None = None) -> dict",
        line_start=1,
        line_end=4,
        risk_tags=[],
        input_sources=["function_parameter"],
        dangerous_sinks=[],
    )
    db_targets = [
        SimpleNamespace(
            run_id="run-1",
            target_key=service_target.target_key,
            target_type=service_target.target_type,
            file_path=service_target.file_path,
            symbol=service_target.symbol,
            signature=service_target.signature,
            target_metadata=build_slim_target_row("run-1", service_target).metadata.model_dump(exclude_none=True),
        )
    ]

    selected, skipped = select_generic_fallback_candidates_for_generation(
        db_targets=db_targets,
        targets_by_key={service_target.target_key: service_target},
        config=GenerateTestsConfig(),
    )

    assert len(selected) == 1
    assert selected[0].target_row.target_key == service_target.target_key
    assert skipped == []


def test_evaluate_runnability_rejects_missing_fastapi_context() -> None:
    target = make_rich_target(
        target_type="API_ENDPOINT",
        file_path="app/main.py",
        symbol="get_item",
        signature="get_item(item_id: str) -> dict",
        line_start=1,
        line_end=4,
        framework_hints=["fastapi", "pytest"],
        risk_tags=["sql_injection_candidate", "public_input"],
        input_sources=["path_parameter"],
        dangerous_sinks=["database_access"],
        execution_context={
            "module_path": "app.main",
            "import_hint": "app.main:get_item",
            "framework_hints": ["fastapi", "pytest"],
            "route_path": "/items/{item_id}",
            "fastapi_router_symbol": None,
            "fastapi_test_client_candidate": False,
        },
    )

    result = evaluate_runnability(target)

    assert result.allowed is False
    assert result.reason == "runnability_missing_fastapi_test_client_context"


def test_generate_tests_job_skips_unrunnable_recipe_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_path = tmp_path / "repo"
    write_repo_fixture(repo_path)
    snapshot_path = tmp_path / "snapshot.tar.gz"
    create_snapshot(repo_path, snapshot_path)

    api_target = make_rich_target(
        target_type="API_ENDPOINT",
        file_path="app/main.py",
        symbol="get_item",
        signature="get_item(item_id: str) -> dict",
        line_start=12,
        line_end=14,
        http_method="GET",
        route_path="/items/{item_id}",
        framework_hints=["fastapi", "pytest"],
        risk_tags=["database_access", "sql_injection_candidate", "public_input"],
        input_sources=["path_parameter"],
        dangerous_sinks=["database_access"],
        execution_context={
            "module_path": "app.main",
            "import_hint": "app.main:get_item",
            "framework_hints": ["fastapi", "pytest"],
            "route_path": "/items/{item_id}",
            "fastapi_router_symbol": None,
            "fastapi_test_client_candidate": False,
        },
    )
    discover_artifact = build_discover_targets_artifact("run-1", [api_target])
    db_targets = [
        SimpleNamespace(
            run_id="run-1",
            target_key=api_target.target_key,
            target_type=api_target.target_type,
            file_path=api_target.file_path,
            symbol=api_target.symbol,
            signature=api_target.signature,
            target_metadata=build_slim_target_row("run-1", api_target).metadata.model_dump(exclude_none=True),
        )
    ]

    uploads: dict[str, str] = {}
    marks: dict[str, object] = {}
    enqueued: dict[str, object] = {}

    class FakeProvider:
        def __init__(self, api_key: str, config: GenerateTestsConfig) -> None:
            self.api_key = api_key
            self.config = config

        def generate_test_code(self, packet) -> str:
            raise AssertionError("Provider should not be called for unrunnable targets")

    class FakeSession:
        def close(self) -> None:
            return None

    monkeypatch.setattr("worker.app.jobs.generate_tests.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.generate_tests.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            snapshot_bucket="runs",
            snapshot_key="workspace-1/project-1/run-1/snapshot/snapshot.tar.gz",
        ),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.mark_run_running", lambda session, run_id: None)
    monkeypatch.setattr("worker.app.jobs.generate_tests.list_targets_for_run", lambda session, run_id: db_targets)
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.download_storage_object",
        lambda bucket, object_key, destination: destination.write_bytes(snapshot_path.read_bytes()),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.download_storage_object_text",
        lambda bucket, object_key: json.dumps(discover_artifact.model_dump(mode="json")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8") if source.suffix != ".zip" else "zip"),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.OpenAIGenerateTestsProvider", FakeProvider)
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            OPENAI_API_KEY="test-key",
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.mark_job_succeeded_with_artifacts",
        lambda session, job_id, output_json, artifacts_json: marks.update(
            {"job_id": job_id, "output_json": output_json, "artifacts_json": artifacts_json}
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(id="exec-job-2") if stage == "execute_tests" else None,
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_queue",
        lambda name: SimpleNamespace(enqueue=lambda fn, run_id, job_id: SimpleNamespace(id=f"rq-{name}")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.set_job_rq_id",
        lambda session, job_id, rq_job_id: enqueued.update({"job_id": job_id, "rq_job_id": rq_job_id}),
    )

    generate_tests_job("run-1", "job-1")

    manifest_key = "workspace-1/project-1/run-1/generated_tests/test_index.json"
    manifest = json.loads(uploads[manifest_key])
    assert manifest["files"] == [
        {
            "target_key": api_target.target_key,
            "target_type": "API_ENDPOINT",
            "symbol": "get_item",
            "source_file": "app/main.py",
            "generated_test_file": None,
            "test_kind": "security",
            "status": "skipped",
            "generation_mode": "security_recipe",
            "recipe_id": "sql_injection",
            "recipe_name": "SQL Injection",
            "risk_tags": ["database_access", "sql_injection_candidate", "public_input"],
            "skip_reason": "runnability_missing_fastapi_test_client_context",
        }
    ]
    assert manifest["empty_reason"] == "no_eligible_targets_after_runnability_filtering"
    assert marks["output_json"] == {
        "supported_targets": 1,
        "runnable_targets": 0,
        "generated_files": 0,
        "skipped_targets": 1,
        "manifest_path": manifest_key,
        "artifact_paths": ["generated_tests/test_index.json", "generated_tests.zip"],
        "empty_reason": "no_eligible_targets_after_runnability_filtering",
    }
    assert enqueued == {"job_id": "exec-job-2", "rq_job_id": "rq-execute_tests"}


def test_generate_tests_job_uses_generic_fallback_when_no_security_recipe_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "repo"
    write_repo_fixture(repo_path)
    snapshot_path = tmp_path / "snapshot.tar.gz"
    create_snapshot(repo_path, snapshot_path)

    service_target = make_rich_target(
        target_type="SERVICE_FUNCTION",
        file_path="app/main.py",
        symbol="parse_config",
        signature="parse_config(path: str) -> dict",
        line_start=6,
        line_end=9,
        risk_tags=[],
        input_sources=["function_parameter"],
        dangerous_sinks=[],
    )
    discover_artifact = build_discover_targets_artifact("run-1", [service_target])
    db_targets = [
        SimpleNamespace(
            run_id="run-1",
            target_key=service_target.target_key,
            target_type=service_target.target_type,
            file_path=service_target.file_path,
            symbol=service_target.symbol,
            signature=service_target.signature,
            target_metadata=build_slim_target_row("run-1", service_target).metadata.model_dump(exclude_none=True),
        )
    ]
    uploads: dict[str, str] = {}
    marks: dict[str, object] = {}

    class FakeProvider:
        def __init__(self, api_key: str, config: GenerateTestsConfig) -> None:
            self.api_key = api_key
            self.config = config

        def generate_test_code(self, packet) -> str:
            assert packet.generation_mode == "generic_fallback"
            return "def test_parse_config_smoke():\n    assert parse_config('cfg')['path'] == 'cfg'\n"

    class FakeSession:
        def close(self) -> None:
            return None

    monkeypatch.setattr("worker.app.jobs.generate_tests.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("worker.app.jobs.generate_tests.claim_job", lambda session, job_id: SimpleNamespace(id=job_id))
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_run",
        lambda session, run_id: SimpleNamespace(
            id=run_id,
            workspace_id="workspace-1",
            project_id="project-1",
            snapshot_bucket="runs",
            snapshot_key="workspace-1/project-1/run-1/snapshot/snapshot.tar.gz",
        ),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.mark_run_running", lambda session, run_id: None)
    monkeypatch.setattr("worker.app.jobs.generate_tests.list_targets_for_run", lambda session, run_id: db_targets)
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.download_storage_object",
        lambda bucket, object_key, destination: destination.write_bytes(snapshot_path.read_bytes()),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.download_storage_object_text",
        lambda bucket, object_key: json.dumps(discover_artifact.model_dump(mode="json")),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.upload_file_to_storage",
        lambda bucket, object_key, source, content_type: uploads.__setitem__(object_key, source.read_text(encoding="utf-8") if source.suffix != ".zip" else "zip"),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.OpenAIGenerateTestsProvider", FakeProvider)
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.settings",
        Settings(
            DATABASE_URL="sqlite:///tmp.db",
            REDIS_URL="redis://localhost:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="service-role-key",
            SUPABASE_STORAGE_BUCKET="runs",
            OPENAI_API_KEY="test-key",
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.mark_job_succeeded_with_artifacts",
        lambda session, job_id, output_json, artifacts_json: marks.update(
            {"job_id": job_id, "output_json": output_json, "artifacts_json": artifacts_json}
        ),
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_job_by_stage",
        lambda session, run_id, stage: SimpleNamespace(id="exec-job-fallback") if stage == "execute_tests" else None,
    )
    monkeypatch.setattr(
        "worker.app.jobs.generate_tests.get_queue",
        lambda name: SimpleNamespace(enqueue=lambda fn, run_id, job_id: SimpleNamespace(id=f"rq-{name}")),
    )
    monkeypatch.setattr("worker.app.jobs.generate_tests.set_job_rq_id", lambda session, job_id, rq_job_id: None)

    generate_tests_job("run-1", "job-fallback")

    file_path = generated_test_relative_path("generated_tests", "SERVICE_FUNCTION", "parse_config", service_target.target_key)
    manifest_key = "workspace-1/project-1/run-1/generated_tests/test_index.json"
    manifest = json.loads(uploads[manifest_key])
    assert manifest["files"][0]["generation_mode"] == "generic_fallback"
    assert manifest["files"][0]["generated_test_file"] == file_path
    assert manifest["files"][0]["recipe_id"] is None
    assert manifest["empty_reason"] is None
    assert f"workspace-1/project-1/run-1/{file_path}" in uploads
    assert marks["output_json"]["supported_targets"] == 1
    assert marks["output_json"]["empty_reason"] is None


def test_generated_test_paths_are_stable_and_routed_by_target_type() -> None:
    assert generated_security_test_relative_path("generated_tests", "parse.config", "path_traversal", "a1b2c3d4") == (
        "generated_tests/security/test_parse_config_path_traversal_a1b2c3.py"
    )
    assert generated_security_test_relative_path("generated_tests", "get-user", "sql_injection", "f9e8d7c6") == (
        "generated_tests/security/test_get_user_sql_injection_f9e8d7.py"
    )


def test_validate_generated_test_code_rejects_invalid_python() -> None:
    with pytest.raises(SyntaxError):
        validate_generated_test_code("def test_broken(:\n    pass\n")


def test_validate_generated_test_code_rejects_markdown_fences() -> None:
    with pytest.raises(ValueError, match="markdown_fences_not_allowed"):
        validate_generated_test_code("```python\ndef test_x():\n    assert True\n```")


def test_target_key_mapping_from_db_to_artifact_builds_packet(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    write_repo_fixture(repo_path)
    target = make_rich_target(
        target_type="SERVICE_FUNCTION",
        file_path="app/main.py",
        symbol="parse_config",
        signature="parse_config(path: str) -> dict",
        line_start=6,
        line_end=9,
        risk_tags=["filesystem_access", "path_traversal_candidate"],
        input_sources=["function_parameter"],
        dangerous_sinks=["filesystem_access"],
    )
    db_target = build_slim_target_row("run-1", target)
    recipe_match = match_security_recipes(target)[0]
    packet = build_generation_packet("run-1", repo_path, db_target, target, recipe_match)

    assert packet is not None
    assert packet.target_db.target_key == packet.target_artifact.target_key
    assert packet.recipe_id == "path_traversal"
    assert "def parse_config" in packet.source_context.code


def test_generic_fallback_packet_builder_marks_mode(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    write_repo_fixture(repo_path)
    target = make_rich_target(
        target_type="SERVICE_FUNCTION",
        file_path="app/main.py",
        symbol="parse_config",
        signature="parse_config(path: str) -> dict",
        line_start=6,
        line_end=9,
        risk_tags=[],
        input_sources=["function_parameter"],
        dangerous_sinks=[],
    )

    packet = build_generic_generation_packet("run-1", repo_path, build_slim_target_row("run-1", target), target)

    assert packet is not None
    assert packet.generation_mode == "generic_fallback"


def test_generate_tests_config_reads_new_env_fields() -> None:
    settings = Settings(
        DATABASE_URL="sqlite:///tmp.db",
        REDIS_URL="redis://localhost:6379/0",
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY="service-role-key",
        SUPABASE_STORAGE_BUCKET="runs",
        OPENAI_API_KEY="test-key",
        GENERATE_TESTS_MODEL="gpt-4.1-mini",
        GENERATE_TESTS_MAX_TOKENS=1234,
        GENERATE_TESTS_TEMPERATURE=0.4,
        GENERATE_TESTS_MAX_TARGETS_PER_RUN=12,
        GENERATE_TESTS_OUTPUT_DIR="generated_tests",
        GENERATE_TESTS_ENABLE_SERVICE_FUNCTIONS=False,
        GENERATE_TESTS_ENABLE_API_ENDPOINTS=True,
    )

    config = settings.generate_tests_config()

    assert config.model == "gpt-4.1-mini"
    assert config.max_tokens == 1234
    assert config.temperature == 0.4
    assert config.max_targets_per_run == 12
    assert config.output_dir == "generated_tests"
    assert config.enable_service_functions is False
    assert config.enable_api_endpoints is True
    assert settings.require_openai_api_key_for_generate_tests() == "test-key"
