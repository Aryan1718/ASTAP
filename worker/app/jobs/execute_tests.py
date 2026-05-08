import json
import logging
import shlex
import tempfile
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from shutil import rmtree

from shared.config import ExecuteTestsConfig, settings
from shared.db import SessionLocal
from shared.repository import (
    claim_job,
    get_job_by_stage,
    get_run,
    mark_job_failed,
    mark_job_succeeded_with_artifacts,
    mark_run_failed,
    mark_run_running,
    set_job_rq_id,
)
from shared.queue import get_queue
from shared.storage import download_storage_object, download_storage_object_text, upload_file_to_storage
from shared.targets import GeneratedTestManifest, GeneratedTestStatus
from worker.app.jobs.common import safe_extract_tar_gz

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(slots=True)
class CommandSelection:
    command: list[str]
    source: str


@dataclass(slots=True)
class ExecutionPlan:
    framework: str
    install_commands: list[CommandSelection]
    existing_test_command: CommandSelection
    generated_test_command: CommandSelection
    suite_timeout_seconds: int
    detection_notes: list[str]


@dataclass(slots=True)
class ExecutorExecutionResult:
    python_version: str
    platform_system: str
    isolation: dict
    steps: dict
    error: dict | None


class ExecutorClient:
    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def execute(self, payload: dict) -> ExecutorExecutionResult:
        request = urllib.request.Request(
            url=f"{self.base_url}/executions",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Executor API request failed with status {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Executor API request failed: {exc.reason}") from exc

        return ExecutorExecutionResult(
            python_version=str(response_payload.get("python_version", "unknown")),
            platform_system=str(response_payload.get("platform_system", "unknown")),
            isolation=response_payload.get("isolation", {}),
            steps=response_payload.get("steps", {}),
            error=response_payload.get("error"),
        )


def execute_tests_job(run_id: str, job_id: str) -> None:
    session = SessionLocal()
    workspace_dir: Path | None = None
    try:
        job = claim_job(session, job_id)
        if job is None:
            return

        config = settings.execute_tests_config()
        run = get_run(session, run_id)
        if run is None:
            raise RuntimeError("Run not found")
        if not run.snapshot_bucket or not run.snapshot_key:
            raise RuntimeError("Run snapshot metadata is missing")

        generate_tests_job = get_job_by_stage(session, run.id, "generate_tests")
        if generate_tests_job is None or generate_tests_job.status != "succeeded":
            raise RuntimeError("Generate tests outputs are not available")

        mark_run_running(session, run_id)

        Path(config.shared_workspace_root).mkdir(parents=True, exist_ok=True)
        workspace_dir = Path(tempfile.mkdtemp(prefix="execute-tests-", dir=config.shared_workspace_root))
        repo_path = workspace_dir / "repo"
        out_dir = workspace_dir / "out"
        tmp_dir = workspace_dir / "tmp"
        out_root = out_dir / config.output_dir
        logs_dir = out_root / "logs"
        junit_dir = out_root / "junit"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        junit_dir.mkdir(parents=True, exist_ok=True)

        snapshot_path = workspace_dir / "snapshot.tar.gz"
        download_storage_object(run.snapshot_bucket, run.snapshot_key, snapshot_path)
        safe_extract_tar_gz(snapshot_path, repo_path)

        manifest = load_generated_test_manifest(generate_tests_job)
        generated_tests_root = repo_path / ".astap" / "generated_tests"
        materialized_generated_files = materialize_generated_tests(
            manifest=manifest,
            generate_tests_job=generate_tests_job,
            generated_tests_root=generated_tests_root,
        )

        execution_plan = detect_execution_plan(
            repo_path=repo_path,
            run_config=getattr(run, "run_config", {}) or {},
            config=config,
        )

        executor = ExecutorClient(base_url=config.executor_base_url)
        execution_result = executor.execute(
            build_executor_request(
                run=run,
                config=config,
                workspace_dir=workspace_dir,
                execution_plan=execution_plan,
                include_generated_suite=bool(materialized_generated_files),
            )
        )

        install_results = build_install_results(execution_result.steps.get("install", []), execution_plan.install_commands)
        existing_suite = run_existing_tests_suite(
            junit_dir=junit_dir,
            logs_dir=logs_dir,
            command_selection=execution_plan.existing_test_command,
            result_payload=execution_result.steps.get("existing_suite"),
        )
        generated_suite = run_generated_tests_suite(
            generated_files=materialized_generated_files,
            junit_dir=junit_dir,
            logs_dir=logs_dir,
            command_selection=execution_plan.generated_test_command,
            result_payload=execution_result.steps.get("generated_suite"),
        )

        results_payload = build_results_payload(
            run_id=run.id,
            config=config,
            execution_plan=execution_plan,
            python_version=execution_result.python_version,
            platform_system=execution_result.platform_system,
            isolation=execution_result.isolation,
            install_results=install_results,
            existing_suite=existing_suite,
            generated_suite=generated_suite,
            error=execution_result.error,
        )
        results_path = out_root / "results.json"
        results_path.write_text(json.dumps(results_payload, indent=2), encoding="utf-8")
        if execution_result.error is not None:
            write_environment_setup_log(logs_dir / "environment-setup.log", execution_result)

        uploaded_artifacts = upload_execution_artifacts(
            run=run,
            output_dir=config.output_dir,
            results_path=results_path,
            logs_dir=logs_dir,
            junit_dir=junit_dir,
        )
        output_json = build_job_output_json(
            execution_plan=execution_plan,
            results_payload=results_payload,
            uploaded_artifacts=uploaded_artifacts,
        )
        if execution_result.error is not None:
            error_type = execution_result.error.get("type", "environment_setup_failed")
            error_message = execution_result.error.get("message", "Execution environment setup failed")
            mark_job_failed(
                session,
                job.id,
                f"{error_type}: {error_message}",
                output_json=output_json,
                artifacts_json=uploaded_artifacts,
            )
            enqueue_analyze_job(session, run.id)
            return

        mark_job_succeeded_with_artifacts(session, job_id=job.id, output_json=output_json, artifacts_json=uploaded_artifacts)
        enqueue_analyze_job(session, run.id)
    except Exception as exc:  # noqa: BLE001
        mark_job_failed(session, job_id, f"{type(exc).__name__}: {exc}")
        mark_run_failed(session, run_id)
        raise
    finally:
        session.close()
        if workspace_dir is not None:
            rmtree(workspace_dir, ignore_errors=True)


def load_generated_test_manifest(generate_tests_job) -> GeneratedTestManifest:
    manifest_artifact = next(
        (
            artifact
            for artifact in generate_tests_job.artifacts_json
            if artifact.get("artifact_type") == "generated_tests_manifest"
        ),
        None,
    )
    if manifest_artifact is None:
        raise RuntimeError("Generated tests manifest artifact not found")

    bucket = manifest_artifact.get("bucket")
    key = manifest_artifact.get("key")
    if not isinstance(bucket, str) or not isinstance(key, str):
        raise RuntimeError("Generated tests manifest artifact metadata is invalid")

    payload = download_storage_object_text(bucket, key)
    return GeneratedTestManifest.model_validate_json(payload)


def materialize_generated_tests(*, manifest: GeneratedTestManifest, generate_tests_job, generated_tests_root: Path) -> list[Path]:
    artifacts_by_path = {
        artifact.get("path"): artifact
        for artifact in generate_tests_job.artifacts_json
        if artifact.get("artifact_type") == "generated_test_file"
    }
    generated_paths: list[Path] = []
    for entry in manifest.files:
        if entry.status != GeneratedTestStatus.generated or not entry.generated_test_file:
            continue
        artifact = artifacts_by_path.get(entry.generated_test_file)
        if artifact is None:
            raise RuntimeError(f"Generated test artifact missing for path {entry.generated_test_file}")

        bucket = artifact.get("bucket")
        key = artifact.get("key")
        if not isinstance(bucket, str) or not isinstance(key, str):
            raise RuntimeError(f"Generated test artifact metadata is invalid for path {entry.generated_test_file}")

        relative_output_path = _generated_test_relative_output_path(entry.generated_test_file)
        destination = generated_tests_root / relative_output_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(download_storage_object_text(bucket, key), encoding="utf-8")
        generated_paths.append(destination)
    return generated_paths


def _generated_test_relative_output_path(manifest_path: str) -> Path:
    if not manifest_path.startswith(f"{settings.generate_tests_output_dir}/"):
        raise RuntimeError(f"Unexpected generated test path: {manifest_path}")
    relative = manifest_path.removeprefix(f"{settings.generate_tests_output_dir}/")
    return Path(relative)


def detect_execution_plan(*, repo_path: Path, run_config: dict, config: ExecuteTestsConfig) -> ExecutionPlan:
    execute_config = run_config.get("execute_tests") if isinstance(run_config, dict) else {}
    if not isinstance(execute_config, dict):
        execute_config = {}

    detection_notes: list[str] = []
    framework = "pytest"
    test_targets = detect_test_targets(repo_path)
    if test_targets:
        detection_notes.append(f"Detected pytest test targets from repo config: {', '.join(test_targets)}")

    install_commands = detect_install_commands(repo_path, detection_notes)
    existing_command = build_existing_test_command(test_targets)
    generated_command = build_generated_test_command()
    suite_timeout_seconds = config.suite_timeout_seconds

    override_install_commands = parse_optional_commands(execute_config.get("install_commands"))
    override_install_command = parse_optional_command(execute_config.get("install_command"))
    if override_install_commands is not None and override_install_command is not None:
        raise RuntimeError("run_config.execute_tests must not define both install_command and install_commands")
    if override_install_commands is not None:
        install_commands = [CommandSelection(command=command, source="run_config.install_commands") for command in override_install_commands]
        detection_notes.append("Using install commands from run_config.execute_tests.install_commands")
    elif override_install_command is not None:
        install_commands = [CommandSelection(command=override_install_command, source="run_config.install_command")]
        detection_notes.append("Using install command from run_config.execute_tests.install_command")

    override_test_command = parse_optional_command(execute_config.get("test_command"))
    override_existing_command = parse_optional_command(execute_config.get("existing_test_command"))
    if override_test_command is not None and override_existing_command is not None:
        raise RuntimeError("run_config.execute_tests must not define both test_command and existing_test_command")
    if override_existing_command is not None:
        existing_command = CommandSelection(command=override_existing_command, source="run_config.existing_test_command")
        detection_notes.append("Using existing test command from run_config.execute_tests.existing_test_command")
    elif override_test_command is not None:
        existing_command = CommandSelection(command=override_test_command, source="run_config.test_command")
        detection_notes.append("Using existing test command from run_config.execute_tests.test_command")

    override_generated_command = parse_optional_command(execute_config.get("generated_test_command"))
    if override_generated_command is not None:
        generated_command = CommandSelection(command=override_generated_command, source="run_config.generated_test_command")
        detection_notes.append("Using generated test command from run_config.execute_tests.generated_test_command")

    override_timeout = execute_config.get("suite_timeout_seconds")
    if override_timeout is not None:
        try:
            suite_timeout_seconds = int(override_timeout)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("run_config.execute_tests.suite_timeout_seconds must be an integer") from exc
        if suite_timeout_seconds <= 0:
            raise RuntimeError("run_config.execute_tests.suite_timeout_seconds must be greater than 0")
        detection_notes.append("Using suite timeout from run_config.execute_tests.suite_timeout_seconds")

    return ExecutionPlan(
        framework=framework,
        install_commands=install_commands,
        existing_test_command=existing_command,
        generated_test_command=generated_command,
        suite_timeout_seconds=suite_timeout_seconds,
        detection_notes=detection_notes,
    )


def detect_install_commands(repo_path: Path, detection_notes: list[str]) -> list[CommandSelection]:
    commands: list[CommandSelection] = []
    requirements_path = repo_path / "requirements.txt"
    pyproject_path = repo_path / "pyproject.toml"
    if requirements_path.exists():
        commands.append(
            CommandSelection(
                command=["python", "-m", "pip", "install", "-r", requirements_path.name],
                source="repo.requirements_txt",
            )
        )
        detection_notes.append("Detected requirements.txt for dependency installation")
        return commands

    if pyproject_path.exists():
        commands.append(CommandSelection(command=detect_pyproject_install_command(pyproject_path), source="repo.pyproject_toml"))
        detection_notes.append("Detected pyproject.toml for package installation")
    else:
        detection_notes.append("No Python dependency manifest detected; relying on the execution image for pytest")
    return commands


def detect_pyproject_install_command(pyproject_path: Path) -> list[str]:
    pyproject = load_toml_file(pyproject_path)
    project = pyproject.get("project")
    if isinstance(project, dict):
        optional_dependencies = project.get("optional-dependencies")
        if isinstance(optional_dependencies, dict):
            for extra_name in ("test", "tests", "dev"):
                extra_values = optional_dependencies.get(extra_name)
                if isinstance(extra_values, list) and extra_values:
                    return ["python", "-m", "pip", "install", f".[{extra_name}]"]
    return ["python", "-m", "pip", "install", "."]


def detect_test_targets(repo_path: Path) -> list[str]:
    for candidate in (
        detect_pyproject_test_targets(repo_path / "pyproject.toml"),
        detect_ini_test_targets(repo_path / "pytest.ini", section="pytest"),
        detect_ini_test_targets(repo_path / "setup.cfg", section="tool:pytest"),
        detect_ini_test_targets(repo_path / "tox.ini", section="pytest"),
    ):
        if candidate:
            return candidate
    if (repo_path / "tests").exists():
        return ["tests"]
    return ["."]


def detect_pyproject_test_targets(pyproject_path: Path) -> list[str] | None:
    if not pyproject_path.exists():
        return None
    pyproject = load_toml_file(pyproject_path)
    tool = pyproject.get("tool")
    if not isinstance(tool, dict):
        return None
    pytest_config = tool.get("pytest")
    if not isinstance(pytest_config, dict):
        return None
    ini_options = pytest_config.get("ini_options")
    if not isinstance(ini_options, dict):
        return None
    return normalize_test_targets(ini_options.get("testpaths"))


def detect_ini_test_targets(config_path: Path, *, section: str) -> list[str] | None:
    if not config_path.exists():
        return None
    parser = ConfigParser()
    parser.read(config_path, encoding="utf-8")
    if not parser.has_section(section):
        return None
    raw_value = parser.get(section, "testpaths", fallback="").strip()
    if not raw_value:
        return None
    return normalize_test_targets(raw_value)


def normalize_test_targets(value: object) -> list[str] | None:
    if isinstance(value, list):
        targets = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        collapsed = value.replace("\n", " ")
        targets = [token.strip() for token in collapsed.split() if token.strip()]
    else:
        return None
    return targets or None


def build_existing_test_command(test_targets: list[str]) -> CommandSelection:
    return CommandSelection(
        command=[
            "python",
            "-m",
            "pytest",
            *test_targets,
            "--ignore=.astap/generated_tests",
        ],
        source="repo_detection.pytest",
    )


def build_generated_test_command() -> CommandSelection:
    return CommandSelection(
        command=["python", "-m", "pytest", ".astap/generated_tests"],
        source="platform_default.generated_pytest",
    )


def parse_optional_commands(value: object) -> list[list[str]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise RuntimeError("run_config.execute_tests.install_commands must be a non-empty list")
    return [parse_required_command(item, config_key="run_config.execute_tests.install_commands") for item in value]


def parse_optional_command(value: object) -> list[str] | None:
    if value is None:
        return None
    return parse_required_command(value, config_key="run_config.execute_tests")


def parse_required_command(value: object, *, config_key: str) -> list[str]:
    if isinstance(value, str):
        command = shlex.split(value)
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        command = [item.strip() for item in value if item.strip()]
    else:
        raise RuntimeError(f"{config_key} command value must be a string or list of strings")
    if not command:
        raise RuntimeError(f"{config_key} command value must not be empty")
    return command


def load_toml_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    return payload if isinstance(payload, dict) else {}


def run_install_commands(
    executor_steps: list[dict],
    commands: list[CommandSelection],
) -> list[dict]:
    results: list[dict] = []
    for selection, result in zip(commands, executor_steps, strict=False):
        results.append(
            {
                "command": selection.command,
                "source": selection.source,
                "exit_code": result.get("exit_code"),
                "duration_seconds": result.get("duration_seconds", 0.0),
                "stdout_excerpt": str(result.get("stdout", ""))[-2000:],
                "stderr_excerpt": str(result.get("stderr", ""))[-2000:],
            }
        )
    return results


def run_existing_tests_suite(
    *,
    junit_dir: Path,
    logs_dir: Path,
    command_selection: CommandSelection,
    result_payload: dict | None,
) -> dict:
    junit_path = junit_dir / "existing-tests.xml"
    log_path = logs_dir / "existing-tests.log"
    if result_payload is None:
        return summarize_missing_suite_result("existing", junit_path, log_path, source=command_selection.source)
    result = command_result_from_payload(result_payload)
    write_suite_log(log_path, result)
    return summarize_suite_result("existing", result, junit_path, log_path, source=command_selection.source)


def run_generated_tests_suite(
    *,
    generated_files: list[Path],
    junit_dir: Path,
    logs_dir: Path,
    command_selection: CommandSelection,
    result_payload: dict | None,
) -> dict:
    junit_path = junit_dir / "generated-tests.xml"
    log_path = logs_dir / "generated-tests.log"
    if not generated_files:
        log_path.write_text("No generated tests were materialized for this run.\n", encoding="utf-8")
        return {
            "suite_key": "generated",
            "status": "skipped",
            "command": None,
            "command_source": command_selection.source,
            "exit_code": None,
            "collected": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "duration_seconds": 0.0,
            "log_path": _relative_output_path(log_path),
            "junit_path": None,
        }

    if result_payload is None:
        return summarize_missing_suite_result("generated", junit_path, log_path, source=command_selection.source)
    result = command_result_from_payload(result_payload)
    write_suite_log(log_path, result)
    return summarize_suite_result("generated", result, junit_path, log_path, source=command_selection.source)


def write_suite_log(log_path: Path, result: CommandResult) -> None:
    payload = [
        f"command: {shlex.join(result.command)}",
        f"exit_code: {result.exit_code}",
        f"duration_seconds: {result.duration_seconds}",
        "",
        "stdout:",
        result.stdout,
        "",
        "stderr:",
        result.stderr,
    ]
    log_path.write_text("\n".join(payload).strip() + "\n", encoding="utf-8")


def summarize_suite_result(suite_key: str, result: CommandResult, junit_path: Path, log_path: Path, *, source: str) -> dict:
    counts = parse_junit_counts(junit_path)
    if counts is None:
        status = "error" if result.exit_code != 0 else "passed"
        counts = {"collected": 0, "failed": 0, "errors": 0, "skipped": 0, "passed": 0}
    else:
        status = "passed" if result.exit_code == 0 else "failed"
    return {
        "suite_key": suite_key,
        "status": status,
        "command": result.command,
        "command_source": source,
        "exit_code": result.exit_code,
        "collected": counts["collected"],
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "duration_seconds": result.duration_seconds,
        "log_path": _relative_output_path(log_path),
        "junit_path": _relative_output_path(junit_path) if junit_path.exists() else None,
    }


def summarize_missing_suite_result(suite_key: str, junit_path: Path, log_path: Path, *, source: str) -> dict:
    log_path.write_text("Suite did not execute because environment setup failed.\n", encoding="utf-8")
    return {
        "suite_key": suite_key,
        "status": "error",
        "command": None,
        "command_source": source,
        "exit_code": None,
        "collected": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 0.0,
        "log_path": _relative_output_path(log_path),
        "junit_path": _relative_output_path(junit_path) if junit_path.exists() else None,
    }


def parse_junit_counts(junit_path: Path) -> dict | None:
    if not junit_path.exists():
        return None

    root = ET.fromstring(junit_path.read_text(encoding="utf-8"))
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    tests = failures = errors = skipped = 0
    for suite in suites:
        tests += int(suite.attrib.get("tests", 0))
        failures += int(suite.attrib.get("failures", 0))
        errors += int(suite.attrib.get("errors", 0))
        skipped += int(suite.attrib.get("skipped", 0))
    passed = max(tests - failures - errors - skipped, 0)
    return {
        "collected": tests,
        "passed": passed,
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
    }


def build_results_payload(
    *,
    run_id: str,
    config: ExecuteTestsConfig,
    execution_plan: ExecutionPlan,
    python_version: str,
    platform_system: str,
    isolation: dict,
    install_results: list[dict],
    existing_suite: dict,
    generated_suite: dict,
    error: dict | None,
) -> dict:
    overall_result = "completed_successfully"
    if error is not None:
        overall_result = error.get("type", "environment_setup_failed")
    elif existing_suite["status"] != "passed" or generated_suite["status"] not in {"passed", "skipped"}:
        overall_result = "completed_with_failures"
    attempted_commands = [entry["command"] for entry in install_results]
    if existing_suite["command"] is not None:
        attempted_commands.append(existing_suite["command"])
    if generated_suite["command"] is not None:
        attempted_commands.append(generated_suite["command"])
    return {
        "version": 1,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "framework": execution_plan.framework,
        "environment": {
            "python_version": python_version,
            "platform_system": platform_system,
            "execution_image": config.image,
            "working_directory": "repo",
            "generated_tests_root": ".astap/generated_tests",
            "execution_mode": "bounded_container",
            "worker_has_docker_socket": False,
        },
        "isolation": isolation,
        "execution_plan": {
            "framework": execution_plan.framework,
            "install_commands": [
                {"command": selection.command, "source": selection.source}
                for selection in execution_plan.install_commands
            ],
            "existing_test_command": {
                "command": execution_plan.existing_test_command.command,
                "source": execution_plan.existing_test_command.source,
            },
            "generated_test_command": {
                "command": execution_plan.generated_test_command.command,
                "source": execution_plan.generated_test_command.source,
            },
            "suite_timeout_seconds": execution_plan.suite_timeout_seconds,
            "detection_notes": execution_plan.detection_notes,
        },
        "install": {
            "offline": True,
            "steps": install_results,
        },
        "existing_tests": existing_suite,
        "generated_tests": generated_suite,
        "combined_tests": None,
        "overall_result": overall_result,
        "attempted_commands": attempted_commands,
        "suites": [existing_suite, generated_suite],
        "error": error,
    }


def upload_execution_artifacts(*, run, output_dir: str, results_path: Path, logs_dir: Path, junit_dir: Path) -> list[dict]:
    artifacts: list[dict] = []
    files_to_upload = [
        ("execution_results", results_path, "application/json"),
        *[
            ("execution_log", path, "text/plain")
            for path in sorted(logs_dir.glob("*.log"))
        ],
        *[
            ("execution_junit", path, "application/xml")
            for path in sorted(junit_dir.glob("*.xml"))
        ],
    ]
    for artifact_type, source, content_type in files_to_upload:
        relative_path = _relative_output_path(source)
        object_key = f"{run.workspace_id}/{run.project_id}/{run.id}/{relative_path}"
        upload_file_to_storage(
            bucket=settings.supabase_storage_bucket,
            object_key=object_key,
            source=source,
            content_type=content_type,
        )
        artifacts.append(
            {
                "artifact_type": artifact_type,
                "bucket": settings.supabase_storage_bucket,
                "key": object_key,
                "path": relative_path,
            }
        )
    return artifacts


def _relative_output_path(path: Path) -> str:
    parts = path.parts
    execute_index = parts.index(settings.execute_tests_output_dir)
    return Path(*parts[execute_index:]).as_posix()


def build_executor_request(*, run, config: ExecuteTestsConfig, workspace_dir: Path, execution_plan: ExecutionPlan, include_generated_suite: bool) -> dict:
    existing_junit = f"{config.workspace_root}/out/{config.output_dir}/junit/existing-tests.xml"
    generated_junit = f"{config.workspace_root}/out/{config.output_dir}/junit/generated-tests.xml"
    return {
        "run_id": run.id,
        "workspace_id": run.workspace_id,
        "workspace_path": str(workspace_dir.resolve()),
        "image": config.image,
        "install_timeout_seconds": config.install_timeout_seconds,
        "suite_timeout_seconds": execution_plan.suite_timeout_seconds,
        "limits": {
            "cpus": config.cpus,
            "memory_mb": config.memory_mb,
            "pids": config.pids,
            "tmpfs_mb": config.tmpfs_mb,
        },
        "commands": {
            "bootstrap": [["python", "-m", "venv", f"{config.workspace_root}/out/venv"]],
            "install": [selection.command for selection in execution_plan.install_commands],
            "existing_suite": [*execution_plan.existing_test_command.command, f"--junitxml={existing_junit}"],
            "generated_suite": [*execution_plan.generated_test_command.command, f"--junitxml={generated_junit}"] if include_generated_suite else None,
        },
    }


def build_install_results(executor_steps: list[dict], commands: list[CommandSelection]) -> list[dict]:
    return run_install_commands(executor_steps, commands)


def command_result_from_payload(payload: dict) -> CommandResult:
    return CommandResult(
        command=[str(item) for item in payload.get("command", [])],
        exit_code=int(payload.get("exit_code", 1) if payload.get("exit_code") is not None else 1),
        stdout=str(payload.get("stdout", "")),
        stderr=str(payload.get("stderr", "")),
        duration_seconds=float(payload.get("duration_seconds", 0.0)),
    )


def build_job_output_json(*, execution_plan: ExecutionPlan, results_payload: dict, uploaded_artifacts: list[dict]) -> dict:
    return {
        "framework": execution_plan.framework,
        "python_version": results_payload["environment"]["python_version"],
        "environment": results_payload["environment"],
        "isolation": results_payload["isolation"],
        "install": results_payload["install"],
        "existing_tests": results_payload["existing_tests"],
        "generated_tests": results_payload["generated_tests"],
        "combined_tests": None,
        "overall_result": results_payload["overall_result"],
        "execution_plan": results_payload["execution_plan"],
        "attempted_commands": results_payload["attempted_commands"],
        "artifacts": _build_artifact_path_index(uploaded_artifacts),
        "error": results_payload.get("error"),
    }


def write_environment_setup_log(log_path: Path, execution_result: ExecutorExecutionResult) -> None:
    error = execution_result.error or {}
    payload = [
        f"error_type: {error.get('type', 'environment_setup_failed')}",
        f"message: {error.get('message', 'Execution environment setup failed')}",
        "",
        "install_steps:",
        json.dumps(execution_result.steps.get("install", []), indent=2),
    ]
    log_path.write_text("\n".join(payload).strip() + "\n", encoding="utf-8")


def enqueue_analyze_job(session, run_id: str) -> None:
    analyze = get_job_by_stage(session, run_id, "analyze")
    if analyze is None:
        raise RuntimeError("Analyze job not found")
    rq_job = get_queue("analyze").enqueue("worker.app.jobs.analyze_job", run_id, analyze.id)
    set_job_rq_id(session, analyze.id, rq_job.id)


def _build_artifact_path_index(artifacts: list[dict]) -> dict[str, str]:
    index: dict[str, str] = {}
    seen: dict[str, int] = {}
    for artifact in artifacts:
        artifact_type = artifact.get("artifact_type")
        path = artifact.get("path")
        if not isinstance(artifact_type, str) or not isinstance(path, str):
            continue
        count = seen.get(artifact_type, 0)
        seen[artifact_type] = count + 1
        key = artifact_type if count == 0 else f"{artifact_type}_{count + 1}"
        index[key] = path
    return index
