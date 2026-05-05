from pathlib import Path

from shared.models import Target
from shared.repository import replace_targets_for_run
from shared.targets import (
    DiscoverTargetsArtifact,
    RichTargetArtifact,
    build_discover_targets_artifact,
    build_slim_target_row,
    compute_target_key,
)
from worker.app.jobs.discover import discover_python_targets


def write_sample_repo(repo_path: Path) -> None:
    app_dir = repo_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "main.py").write_text(
        """
from fastapi import APIRouter

router = APIRouter()


def parse_config(path: str) -> dict:
    \"\"\"Parse config input.\"\"\"
    return {"path": path}


@router.get("/items/{id}")
def get_item(item_id: str) -> dict:
    \"\"\"Fetch one item.\"\"\"
    return {"id": item_id}


class UserService:
    \"\"\"Service wrapper.\"\"\"

    def get_name(self) -> str:
        return "user"
""".strip(),
        encoding="utf-8",
    )


def test_compute_target_key_is_deterministic() -> None:
    key_one = compute_target_key(
        target_type="SERVICE_FUNCTION",
        file_path="app/main.py",
        symbol="parse_config",
        signature="parse_config(path: str) -> dict",
        line_start=1,
        line_end=4,
    )
    key_two = compute_target_key(
        target_type="SERVICE_FUNCTION",
        file_path="app/main.py",
        symbol="parse_config",
        signature="parse_config(path: str) -> dict",
        line_start=1,
        line_end=4,
    )

    assert key_one == key_two


def test_discover_uses_same_target_key_for_db_and_artifact(tmp_path: Path) -> None:
    write_sample_repo(tmp_path)

    rich_targets = discover_python_targets(tmp_path)
    slim_targets = [build_slim_target_row("run-1", target) for target in rich_targets]
    artifact = build_discover_targets_artifact("run-1", rich_targets)

    assert {target.target_key for target in rich_targets} == {row.target_key for row in slim_targets}
    assert {target.target_key for target in rich_targets} == {target.target_key for target in artifact.targets}


def test_discover_retry_replaces_rows_without_duplicates() -> None:
    session = RecordingSession()
    target = build_slim_target_row(
        "run-1",
        RichTargetArtifact(
            target_key=compute_target_key(
                target_type="SERVICE_FUNCTION",
                file_path="app/main.py",
                symbol="parse_config",
                signature="parse_config(path: str) -> dict",
                line_start=10,
                line_end=20,
            ),
            target_type="SERVICE_FUNCTION",
            file_path="app/main.py",
            symbol="parse_config",
            signature="parse_config(path: str) -> dict",
            line_start=10,
            line_end=20,
            class_name=None,
            decorators=["cached"],
            framework_hints=["pytest"],
            recommended_test_kind="unit",
            priority_score=0.5,
            language="python",
            docstring="Parse config input.",
            source_excerpt="def parse_config(path: str) -> dict: ...",
        ),
    )

    replace_targets_for_run(session, "run-1", [target])
    replace_targets_for_run(session, "run-1", [target])

    assert len(session.rows) == 1
    assert session.rows[0].target_key == target.target_key


def test_db_metadata_remains_slim() -> None:
    rich_target = RichTargetArtifact(
        target_key="abc123",
        target_type="API_ENDPOINT",
        file_path="app/main.py",
        symbol="get_item",
        signature="get_item(item_id: str) -> dict",
        line_start=11,
        line_end=15,
        class_name="UserService",
        decorators=["router.get"],
        framework_hints=["fastapi", "pytest"],
        http_method="GET",
        route_path="/items/{id}",
        recommended_test_kind="api",
        priority_score=0.95,
        language="python",
        docstring="Fetch one item.",
        dependency_hints=["fastapi.APIRouter"],
        source_excerpt="@router.get('/items/{id}')",
    )

    row = build_slim_target_row("run-1", rich_target)
    metadata = row.metadata.model_dump(exclude_none=True)

    assert metadata == {
        "line_start": 11,
        "line_end": 15,
        "class_name": "UserService",
        "http_method": "GET",
        "route_path": "/items/{id}",
        "recommended_test_kind": "api",
        "priority_score": 0.95,
        "language": "python",
    }
    assert "decorators" not in metadata
    assert "docstring" not in metadata
    assert "dependency_hints" not in metadata
    assert "source_excerpt" not in metadata


def test_discover_targets_json_matches_expected_schema(tmp_path: Path) -> None:
    write_sample_repo(tmp_path)

    rich_targets = discover_python_targets(tmp_path)
    artifact = build_discover_targets_artifact("run-1", rich_targets)
    payload = artifact.model_dump(mode="json")

    assert set(payload) == {"version", "run_id", "generated_at", "targets"}
    assert payload["version"] == 1
    assert payload["run_id"] == "run-1"
    assert payload["targets"]

    first_target = payload["targets"][0]
    assert {
        "target_key",
        "target_type",
        "file_path",
        "symbol",
        "signature",
        "line_start",
        "line_end",
        "class_name",
        "decorators",
        "framework_hints",
        "http_method",
        "route_path",
        "recommended_test_kind",
        "priority_score",
        "language",
    }.issubset(first_target)

    parsed = DiscoverTargetsArtifact.model_validate(payload)
    assert parsed.targets[0].target_key == artifact.targets[0].target_key


def test_unique_run_and_target_key_index_exists() -> None:
    indexes = {index.name: index for index in Target.__table__.indexes}

    assert "targets_run_id_target_key_uidx" in indexes
    assert indexes["targets_run_id_target_key_uidx"].unique is True
    assert [column.name for column in indexes["targets_run_id_target_key_uidx"].columns] == ["run_id", "target_key"]


class RecordingSession:
    def __init__(self) -> None:
        self.rows = []

    def execute(self, _statement) -> None:
        self.rows.clear()

    def add_all(self, items) -> None:
        self.rows.extend(items)

    def commit(self) -> None:
        return None
