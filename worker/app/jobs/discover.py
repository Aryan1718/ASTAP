import ast
import json
import logging
import tempfile
from pathlib import Path
from shutil import rmtree

from shared.config import settings
from shared.db import SessionLocal
from shared.queue import get_queue
from shared.repository import (
    claim_job,
    get_job_by_stage,
    get_run,
    mark_job_failed,
    mark_job_succeeded_with_artifacts,
    mark_run_failed,
    mark_run_running,
    set_job_rq_id,
    replace_targets_for_run,
)
from shared.storage import download_storage_object, upload_file_to_storage
from shared.targets import (
    RichTargetArtifact,
    build_discover_targets_artifact,
    build_slim_target_row,
    compute_target_key,
    target_counts_by_type,
)
from worker.app.jobs.common import safe_extract_tar_gz

logger = logging.getLogger(__name__)

EXCLUDED_DIRS = {".git", ".venv", "__pycache__", "build", "dist", "node_modules", "venv"}
HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


def discover_job(run_id: str, job_id: str) -> None:
    session = SessionLocal()
    temp_dir = Path(tempfile.mkdtemp(prefix="discover-"))
    try:
        job = claim_job(session, job_id)
        if job is None:
            return

        run = get_run(session, run_id)
        if run is None:
            raise RuntimeError("Run not found")
        if not run.snapshot_bucket or not run.snapshot_key:
            raise RuntimeError("Run snapshot metadata is missing")

        mark_run_running(session, run_id)

        snapshot_path = temp_dir / "snapshot.tar.gz"
        repo_path = temp_dir / "repo"
        download_storage_object(run.snapshot_bucket, run.snapshot_key, snapshot_path)
        safe_extract_tar_gz(snapshot_path, repo_path)

        rich_targets = discover_python_targets(repo_path)
        slim_targets = [build_slim_target_row(run.id, target) for target in rich_targets]
        replace_targets_for_run(session, run.id, slim_targets)

        payload = build_discover_targets_artifact(run.id, rich_targets)
        targets_path = temp_dir / "targets.json"
        targets_path.write_text(json.dumps(payload.model_dump(mode="json"), indent=2), encoding="utf-8")

        object_key = f"{run.workspace_id}/{run.project_id}/{run.id}/discover/targets.json"
        upload_file_to_storage(
            bucket=settings.supabase_storage_bucket,
            object_key=object_key,
            source=targets_path,
            content_type="application/json",
        )

        counts_by_type = target_counts_by_type(rich_targets)
        logger.info(
            "Discover completed for run %s: total_targets=%s counts_by_type=%s artifact_path=%s",
            run.id,
            len(rich_targets),
            counts_by_type,
            object_key,
        )

        targets_artifact = {
            "artifact_type": "targets_json",
            "bucket": settings.supabase_storage_bucket,
            "key": object_key,
        }
        mark_job_succeeded_with_artifacts(
            session,
            job_id=job.id,
            output_json={
                "targets_count": len(rich_targets),
                "target_counts_by_type": counts_by_type,
                "language": "python",
                "framework_hint": "pytest",
                "artifact_path": object_key,
            },
            artifacts_json=[targets_artifact],
        )

        generate_tests = get_job_by_stage(session, run.id, "generate_tests")
        if generate_tests is None:
            raise RuntimeError("Generate tests job not found")

        rq_job = get_queue("generate_tests").enqueue("worker.app.jobs.generate_tests_job", run.id, generate_tests.id)
        set_job_rq_id(session, generate_tests.id, rq_job.id)
    except Exception as exc:  # noqa: BLE001
        mark_job_failed(session, job_id, f"{type(exc).__name__}: {exc}")
        mark_run_failed(session, run_id)
        raise
    finally:
        session.close()
        rmtree(temp_dir, ignore_errors=True)


def discover_python_targets(repo_path: Path) -> list[RichTargetArtifact]:
    targets: list[RichTargetArtifact] = []

    for path in sorted(repo_path.rglob("*.py")):
        relative_path = path.relative_to(repo_path)
        if should_skip_path(relative_path):
            continue

        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(relative_path))
        targets.extend(extract_targets_from_module(relative_path, source, tree))

    return targets


def should_skip_path(relative_path: Path) -> bool:
    parts = relative_path.parts
    return any(part in EXCLUDED_DIRS or part == "tests" for part in parts)


