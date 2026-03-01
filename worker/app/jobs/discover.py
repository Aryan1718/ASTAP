import ast
import json
import tempfile
from pathlib import Path
from shutil import rmtree

from shared.config import settings
from shared.db import SessionLocal
from shared.repository import (
    claim_job,
    get_run,
    mark_job_failed,
    mark_job_succeeded_with_artifacts,
    mark_run_failed,
    mark_run_running,
    mark_run_succeeded,
    replace_targets_for_run,
)
from worker.app.jobs.common import download_storage_object, safe_extract_tar_gz, upload_file_to_storage

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

        discovered_targets = discover_python_targets(repo_path)
        replace_targets_for_run(session, run.id, discovered_targets)

        payload = {
            "run_id": run.id,
            "language": "python",
            "framework_hint": "pytest",
            "targets": discovered_targets,
        }
        targets_path = temp_dir / "targets.json"
        targets_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        object_key = f"{run.workspace_id}/{run.project_id}/{run.id}/discover/targets.json"
        upload_file_to_storage(
            bucket=settings.supabase_storage_bucket,
            object_key=object_key,
            source=targets_path,
            content_type="application/json",
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
                "targets_count": len(discovered_targets),
                "language": "python",
                "framework_hint": "pytest",
            },
            artifacts_json=[targets_artifact],
        )
        mark_run_succeeded(session, run_id=run.id)
    except Exception as exc:  # noqa: BLE001
        mark_job_failed(session, job_id, f"{type(exc).__name__}: {exc}")
        mark_run_failed(session, run_id)
        raise
    finally:
        session.close()
        rmtree(temp_dir, ignore_errors=True)


def discover_python_targets(repo_path: Path) -> list[dict]:
    targets: list[dict] = []

    for path in sorted(repo_path.rglob("*.py")):
        relative_path = path.relative_to(repo_path)
        if should_skip_path(relative_path):
            continue

        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(relative_path))
        targets.extend(extract_targets_from_module(relative_path, tree))

    return targets


def should_skip_path(relative_path: Path) -> bool:
    parts = relative_path.parts
    return any(part in EXCLUDED_DIRS or part == "tests" for part in parts)


def extract_targets_from_module(relative_path: Path, tree: ast.Module) -> list[dict]:
    module_name = module_name_for_path(relative_path)
    targets: list[dict] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = [decorator_name(decorator) for decorator in node.decorator_list]
            targets.append(
                {
                    "target_type": "SERVICE_FUNCTION",
                    "file_path": relative_path.as_posix(),
                    "symbol": node.name,
                    "signature": function_signature(node),
                    "metadata": {
                        "module": module_name,
                        "decorators": decorators,
                        "line_start": node.lineno,
                        "line_end": getattr(node, "end_lineno", node.lineno),
                    },
                }
            )
            targets.extend(fastapi_targets(relative_path, node))
        elif isinstance(node, ast.ClassDef):
            decorators = [decorator_name(decorator) for decorator in node.decorator_list]
            targets.append(
                {
                    "target_type": "SERVICE_FUNCTION",
                    "file_path": relative_path.as_posix(),
                    "symbol": node.name,
                    "signature": node.name,
                    "metadata": {
                        "module": module_name,
                        "kind": "class",
                        "decorators": decorators,
                        "line_start": node.lineno,
                        "line_end": getattr(node, "end_lineno", node.lineno),
                    },
                }
            )

    return targets


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


def fastapi_targets(relative_path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict]:
    targets: list[dict] = []
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
            {
                "target_type": "API_ENDPOINT",
                "file_path": relative_path.as_posix(),
                "symbol": node.name,
                "signature": function_signature(node),
                "metadata": {
                    "method": decorator.func.attr.upper(),
                    "path": decorator.args[0].value,
                    "handler": node.name,
                    "line_start": node.lineno,
                    "line_end": getattr(node, "end_lineno", node.lineno),
                },
            }
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


def module_name_for_path(relative_path: Path) -> str:
    parts = list(relative_path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def safe_unparse(node: ast.AST) -> str:
    return ast.unparse(node)
