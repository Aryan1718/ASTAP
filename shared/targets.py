import hashlib
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict


def compute_target_key(
    *,
    target_type: str,
    file_path: str,
    symbol: str,
    signature: str | None,
    line_start: int | None,
    line_end: int | None,
) -> str:
    canonical = (
        f"{target_type}|{file_path}|{symbol}|{signature or ''}|"
        f"{line_start or ''}|{line_end or ''}"
    )
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


class SlimTargetMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_start: int | None = None
    line_end: int | None = None
    class_name: str | None = None
    http_method: str | None = None
    route_path: str | None = None
    recommended_test_kind: str | None = None
    priority_score: float | None = None
    language: str | None = None


class SlimTargetRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    target_key: str
    target_type: str
    file_path: str
    symbol: str
    signature: str | None = None
    metadata: SlimTargetMetadata


class RichTargetArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_key: str
    target_type: str
    file_path: str
    symbol: str
    signature: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    class_name: str | None = None
    decorators: list[str]
    framework_hints: list[str]
    http_method: str | None = None
    route_path: str | None = None
    recommended_test_kind: str | None = None
    priority_score: float | None = None
    language: str | None = None
    docstring: str | None = None
    dependency_hints: list[str] | None = None
    source_excerpt: str | None = None


class DiscoverTargetsArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    run_id: str
    generated_at: str
    targets: list[RichTargetArtifact]


class SourceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    line_start: int
    line_end: int
    code: str


class GenerationPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    target_db: SlimTargetRow
    target_artifact: RichTargetArtifact
    source_context: SourceContext


class GeneratedTestStatus(str, Enum):
    generated = "generated"
    skipped = "skipped"
    failed = "failed"


class GeneratedTestManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_key: str
    target_type: str
    symbol: str
    source_file: str
    generated_test_file: str | None = None
    test_kind: str | None = None
    status: GeneratedTestStatus
    skip_reason: str | None = None


class GeneratedTestManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    run_id: str
    generated_at: str
    files: list[GeneratedTestManifestEntry]


class GeneratedTestFileContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    path: str
    content: str
    language: str = "python"


def build_slim_target_row(run_id: str, target: RichTargetArtifact) -> SlimTargetRow:
    # DB metadata is intentionally lightweight for indexing/filtering only.
    metadata = SlimTargetMetadata(
        line_start=target.line_start,
        line_end=target.line_end,
        class_name=target.class_name,
        http_method=target.http_method,
        route_path=target.route_path,
        recommended_test_kind=target.recommended_test_kind,
        priority_score=target.priority_score,
        language=target.language,
    )
    return SlimTargetRow(
        run_id=run_id,
        target_key=target.target_key,
        target_type=target.target_type,
        file_path=target.file_path,
        symbol=target.symbol,
        signature=target.signature,
        metadata=metadata,
    )


def build_discover_targets_artifact(run_id: str, targets: list[RichTargetArtifact]) -> DiscoverTargetsArtifact:
    return DiscoverTargetsArtifact(
        run_id=run_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        targets=targets,
    )


def build_generation_packet_stub(
    target_db: SlimTargetRow,
    target_artifact: RichTargetArtifact,
    source_context: SourceContext,
) -> GenerationPacket:
    # Intended Generate Tests flow:
    # 1. read selected slim target rows from DB
    # 2. load discover/targets.json and map by target_key
    # 3. read source from the immutable snapshot via file_path + line range
    # 4. assemble a generation packet for the LLM/test builder
    return GenerationPacket(
        run_id=target_db.run_id,
        target_db=target_db,
        target_artifact=target_artifact,
        source_context=source_context,
    )


def build_generated_test_manifest(run_id: str, files: list[GeneratedTestManifestEntry]) -> GeneratedTestManifest:
    return GeneratedTestManifest(
        run_id=run_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        files=files,
    )


def short_target_key(target_key: str, length: int = 6) -> str:
    return target_key[:length]


def safe_symbol_name(symbol: str) -> str:
    sanitized = "".join(char if char.isalnum() or char == "_" else "_" for char in symbol.strip())
    sanitized = sanitized.strip("_").lower()
    return sanitized or "target"


def generated_test_relative_path(output_dir: str, target_type: str, symbol: str, target_key: str) -> str:
    if target_type == "SERVICE_FUNCTION":
        subdir = "services"
    elif target_type == "API_ENDPOINT":
        subdir = "api"
    else:
        raise ValueError(f"Unsupported target type for output path: {target_type}")

    filename = f"test_{safe_symbol_name(symbol)}_{short_target_key(target_key)}.py"
    return PurePosixPath(output_dir, subdir, filename).as_posix()


def target_counts_by_type(targets: list[RichTargetArtifact]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for target in targets:
        counts[target.target_type] = counts.get(target.target_type, 0) + 1
    return counts


def artifact_target_by_key(targets: list[RichTargetArtifact]) -> dict[str, RichTargetArtifact]:
    return {target.target_key: target for target in targets}


def serialize_metadata(metadata: SlimTargetMetadata) -> dict[str, Any]:
    return metadata.model_dump(exclude_none=True)