def extract_targets_from_module(relative_path: Path, source: str, tree: ast.Module) -> list[RichTargetArtifact]:
    targets: list[RichTargetArtifact] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = [decorator_name(decorator) for decorator in node.decorator_list]
            targets.append(
                build_rich_target(
                    target_type="SERVICE_FUNCTION",
                    relative_path=relative_path,
                    symbol=node.name,
                    signature=function_signature(node),
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    decorators=decorators,
                    framework_hints=["pytest"],
                    recommended_test_kind="unit",
                    priority_score=0.5,
                    language="python",
                    docstring=ast.get_docstring(node),
                    source_excerpt=source_excerpt_for_node(source, node),
                )
            )
            targets.extend(fastapi_targets(relative_path, source, node))
        elif isinstance(node, ast.ClassDef):
            decorators = [decorator_name(decorator) for decorator in node.decorator_list]
            targets.append(
                build_rich_target(
                    target_type="SERVICE_FUNCTION",
                    relative_path=relative_path,
                    symbol=node.name,
                    signature=node.name,
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    class_name=node.name,
                    decorators=decorators,
                    framework_hints=["pytest"],
                    recommended_test_kind="unit",
                    priority_score=0.55,
                    language="python",
                    docstring=ast.get_docstring(node),
                    source_excerpt=source_excerpt_for_node(source, node),
                )
            )

    return targets


def build_rich_target(
    *,
    target_type: str,
    relative_path: Path,
    symbol: str,
    signature: str | None,
    line_start: int | None,
    line_end: int | None,
    decorators: list[str],
    framework_hints: list[str],
    class_name: str | None = None,
    http_method: str | None = None,
    route_path: str | None = None,
    recommended_test_kind: str | None = None,
    priority_score: float | None = None,
    language: str | None = None,
    docstring: str | None = None,
    source_excerpt: str | None = None,
) -> RichTargetArtifact:
    file_path = relative_path.as_posix()
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
        class_name=class_name,
        decorators=decorators,
        framework_hints=framework_hints,
        http_method=http_method,
        route_path=route_path,
        recommended_test_kind=recommended_test_kind,
        priority_score=priority_score,
        language=language,
        docstring=docstring,
        source_excerpt=source_excerpt,
    )


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    positional = [*node.args.posonlyargs, *node.args.args]
    positional_defaults_start = len(positional) - len(node.args.defaults)
    parts: list[str] = []

    for index, arg in enumerate(node.args.posonlyargs):
        parts.append(argument_repr(arg, default_for_index(index, positional_defaults_start, node.args.defaults)))
    if node.args.posonlyargs:
        parts.append("/")

    for offset, arg in enumerate(node.args.args, start=len(node.args.posonlyargs)):
        parts.append(argument_repr(arg, default_for_index(offset, positional_defaults_start, node.args.defaults)))

    if node.args.vararg is not None:
        parts.append("*" + argument_repr(node.args.vararg))
    elif node.args.kwonlyargs:
        parts.append("*")

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        parts.append(argument_repr(arg, default))

    if node.args.kwarg is not None:
        parts.append("**" + argument_repr(node.args.kwarg))

    signature = f"{node.name}({', '.join(parts)})"
    if node.returns is not None:
        signature = f"{signature} -> {safe_unparse(node.returns)}"
    return signature


def default_for_index(index: int, defaults_start: int, defaults: list[ast.expr]) -> ast.expr | None:
    default_index = index - defaults_start
    if default_index < 0:
        return None
    return defaults[default_index]


def argument_repr(arg: ast.arg, default: ast.expr | None = None) -> str:
    rendered = arg.arg
    if arg.annotation is not None:
        rendered = f"{rendered}: {safe_unparse(arg.annotation)}"
    if default is not None:
        rendered = f"{rendered} = {safe_unparse(default)}"
    return rendered


def fastapi_targets(
    relative_path: Path,
    source: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[RichTargetArtifact]:
    targets: list[RichTargetArtifact] = []
    decorators = [decorator_name(decorator) for decorator in node.decorator_list]
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if not isinstance(decorator.func, ast.Attribute):
            continue
        if decorator.func.attr not in HTTP_METHODS:
            continue
        if not decorator.args or not isinstance(decorator.args[0], ast.Constant) or not isinstance(decorator.args[0].value, str):
            continue

        targets.append(
            build_rich_target(
                target_type="API_ENDPOINT",
                relative_path=relative_path,
                symbol=node.name,
                signature=function_signature(node),
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                decorators=decorators,
                framework_hints=["fastapi", "pytest"],
                http_method=decorator.func.attr.upper(),
                route_path=decorator.args[0].value,
                recommended_test_kind="api",
                priority_score=0.95,
                language="python",
                docstring=ast.get_docstring(node),
                source_excerpt=source_excerpt_for_node(source, node),
            )
        )
    return targets


def decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        prefix = decorator_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return safe_unparse(node)


def safe_unparse(node: ast.AST) -> str:
    return ast.unparse(node)


def source_excerpt_for_node(source: str, node: ast.AST) -> str | None:
    if not source:
        return None
    excerpt = ast.get_source_segment(source, node)
    if excerpt is None:
        return None
    excerpt = excerpt.strip()
    if not excerpt:
        return None
    return excerpt[:1200]
