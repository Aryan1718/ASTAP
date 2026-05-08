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
REQUEST_INPUT_ANNOTATIONS = {"Request", "Body", "Payload"}
QUERY_INPUT_ANNOTATIONS = {"Query"}
PATH_INPUT_ANNOTATIONS = {"Path"}
FILE_INPUT_ANNOTATIONS = {"File", "UploadFile"}
AUTH_DEPENDENCY_HINTS = {"Depends", "Security"}
FILESYSTEM_CALLS = {
    "open",
    "Path.open",
    "Path.read_bytes",
    "Path.read_text",
    "Path.write_bytes",
    "Path.write_text",
    "os.open",
    "os.remove",
    "os.unlink",
    "shutil.copy",
    "shutil.copyfile",
    "shutil.move",
    "shutil.rmtree",
}
COMMAND_EXECUTION_CALLS = {
    "os.system",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "subprocess.run",
}
UNSAFE_DESERIALIZATION_CALLS = {
    "marshal.load",
    "marshal.loads",
    "pickle.load",
    "pickle.loads",
    "yaml.full_load",
    "yaml.load",
}
NETWORK_CALL_PREFIXES = ("httpx.", "requests.", "urllib.request.")
AUTH_HINT_KEYWORDS = ("auth", "login", "permission", "role", "scope", "jwt", "token", "current_user")


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
            "artifact_type": "discover_targets",
            "bucket": settings.supabase_storage_bucket,
            "key": object_key,
            "path": "discover/targets.json",
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
            security_metadata = analyze_security_metadata(
                node=node,
                target_type="SERVICE_FUNCTION",
                decorators=decorators,
            )
            targets.append(
                build_rich_target(
                    target_type="SERVICE_FUNCTION",
                    relative_path=relative_path,
                    symbol=node.name,
                    signature=function_signature(node),
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    decorators=decorators,
                    framework_hints=sorted({"pytest", *security_metadata["framework_hints"]}),
                    recommended_test_kind="unit",
                    priority_score=0.5,
                    language="python",
                    docstring=ast.get_docstring(node),
                    dependency_hints=security_metadata["dependency_hints"],
                    risk_tags=security_metadata["risk_tags"],
                    input_sources=security_metadata["input_sources"],
                    dangerous_sinks=security_metadata["dangerous_sinks"],
                    auth_hints=security_metadata["auth_hints"],
                    execution_context=build_execution_context(
                        relative_path=relative_path,
                        target_type="SERVICE_FUNCTION",
                        symbol=node.name,
                        framework_hints=sorted({"pytest", *security_metadata["framework_hints"]}),
                        route_path=None,
                        decorators=decorators,
                    ),
                    source_excerpt=source_excerpt_for_node(source, node),
                )
            )
            targets.extend(api_endpoint_targets(relative_path, source, node))
        elif isinstance(node, ast.ClassDef):
            decorators = [decorator_name(decorator) for decorator in node.decorator_list]
            security_metadata = analyze_security_metadata(
                node=node,
                target_type="SERVICE_FUNCTION",
                decorators=decorators,
            )
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
                    framework_hints=sorted({"pytest", *security_metadata["framework_hints"]}),
                    recommended_test_kind="unit",
                    priority_score=0.55,
                    language="python",
                    docstring=ast.get_docstring(node),
                    dependency_hints=security_metadata["dependency_hints"],
                    risk_tags=security_metadata["risk_tags"],
                    input_sources=security_metadata["input_sources"],
                    dangerous_sinks=security_metadata["dangerous_sinks"],
                    auth_hints=security_metadata["auth_hints"],
                    execution_context=build_execution_context(
                        relative_path=relative_path,
                        target_type="SERVICE_FUNCTION",
                        symbol=node.name,
                        framework_hints=sorted({"pytest", *security_metadata["framework_hints"]}),
                        route_path=None,
                        decorators=decorators,
                    ),
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
    dependency_hints: list[str] | None = None,
    risk_tags: list[str] | None = None,
    input_sources: list[str] | None = None,
    dangerous_sinks: list[str] | None = None,
    auth_hints: list[str] | None = None,
    execution_context: dict[str, object] | None = None,
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
        dependency_hints=dependency_hints or [],
        risk_tags=risk_tags or [],
        input_sources=input_sources or [],
        dangerous_sinks=dangerous_sinks or [],
        auth_hints=auth_hints or [],
        execution_context=execution_context or {},
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


def api_endpoint_targets(
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
        route_details = route_decorator_details(decorator)
        if route_details is None:
            continue
        security_metadata = analyze_security_metadata(
            node=node,
            target_type="API_ENDPOINT",
            decorators=decorators,
            route_path=route_details["route_path"],
            framework=route_details["framework"],
        )
        framework_hints = sorted({route_details["framework"], "pytest", *security_metadata["framework_hints"]})

        targets.append(
            build_rich_target(
                target_type="API_ENDPOINT",
                relative_path=relative_path,
                symbol=node.name,
                signature=function_signature(node),
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                decorators=decorators,
                framework_hints=framework_hints,
                http_method=route_details["http_method"],
                route_path=route_details["route_path"],
                recommended_test_kind="api",
                priority_score=0.95,
                language="python",
                docstring=ast.get_docstring(node),
                dependency_hints=security_metadata["dependency_hints"],
                risk_tags=security_metadata["risk_tags"],
                input_sources=security_metadata["input_sources"],
                dangerous_sinks=security_metadata["dangerous_sinks"],
                auth_hints=security_metadata["auth_hints"],
                execution_context=build_execution_context(
                    relative_path=relative_path,
                    target_type="API_ENDPOINT",
                    symbol=node.name,
                    framework_hints=framework_hints,
                    route_path=route_details["route_path"],
                    decorators=decorators,
                    framework=route_details["framework"],
                ),
                source_excerpt=source_excerpt_for_node(source, node),
            )
        )
    return targets


def analyze_security_metadata(
    *,
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    target_type: str,
    decorators: list[str],
    route_path: str | None = None,
    framework: str | None = None,
) -> dict[str, list[str]]:
    input_sources: set[str] = set()
    dangerous_sinks: set[str] = set()
    auth_hints: set[str] = set()
    dependency_hints: set[str] = set()
    framework_hints: set[str] = set()

    if target_type == "API_ENDPOINT":
        input_sources.add("public_input")
        if framework:
            framework_hints.add(framework)
        if route_path and "{" in route_path and "}" in route_path:
            input_sources.add("path_parameter")

    for decorator in decorators:
        dependency_hints.add(decorator)
        if "router." in decorator or "app." in decorator:
            framework_hints.add("fastapi")
        if ".route" in decorator or "blueprint." in decorator:
            framework_hints.add("flask")
        if contains_auth_hint(decorator):
            auth_hints.add("auth_required")

    for arg_name in function_argument_names(node):
        if target_type == "SERVICE_FUNCTION":
            input_sources.add("function_parameter")
        if arg_name in {"request", "body", "payload", "data"}:
            input_sources.add("request_body")
        if arg_name in {"query", "q", "search", "filter"}:
            input_sources.add("query_parameter")
        if arg_name in {"file", "filename", "filepath", "path"}:
            input_sources.add("file_input")
        if arg_name in {"user", "current_user", "token"}:
            auth_hints.add("auth_context_argument")

    for metadata in parameter_metadata(node):
        annotation = metadata["annotation"]
        default_call = metadata["default_call"]

        if annotation in REQUEST_INPUT_ANNOTATIONS:
            input_sources.add("request_body")
        if annotation in QUERY_INPUT_ANNOTATIONS:
            input_sources.add("query_parameter")
        if annotation in PATH_INPUT_ANNOTATIONS:
            input_sources.add("path_parameter")
        if annotation in FILE_INPUT_ANNOTATIONS:
            input_sources.add("file_input")
        if annotation in {"Request"}:
            input_sources.add("public_input")

        if default_call in AUTH_DEPENDENCY_HINTS and contains_auth_hint(metadata["default_call_arg"]):
            auth_hints.add("auth_required")
            dependency_hints.add(f"{default_call}({metadata['default_call_arg']})")
        elif contains_auth_hint(annotation):
            auth_hints.add("auth_context_argument")

    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            call_name = decorator_name(child.func)
            if call_name:
                dependency_hints.add(call_name)

            if call_name in FILESYSTEM_CALLS or call_name.startswith("Path."):
                dangerous_sinks.add("filesystem_access")
            if call_name in COMMAND_EXECUTION_CALLS:
                dangerous_sinks.add("command_execution")
                if keyword_is_true(child, "shell"):
                    dangerous_sinks.add("shell_usage")
            if call_name.endswith(".execute") or call_name.endswith(".executemany"):
                dangerous_sinks.add("database_access")
            if call_name in UNSAFE_DESERIALIZATION_CALLS:
                dangerous_sinks.add("deserialization")
            if call_name.startswith(NETWORK_CALL_PREFIXES):
                dangerous_sinks.add("network_access")

            if contains_auth_hint(call_name):
                auth_hints.add("auth_required")
            if call_name.startswith("subprocess."):
                framework_hints.add("subprocess")
            if call_name.startswith(("requests.", "httpx.", "urllib.request.")):
                framework_hints.add("http_client")
            if call_name.startswith(("sqlalchemy.", "session.", "cursor.")) or call_name.endswith(".execute"):
                framework_hints.add("database")

        if isinstance(child, ast.Import):
            for alias in child.names:
                dependency_hints.add(alias.name)
        elif isinstance(child, ast.ImportFrom):
            module = child.module or ""
            if module:
                dependency_hints.add(module)

    if target_type == "API_ENDPOINT" and not auth_hints:
        auth_hints.add("auth_missing_or_unclear")

    risk_tags = derive_risk_tags(
        target_type=target_type,
        input_sources=input_sources,
        dangerous_sinks=dangerous_sinks,
        auth_hints=auth_hints,
    )

    return {
        "dependency_hints": sorted(dependency_hints),
        "risk_tags": sorted(risk_tags),
        "input_sources": sorted(input_sources),
        "dangerous_sinks": sorted(dangerous_sinks),
        "auth_hints": sorted(auth_hints),
        "framework_hints": sorted(framework_hints),
    }


def function_argument_names(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []

    args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    names = [arg.arg for arg in args if arg.arg not in {"self", "cls"}]
    if node.args.vararg is not None and node.args.vararg.arg not in {"self", "cls"}:
        names.append(node.args.vararg.arg)
    if node.args.kwarg is not None and node.args.kwarg.arg not in {"self", "cls"}:
        names.append(node.args.kwarg.arg)
    return names


def parameter_metadata(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[dict[str, str]]:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []

    metadata: list[dict[str, str]] = []
    positional = [*node.args.posonlyargs, *node.args.args]
    positional_defaults_start = len(positional) - len(node.args.defaults)

    for index, arg in enumerate(positional):
        metadata.append(
            {
                "name": arg.arg,
                "annotation": annotation_name(arg.annotation),
                "default_call": default_call_name(default_for_index(index, positional_defaults_start, node.args.defaults)),
                "default_call_arg": default_call_first_arg(default_for_index(index, positional_defaults_start, node.args.defaults)),
            }
        )

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        metadata.append(
            {
                "name": arg.arg,
                "annotation": annotation_name(arg.annotation),
                "default_call": default_call_name(default),
                "default_call_arg": default_call_first_arg(default),
            }
        )

    return metadata


def annotation_name(annotation: ast.expr | None) -> str:
    if annotation is None:
        return ""
    return decorator_name(annotation)


def default_call_name(default: ast.expr | None) -> str:
    if not isinstance(default, ast.Call):
        return ""
    return decorator_name(default.func)


def default_call_first_arg(default: ast.expr | None) -> str:
    if not isinstance(default, ast.Call) or not default.args:
        return ""
    first_arg = default.args[0]
    if isinstance(first_arg, ast.Name):
        return first_arg.id
    if isinstance(first_arg, ast.Attribute):
        return decorator_name(first_arg)
    return ""


def contains_auth_hint(value: str) -> bool:
    lower_value = value.lower()
    return any(keyword in lower_value for keyword in AUTH_HINT_KEYWORDS)


def keyword_is_true(node: ast.Call, keyword_name: str) -> bool:
    for keyword in node.keywords:
        if keyword.arg != keyword_name:
            continue
        if isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
            return True
    return False


def derive_risk_tags(
    *,
    target_type: str,
    input_sources: set[str],
    dangerous_sinks: set[str],
    auth_hints: set[str],
) -> set[str]:
    risk_tags = set(input_sources)
    risk_tags.update(dangerous_sinks)

    if target_type == "API_ENDPOINT":
        risk_tags.add("http_entrypoint")

    if "auth_required" in auth_hints:
        risk_tags.add("auth_required")
    if "auth_missing_or_unclear" in auth_hints:
        risk_tags.add("auth_missing_or_unclear")

    has_user_controlled_input = bool(input_sources.intersection({"public_input", "function_parameter", "query_parameter", "request_body", "path_parameter", "file_input"}))
    if has_user_controlled_input and "filesystem_access" in dangerous_sinks:
        risk_tags.add("path_traversal_candidate")
    if has_user_controlled_input and "command_execution" in dangerous_sinks:
        risk_tags.add("command_injection_candidate")
    if has_user_controlled_input and "database_access" in dangerous_sinks:
        risk_tags.add("sql_injection_candidate")
    if has_user_controlled_input and "network_access" in dangerous_sinks:
        risk_tags.add("ssrf_candidate")
    if has_user_controlled_input and "deserialization" in dangerous_sinks:
        risk_tags.add("unsafe_deserialization_candidate")

    return risk_tags


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


def build_execution_context(
    *,
    relative_path: Path,
    target_type: str,
    symbol: str,
    framework_hints: list[str],
    route_path: str | None,
    decorators: list[str],
    framework: str | None = None,
) -> dict[str, object]:
    module_path = module_path_for_file(relative_path)
    import_hint = f"{module_path}:{symbol}" if module_path else symbol
    context: dict[str, object] = {
        "module_path": module_path,
        "import_hint": import_hint,
        "framework_hints": framework_hints,
    }
    if target_type == "API_ENDPOINT":
        fastapi_router_symbol = infer_fastapi_router_symbol(decorators) if framework == "fastapi" else None
        flask_app_symbol = infer_flask_app_symbol(decorators) if framework == "flask" else None
        context.update(
            {
                "api_framework": framework,
                "route_path": route_path,
                "fastapi_router_symbol": fastapi_router_symbol,
                "fastapi_test_client_candidate": "fastapi" in framework_hints and bool(fastapi_router_symbol),
                "flask_app_symbol": flask_app_symbol,
                "flask_test_client_candidate": "flask" in framework_hints and bool(flask_app_symbol),
            }
        )
    return context


def module_path_for_file(relative_path: Path) -> str:
    parts = list(relative_path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def infer_fastapi_router_symbol(decorators: list[str]) -> str | None:
    for decorator in decorators:
        if decorator.startswith("router."):
            return "router"
        if decorator.startswith("app."):
            return "app"
    return None


def infer_flask_app_symbol(decorators: list[str]) -> str | None:
    for decorator in decorators:
        if decorator.startswith("app.route"):
            return "app"
        if decorator.startswith("blueprint.route"):
            return "blueprint"
    return None


def route_decorator_details(decorator: ast.Call) -> dict[str, str] | None:
    if not isinstance(decorator.func, ast.Attribute):
        return None
    route_path = constant_string_arg(decorator)
    if route_path is None:
        return None

    if decorator.func.attr in HTTP_METHODS:
        return {
            "framework": "fastapi",
            "http_method": decorator.func.attr.upper(),
            "route_path": route_path,
        }

    if decorator.func.attr != "route":
        return None

    methods = flask_route_methods(decorator)
    if not methods:
        methods = ["GET"]

    return {
        "framework": "flask",
        "http_method": methods[0],
        "route_path": route_path,
    }


def constant_string_arg(decorator: ast.Call) -> str | None:
    if not decorator.args:
        return None
    first_arg = decorator.args[0]
    if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
        return None
    return first_arg.value


def flask_route_methods(decorator: ast.Call) -> list[str]:
    for keyword in decorator.keywords:
        if keyword.arg != "methods":
            continue
        if not isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
            return []
        methods: list[str] = []
        for element in keyword.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                methods.append(element.value.upper())
        return methods
    return []
