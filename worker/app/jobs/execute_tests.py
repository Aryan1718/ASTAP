import ast
import json
import logging
import socket
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
from worker.app.providers.openai_provider import OpenAIGenerateTestsProvider

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
    generated_collect_command: CommandSelection
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
        request_timeout_seconds = _executor_request_timeout_seconds(payload)
        try:
            with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:  # noqa: S310
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Executor API request failed with status {exc.code}: {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeError(f"Executor API request timed out after {request_timeout_seconds} seconds") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Executor API request failed: {exc.reason}") from exc

        return ExecutorExecutionResult(
            python_version=str(response_payload.get("python_version", "unknown")),
            platform_system=str(response_payload.get("platform_system", "unknown")),
            isolation=response_payload.get("isolation", {}),
            steps=response_payload.get("steps", {}),
            error=response_payload.get("error"),
        )


def _executor_request_timeout_seconds(payload: dict) -> int:
    commands = payload.get("commands") if isinstance(payload, dict) else {}
    if not isinstance(commands, dict):
        commands = {}

    install_timeout_seconds = _positive_int(payload.get("install_timeout_seconds"), default=300)
    suite_timeout_seconds = _positive_int(payload.get("suite_timeout_seconds"), default=600)

    bootstrap_commands = commands.get("bootstrap")
    install_commands = commands.get("install")
    existing_suite = commands.get("existing_suite")
    generated_collect = commands.get("generated_collect")
    generated_suite = commands.get("generated_suite")

    install_step_count = len(bootstrap_commands) if isinstance(bootstrap_commands, list) else 0
    install_step_count += len(install_commands) if isinstance(install_commands, list) else 0
    suite_step_count = int(existing_suite is not None) + int(generated_collect is not None) + int(generated_suite is not None)

    step_budget = (install_timeout_seconds * install_step_count) + (suite_timeout_seconds * suite_step_count)
    return max(step_budget + 30, 30)


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


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
        attempts_dir = out_root / "generated_test_attempts"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        junit_dir.mkdir(parents=True, exist_ok=True)
        attempts_dir.mkdir(parents=True, exist_ok=True)

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
        manifest_entries_by_path = {
            entry.generated_test_file: entry
            for entry in manifest.files
            if entry.generated_test_file
        }

        execution_plan = detect_execution_plan(
            repo_path=repo_path,
            run_config=getattr(run, "run_config", {}) or {},
            config=config,
        )

        executor = ExecutorClient(base_url=config.executor_base_url)
        preflight_result = executor.execute(
            build_executor_request(
                run=run,
                config=config,
                workspace_dir=workspace_dir,
                execution_plan=execution_plan,
                include_environment_setup=True,
                include_generated_collect=bool(materialized_generated_files),
                generated_collect_targets=None,
                generated_suite_targets=None,
            )
        )

        install_results = build_install_results(preflight_result.steps.get("install", []), execution_plan.install_commands)
        existing_suite = run_existing_tests_suite(
            junit_dir=junit_dir,
            logs_dir=logs_dir,
            command_selection=execution_plan.existing_test_command,
            result_payload=preflight_result.steps.get("existing_suite"),
        )
        generated_collection = run_generated_tests_collection(
            generated_files=materialized_generated_files,
            logs_dir=logs_dir,
            collect_command_selection=execution_plan.generated_collect_command,
            result_payload=preflight_result.steps.get("generated_collect"),
        )

        repair_summary = build_empty_repair_summary(logs_dir=logs_dir)
        generated_collection_retry_error = None
        if (
            materialized_generated_files
            and generated_collection["status"] != "error"
            and generated_collection["files_collected"] < len(materialized_generated_files)
            and config.generated_tests_max_repair_passes > 0
        ):
            repair_summary = repair_generated_collection_failures(
                manifest_entries_by_path=manifest_entries_by_path,
                collection_summary=generated_collection,
                generated_tests_root=generated_tests_root,
                attempts_dir=attempts_dir,
            )
            if repair_summary["repair_targets"]:
                retry_result = executor.execute(
                    build_executor_request(
                        run=run,
                        config=config,
                        workspace_dir=workspace_dir,
                        execution_plan=execution_plan,
                        include_environment_setup=False,
                        include_generated_collect=True,
                        generated_collect_targets=repair_summary["repair_targets"],
                        generated_suite_targets=None,
                    )
                )
                generated_collection_retry_error = retry_result.error
                retry_collection = run_generated_tests_collection(
                    generated_files=repair_summary["repaired_workspace_paths"],
                    logs_dir=logs_dir,
                    collect_command_selection=execution_plan.generated_collect_command,
                    result_payload=retry_result.steps.get("generated_collect"),
                    log_name="generated-collect-repair.log",
                )
                repair_summary["log_path"] = retry_collection["log_path"]
                generated_collection = merge_collection_summaries(
                    initial_summary=generated_collection,
                    retry_summary=retry_collection,
                    repair_summary=repair_summary,
                )

        generated_execution_payload = None
        generated_execution_python_version = preflight_result.python_version
        generated_execution_platform_system = preflight_result.platform_system
        generated_execution_isolation = preflight_result.isolation
        generated_execution_error = preflight_result.error
        execution_error_result = preflight_result
        if (
            preflight_result.error is None
            and generated_collection_retry_error is None
            and generated_collection["status"] not in {"skipped", "error"}
            and generated_collection["files_collected"] > 0
        ):
            generated_targets = [
                pytest_path
                for path, file_result in generated_collection["file_results_by_path"].items()
                for pytest_path in [_pytest_generated_test_path_from_manifest(path)]
                if pytest_path is not None
                if file_result["status"] in {"collected", "passed", "failed", "error", "skipped", "executed"}
            ]
            generated_execution_result = executor.execute(
                build_executor_request(
                    run=run,
                    config=config,
                    workspace_dir=workspace_dir,
                    execution_plan=execution_plan,
                    include_environment_setup=False,
                    include_generated_collect=False,
                    generated_collect_targets=None,
                    generated_suite_targets=generated_targets,
                )
            )
            generated_execution_payload = generated_execution_result.steps.get("generated_suite")
            generated_execution_python_version = generated_execution_result.python_version
            generated_execution_platform_system = generated_execution_result.platform_system
            generated_execution_isolation = generated_execution_result.isolation
            generated_execution_error = generated_execution_result.error
            execution_error_result = generated_execution_result
        elif generated_collection_retry_error is not None:
            generated_execution_error = generated_collection_retry_error
            execution_error_result = retry_result

        generated_suite = run_generated_tests_suite(
            generated_files=materialized_generated_files,
            junit_dir=junit_dir,
            logs_dir=logs_dir,
            collect_command_selection=execution_plan.generated_collect_command,
            suite_command_selection=execution_plan.generated_test_command,
            collection_summary=generated_collection,
            result_payload=generated_execution_payload,
            config=config,
            repair_summary=repair_summary,
        )

        results_payload = build_results_payload(
            run_id=run.id,
            config=config,
            execution_plan=execution_plan,
            python_version=generated_execution_python_version,
            platform_system=generated_execution_platform_system,
            isolation=generated_execution_isolation,
            install_results=install_results,
            existing_suite=existing_suite,
            generated_suite=generated_suite,
            error=generated_execution_error,
        )
        results_path = out_root / "results.json"
        results_path.write_text(json.dumps(results_payload, indent=2), encoding="utf-8")
        if generated_execution_error is not None:
            write_environment_setup_log(logs_dir / "environment-setup.log", execution_error_result)

        uploaded_artifacts = upload_execution_artifacts(
            run=run,
            output_dir=config.output_dir,
            results_path=results_path,
            logs_dir=logs_dir,
            junit_dir=junit_dir,
            attempts_dir=attempts_dir,
        )
        output_json = build_job_output_json(
            execution_plan=execution_plan,
            results_payload=results_payload,
            uploaded_artifacts=uploaded_artifacts,
        )
        if generated_execution_error is not None:
            error_type = generated_execution_error.get("type", "environment_setup_failed")
            error_message = generated_execution_error.get("message", "Execution environment setup failed")
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
    generated_collect_command = build_generated_collect_command()
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
        generated_collect_command = build_generated_collect_command(override_generated_command, source="run_config.generated_test_command")
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
        generated_collect_command=generated_collect_command,
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


def build_generated_collect_command(command: list[str] | None = None, *, source: str = "platform_default.generated_pytest") -> CommandSelection:
    base_command = command or ["python", "-m", "pytest", ".astap/generated_tests"]
    return CommandSelection(
        command=[*build_generated_pytest_command(base_command, targets=[".astap/generated_tests"]), "--collect-only", "--continue-on-collection-errors", "-q"],
        source=source,
    )


def build_generated_test_command() -> CommandSelection:
    return CommandSelection(
        command=["python", "-m", "pytest", ".astap/generated_tests"],
        source="platform_default.generated_pytest",
    )


def build_generated_pytest_command(command: list[str], *, targets: list[str]) -> list[str]:
    if len(command) >= 3 and command[:3] == ["python", "-m", "pytest"]:
        passthrough_args = [
            arg for arg in command[3:]
            if arg != ".astap/generated_tests" and not arg.startswith("--junitxml=")
        ]
        return ["python", "-m", "pytest", *targets, *passthrough_args]
    return command


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
    collect_command_selection: CommandSelection,
    suite_command_selection: CommandSelection,
    collection_summary: dict,
    result_payload: dict | None,
    config: ExecuteTestsConfig,
    repair_summary: dict,
) -> dict:
    junit_path = junit_dir / "generated-tests.xml"
    log_path = logs_dir / "generated-tests.log"
    if not generated_files:
        return _empty_generated_suite_summary(
            log_path=log_path,
            collect_command_selection=collect_command_selection,
            suite_command_selection=suite_command_selection,
        )

    if collection_summary["status"] == "error":
        return _generated_suite_summary_from_collection_only(
            collection_summary=collection_summary,
            log_path=log_path,
            suite_command_selection=suite_command_selection,
            quality_status="unrunnable",
            quality_failure_reason="environment_setup_failed_before_generated_collection",
            suite_status="error",
            repair_summary=repair_summary,
        )

    if collection_summary["files_collected"] == 0:
        return _generated_suite_summary_from_collection_only(
            collection_summary=collection_summary,
            log_path=log_path,
            suite_command_selection=suite_command_selection,
            quality_status="unrunnable",
            quality_failure_reason="no_generated_tests_collected",
            suite_status="skipped",
            repair_summary=repair_summary,
        )

    if result_payload is None:
        return _generated_suite_summary_from_collection_only(
            collection_summary=collection_summary,
            log_path=log_path,
            suite_command_selection=suite_command_selection,
            quality_status="quality_failed",
            quality_failure_reason="generated_execution_not_started",
            suite_status="error",
            repair_summary=repair_summary,
        )

    result = command_result_from_payload(result_payload)
    write_suite_log(log_path, result)
    execution_counts = parse_junit_counts(junit_path)
    file_results = _merge_generated_file_execution_results(
        collection_summary["file_results_by_path"],
        _parse_generated_junit_file_results(junit_path),
    )
    suite_status = "passed" if result.exit_code == 0 else "failed"
    if execution_counts is None:
        suite_status = "error" if result.exit_code != 0 else "passed"
        execution_counts = {"collected": 0, "failed": 0, "errors": 0, "skipped": 0, "passed": 0}

    quality_status, quality_failure_reason = _generated_quality_status(
        generated_count=len(generated_files),
        collected_count=collection_summary["files_collected"],
        executed_count=_count_executed_files(file_results),
        config=config,
    )
    if quality_status == "quality_failed" and suite_status == "passed":
        suite_status = "failed"

    return {
        "suite_key": "generated",
        "status": suite_status,
        "command": result.command,
        "command_source": suite_command_selection.source,
        "exit_code": result.exit_code,
        "collected": execution_counts["collected"],
        "passed": execution_counts["passed"],
        "failed": execution_counts["failed"],
        "errors": execution_counts["errors"],
        "skipped": execution_counts["skipped"],
        "duration_seconds": result.duration_seconds,
        "log_path": _relative_output_path(log_path),
        "junit_path": _relative_output_path(junit_path) if junit_path.exists() else None,
        "quality_status": quality_status,
        "quality_failure_reason": quality_failure_reason,
        "files_generated": len(generated_files),
        "files_collected": collection_summary["files_collected"],
        "files_executed": _count_executed_files(file_results),
        "collection_failed_files": len(generated_files) - collection_summary["files_collected"],
        "collection_coverage_ratio": round(collection_summary["collection_coverage_ratio"], 3),
        "collected_test_count": collection_summary["collected_test_count"],
        "executed_test_count": execution_counts["collected"],
        "collect_command": collection_summary["command"],
        "collect_command_source": collection_summary["command_source"],
        "collect_exit_code": collection_summary["exit_code"],
        "collect_log_path": collection_summary["log_path"],
        "repair_passes_run": repair_summary["repair_passes_run"],
        "files_repaired": repair_summary["files_repaired"],
        "files_repaired_and_collected": repair_summary["files_repaired_and_collected"],
        "repair_log_path": repair_summary["log_path"],
        "file_results": list(file_results.values()),
    }


def run_generated_tests_collection(
    *,
    generated_files: list[Path],
    logs_dir: Path,
    collect_command_selection: CommandSelection,
    result_payload: dict | None,
    log_name: str = "generated-collect.log",
) -> dict:
    log_path = logs_dir / log_name
    file_results_by_path = {
        _manifest_generated_test_path(path): {
            "path": _manifest_generated_test_path(path),
            "status": "generated",
            "attempt_count": 1,
            "final_attempt": 1,
            "repair_status": None,
            "collection_error_excerpt": None,
            "repaired_from_path": None,
            "initial_attempt_artifact_path": None,
            "final_attempt_artifact_path": None,
            "collected_test_count": 0,
            "executed_test_count": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "message": None,
        }
        for path in generated_files
    }
    if not generated_files:
        log_path.write_text("No generated tests were materialized for this run.\n", encoding="utf-8")
        return {
            "suite_key": "generated",
            "status": "skipped",
            "command": None,
            "command_source": collect_command_selection.source,
            "exit_code": None,
            "files_collected": 0,
            "collection_coverage_ratio": 0.0,
            "collected_test_count": 0,
            "log_path": _relative_output_path(log_path),
            "file_results_by_path": file_results_by_path,
        }

    if result_payload is None:
        log_path.write_text("Generated collection did not execute because environment setup failed.\n", encoding="utf-8")
        for file_result in file_results_by_path.values():
            file_result["status"] = "collection_failed"
            file_result["message"] = "Environment setup failed before generated collection could run."
            file_result["collection_error_excerpt"] = file_result["message"]
        return {
            "suite_key": "generated",
            "status": "error",
            "command": None,
            "command_source": collect_command_selection.source,
            "exit_code": None,
            "files_collected": 0,
            "collection_coverage_ratio": 0.0,
            "collected_test_count": 0,
            "log_path": _relative_output_path(log_path),
            "file_results_by_path": file_results_by_path,
        }

    result = command_result_from_payload(result_payload)
    write_suite_log(log_path, result)
    collected_test_counts = _parse_generated_collect_output(result.stdout, result.stderr)
    for path, count in collected_test_counts.items():
        file_result = file_results_by_path.get(path)
        if file_result is None:
            continue
        file_result["status"] = "collected"
        file_result["collected_test_count"] = count

    collection_failure_message = _extract_collection_failure_message(result.stdout, result.stderr)
    for file_result in file_results_by_path.values():
        if file_result["status"] != "collected":
            file_result["status"] = "collection_failed"
            file_result["message"] = collection_failure_message
            file_result["collection_error_excerpt"] = collection_failure_message

    files_collected = len([item for item in file_results_by_path.values() if item["status"] == "collected"])
    return {
        "suite_key": "generated",
        "status": "passed" if result.exit_code == 0 else "failed",
        "command": result.command,
        "command_source": collect_command_selection.source,
        "exit_code": result.exit_code,
        "files_collected": files_collected,
        "collection_coverage_ratio": files_collected / len(generated_files) if generated_files else 0.0,
        "collected_test_count": sum(item["collected_test_count"] for item in file_results_by_path.values()),
        "log_path": _relative_output_path(log_path),
        "file_results_by_path": file_results_by_path,
    }


def build_empty_repair_summary(*, logs_dir: Path) -> dict:
    return {
        "repair_passes_run": 0,
        "files_repaired": 0,
        "files_repaired_and_collected": 0,
        "repair_targets": [],
        "repaired_workspace_paths": [],
        "log_path": _relative_output_path(logs_dir / "generated-repair.log"),
    }


def repair_generated_collection_failures(
    *,
    manifest_entries_by_path: dict[str, object],
    collection_summary: dict,
    generated_tests_root: Path,
    attempts_dir: Path,
) -> dict:
    log_path = attempts_dir.parent / "logs" / "generated-repair.log"
    repairs: list[str] = []
    repaired_workspace_paths: list[Path] = []
    provider = _repair_provider()
    if provider is None:
        log_path.write_text("Skipping generated test repair because OPENAI_API_KEY is unavailable.\n", encoding="utf-8")
        for file_result in collection_summary["file_results_by_path"].values():
            if file_result["status"] == "collection_failed":
                file_result["repair_status"] = "skipped_no_provider"
        return {
            "repair_passes_run": 0,
            "files_repaired": 0,
            "files_repaired_and_collected": 0,
            "repair_targets": [],
            "repaired_workspace_paths": [],
            "log_path": _relative_output_path(log_path),
        }

    for manifest_path, file_result in collection_summary["file_results_by_path"].items():
        if file_result["status"] != "collection_failed":
            continue
        manifest_entry = manifest_entries_by_path.get(manifest_path)
        if manifest_entry is None:
            continue
        workspace_path = generated_tests_root / _generated_test_relative_output_path(manifest_path)
        if not workspace_path.exists():
            continue

        original_code = workspace_path.read_text(encoding="utf-8")
        attempt_one_path = attempts_dir / "attempt_1" / _generated_test_relative_output_path(manifest_path)
        attempt_two_path = attempts_dir / "attempt_2" / _generated_test_relative_output_path(manifest_path)
        attempt_one_path.parent.mkdir(parents=True, exist_ok=True)
        attempt_two_path.parent.mkdir(parents=True, exist_ok=True)
        attempt_one_path.write_text(original_code, encoding="utf-8")
        file_result["initial_attempt_artifact_path"] = _relative_output_path(attempt_one_path)

        try:
            repaired_code = provider.repair_collection_failure(
                generated_test_path=manifest_path,
                generated_test_code=original_code,
                error_message=str(file_result.get("message") or "pytest collection failed"),
                target_key=manifest_entry.target_key,
                target_type=manifest_entry.target_type,
                symbol=manifest_entry.symbol,
                source_file=manifest_entry.source_file,
                generation_mode=manifest_entry.generation_mode,
                recipe_id=manifest_entry.recipe_id,
                recipe_name=manifest_entry.recipe_name,
            ).strip()
            _validate_repaired_test_code(repaired_code)
        except Exception as exc:  # noqa: BLE001
            file_result["repair_status"] = "repair_failed"
            file_result["message"] = f"{file_result.get('message') or 'pytest collection failed'} | repair failed: {exc}"
            repairs.append(f"{manifest_path}: repair failed: {exc}")
            continue

        attempt_two_path.write_text(repaired_code + "\n", encoding="utf-8")
        workspace_path.write_text(repaired_code + "\n", encoding="utf-8")
        repaired_workspace_paths.append(workspace_path)
        repair_target = _pytest_generated_test_path_from_manifest(manifest_path)
        if repair_target is None:
            continue
        file_result["attempt_count"] = 2
        file_result["final_attempt"] = 2
        file_result["repair_status"] = "repaired"
        file_result["repaired_from_path"] = manifest_path
        file_result["final_attempt_artifact_path"] = _relative_output_path(attempt_two_path)
        repairs.append(f"{manifest_path}: repaired after collection failure")
        repairs.append(f"  original: {_relative_output_path(attempt_one_path)}")
        repairs.append(f"  repaired: {_relative_output_path(attempt_two_path)}")

    if not repairs:
        log_path.write_text("No generated files were eligible for collection-failure repair.\n", encoding="utf-8")
        return {
            "repair_passes_run": 0,
            "files_repaired": 0,
            "files_repaired_and_collected": 0,
            "repair_targets": [],
            "repaired_workspace_paths": [],
            "log_path": _relative_output_path(log_path),
        }

    deduped_workspace_paths = list(dict.fromkeys(repaired_workspace_paths))
    repair_targets = [
        _pytest_generated_test_path_from_manifest(file_result["path"])
        for file_result in collection_summary["file_results_by_path"].values()
        if file_result.get("repair_status") == "repaired"
    ]
    log_path.write_text("\n".join(repairs).strip() + "\n", encoding="utf-8")
    return {
        "repair_passes_run": 1,
        "files_repaired": len(repair_targets),
        "files_repaired_and_collected": 0,
        "repair_targets": [target for target in repair_targets if target],
        "repaired_workspace_paths": deduped_workspace_paths,
        "log_path": _relative_output_path(log_path),
    }


def merge_collection_summaries(*, initial_summary: dict, retry_summary: dict, repair_summary: dict) -> dict:
    merged = dict(initial_summary)
    merged_file_results: dict[str, dict] = {
        path: dict(result)
        for path, result in initial_summary["file_results_by_path"].items()
    }
    repaired_and_collected = 0
    for path, retry_result in retry_summary["file_results_by_path"].items():
        existing = merged_file_results.get(path)
        if existing is None:
            merged_file_results[path] = dict(retry_result)
            continue
        existing["attempt_count"] = max(existing.get("attempt_count", 1), retry_result.get("attempt_count", 1), 2)
        existing["final_attempt"] = max(existing.get("final_attempt", 1), 2)
        if existing.get("repair_status") == "repaired" and retry_result["status"] == "collected":
            existing["status"] = "collected"
            existing["collected_test_count"] = retry_result["collected_test_count"]
            existing["message"] = None
            existing["collection_error_excerpt"] = None
            repaired_and_collected += 1
        elif existing.get("repair_status") == "repaired":
            existing["status"] = "collection_failed_after_repair"
            existing["message"] = retry_result.get("message") or existing.get("message")
            existing["collection_error_excerpt"] = retry_result.get("collection_error_excerpt") or existing.get("collection_error_excerpt")

    merged["file_results_by_path"] = merged_file_results
    if retry_summary["status"] == "error":
        merged["status"] = "error"
    elif any(result["status"] in {"collection_failed", "collection_failed_after_repair"} for result in merged_file_results.values()):
        merged["status"] = "failed"
    else:
        merged["status"] = "passed"
    merged["command"] = retry_summary["command"] or initial_summary["command"]
    merged["command_source"] = retry_summary["command_source"] or initial_summary["command_source"]
    merged["exit_code"] = retry_summary["exit_code"] if retry_summary["exit_code"] is not None else initial_summary["exit_code"]
    merged["files_collected"] = len(
        [item for item in merged_file_results.values() if item["status"] == "collected"]
    )
    merged["collection_coverage_ratio"] = (
        merged["files_collected"] / len(merged_file_results) if merged_file_results else 0.0
    )
    merged["collected_test_count"] = sum(item["collected_test_count"] for item in merged_file_results.values())
    merged["log_path"] = retry_summary["log_path"]
    repair_summary["files_repaired_and_collected"] = repaired_and_collected
    return merged


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


def _empty_generated_suite_summary(*, log_path: Path, collect_command_selection: CommandSelection, suite_command_selection: CommandSelection) -> dict:
    log_path.write_text("No generated tests were materialized for this run.\n", encoding="utf-8")
    return {
        "suite_key": "generated",
        "status": "skipped",
        "command": None,
        "command_source": suite_command_selection.source,
        "exit_code": None,
        "collected": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 0.0,
        "log_path": _relative_output_path(log_path),
        "junit_path": None,
        "quality_status": "skipped",
        "quality_failure_reason": None,
        "files_generated": 0,
        "files_collected": 0,
        "files_executed": 0,
        "collection_failed_files": 0,
        "collection_coverage_ratio": 0.0,
        "collected_test_count": 0,
        "executed_test_count": 0,
        "collect_command": None,
        "collect_command_source": collect_command_selection.source,
        "collect_exit_code": None,
        "collect_log_path": None,
        "repair_passes_run": 0,
        "files_repaired": 0,
        "files_repaired_and_collected": 0,
        "repair_log_path": None,
        "file_results": [],
    }


def _generated_suite_summary_from_collection_only(
    *,
    collection_summary: dict,
    log_path: Path,
    suite_command_selection: CommandSelection,
    quality_status: str,
    quality_failure_reason: str | None,
    suite_status: str,
    repair_summary: dict,
) -> dict:
    log_path.write_text("Generated suite execution was skipped after collection preflight.\n", encoding="utf-8")
    file_results = list(collection_summary["file_results_by_path"].values())
    return {
        "suite_key": "generated",
        "status": suite_status,
        "command": None,
        "command_source": suite_command_selection.source,
        "exit_code": None,
        "collected": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 0.0,
        "log_path": _relative_output_path(log_path),
        "junit_path": None,
        "quality_status": quality_status,
        "quality_failure_reason": quality_failure_reason,
        "files_generated": len(file_results),
        "files_collected": collection_summary["files_collected"],
        "files_executed": 0,
        "collection_failed_files": len(file_results) - collection_summary["files_collected"],
        "collection_coverage_ratio": round(collection_summary["collection_coverage_ratio"], 3),
        "collected_test_count": collection_summary["collected_test_count"],
        "executed_test_count": 0,
        "collect_command": collection_summary["command"],
        "collect_command_source": collection_summary["command_source"],
        "collect_exit_code": collection_summary["exit_code"],
        "collect_log_path": collection_summary["log_path"],
        "repair_passes_run": repair_summary["repair_passes_run"],
        "files_repaired": repair_summary["files_repaired"],
        "files_repaired_and_collected": repair_summary["files_repaired_and_collected"],
        "repair_log_path": repair_summary["log_path"],
        "file_results": file_results,
    }


def _generated_quality_status(*, generated_count: int, collected_count: int, executed_count: int, config: ExecuteTestsConfig) -> tuple[str, str | None]:
    if generated_count == 0:
        return "skipped", None
    if collected_count == 0 and config.generated_tests_fail_if_zero_collected:
        return "unrunnable", "no_generated_tests_collected"
    if executed_count < config.generated_tests_min_executed_files:
        return "quality_failed", "generated_execution_coverage_below_threshold"

    collection_ratio = collected_count / generated_count if generated_count else 0.0
    if collection_ratio < config.generated_tests_min_collection_ratio:
        return "quality_failed", "generated_collection_coverage_below_threshold"
    if collected_count < generated_count:
        return "partially_runnable", "some_generated_tests_failed_collection"
    return "runnable", None


def _parse_generated_collect_output(stdout: str, stderr: str) -> dict[str, int]:
    collected: dict[str, int] = {}
    for raw_line in f"{stdout}\n{stderr}".splitlines():
        line = raw_line.strip()
        if not line or "::" not in line:
            continue
        path_part = line.split("::", 1)[0].strip()
        manifest_path = _manifest_path_from_pytest_path(path_part)
        if manifest_path is None:
            continue
        collected[manifest_path] = collected.get(manifest_path, 0) + 1
    return collected


def _extract_collection_failure_message(stdout: str, stderr: str) -> str:
    combined = "\n".join(part for part in [stderr.strip(), stdout.strip()] if part).strip()
    if not combined:
        return "pytest collection failed before generated tests could run."
    for line in combined.splitlines():
        stripped = line.strip()
        if stripped and ("error" in stripped.lower() or "failed" in stripped.lower()):
            return stripped[:300]
    return combined.splitlines()[0][:300]


def _manifest_path_from_pytest_path(path_value: str) -> str | None:
    normalized = path_value.strip()
    if normalized.startswith(".astap/generated_tests/"):
        return f"{settings.generate_tests_output_dir}/{normalized.removeprefix('.astap/generated_tests/')}"
    if normalized.startswith(f"{settings.generate_tests_output_dir}/"):
        return normalized
    return None


def _pytest_generated_test_path_from_manifest(manifest_path: str) -> str | None:
    if not manifest_path.startswith(f"{settings.generate_tests_output_dir}/"):
        return None
    return f".astap/generated_tests/{manifest_path.removeprefix(f'{settings.generate_tests_output_dir}/')}"


def _manifest_generated_test_path(path: Path) -> str:
    return f"{settings.generate_tests_output_dir}/{path.relative_to(path.parents[1]).as_posix()}"


def _repair_provider() -> OpenAIGenerateTestsProvider | None:
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        return None
    return OpenAIGenerateTestsProvider(api_key=api_key, config=settings.generate_tests_config())


def _validate_repaired_test_code(content: str) -> None:
    ast.parse(content)


def _parse_generated_junit_file_results(junit_path: Path) -> dict[str, dict]:
    if not junit_path.exists():
        return {}

    root = ET.fromstring(junit_path.read_text(encoding="utf-8"))
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    results: dict[str, dict] = {}
    for suite in suites:
        for testcase in suite.findall("testcase"):
            manifest_path = _manifest_path_from_pytest_path(testcase.attrib.get("file", ""))
            if manifest_path is None:
                continue
            file_result = results.setdefault(
                manifest_path,
                {
                    "path": manifest_path,
                    "status": "executed",
                    "collected_test_count": 0,
                    "executed_test_count": 0,
                    "passed": 0,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 0,
                    "message": None,
                },
            )
            file_result["executed_test_count"] += 1
            failure_node = testcase.find("failure")
            error_node = testcase.find("error")
            skipped_node = testcase.find("skipped")
            if failure_node is not None:
                file_result["failed"] += 1
                file_result["status"] = "failed"
                file_result["message"] = (failure_node.attrib.get("message") or (failure_node.text or "").strip() or None)
            elif error_node is not None:
                file_result["errors"] += 1
                file_result["status"] = "error"
                file_result["message"] = (error_node.attrib.get("message") or (error_node.text or "").strip() or None)
            elif skipped_node is not None:
                file_result["skipped"] += 1
                if file_result["status"] == "executed":
                    file_result["status"] = "skipped"
            else:
                file_result["passed"] += 1
                if file_result["status"] == "executed":
                    file_result["status"] = "passed"
    return results


def _merge_generated_file_execution_results(collection_results: dict[str, dict], junit_results: dict[str, dict]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for path, file_result in collection_results.items():
        merged[path] = dict(file_result)
        junit_result = junit_results.get(path)
        if junit_result is None:
            continue
        merged[path].update(junit_result)
        merged[path]["collected_test_count"] = max(merged[path]["collected_test_count"], junit_result["executed_test_count"])
    return merged


def _count_executed_files(file_results: dict[str, dict]) -> int:
    return len([result for result in file_results.values() if result["status"] in {"passed", "failed", "error", "skipped", "executed"}])


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
    offline_install = isolation.get("network_mode") == "none" if isinstance(isolation, dict) else False
    if error is not None:
        overall_result = error.get("type", "environment_setup_failed")
    elif generated_suite.get("quality_status") in {"unrunnable", "quality_failed"}:
        overall_result = "generated_tests_quality_failed"
    elif generated_suite.get("quality_status") == "partially_runnable":
        overall_result = "completed_with_failures"
    elif existing_suite["status"] != "passed" or generated_suite["status"] not in {"passed", "skipped"}:
        overall_result = "completed_with_failures"
    attempted_commands = [entry["command"] for entry in install_results]
    if existing_suite["command"] is not None:
        attempted_commands.append(existing_suite["command"])
    if generated_suite.get("collect_command") is not None:
        attempted_commands.append(generated_suite["collect_command"])
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
            "generated_collect_command": {
                "command": execution_plan.generated_collect_command.command,
                "source": execution_plan.generated_collect_command.source,
            },
            "generated_test_command": {
                "command": execution_plan.generated_test_command.command,
                "source": execution_plan.generated_test_command.source,
            },
            "suite_timeout_seconds": execution_plan.suite_timeout_seconds,
            "detection_notes": execution_plan.detection_notes,
        },
        "install": {
            "offline": offline_install,
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


def upload_execution_artifacts(*, run, output_dir: str, results_path: Path, logs_dir: Path, junit_dir: Path, attempts_dir: Path) -> list[dict]:
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
        *[
            ("generated_test_attempt_file", path, "text/x-python")
            for path in sorted(attempts_dir.rglob("*.py"))
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


def build_executor_request(
    *,
    run,
    config: ExecuteTestsConfig,
    workspace_dir: Path,
    execution_plan: ExecutionPlan,
    include_environment_setup: bool,
    include_generated_collect: bool,
    generated_collect_targets: list[str] | None,
    generated_suite_targets: list[str] | None,
) -> dict:
    existing_junit = f"{config.workspace_root}/out/{config.output_dir}/junit/existing-tests.xml"
    generated_junit = f"{config.workspace_root}/out/{config.output_dir}/junit/generated-tests.xml"
    generated_suite_command = None
    if generated_suite_targets:
        generated_suite_command = [
            *build_generated_pytest_command(execution_plan.generated_test_command.command, targets=generated_suite_targets),
            f"--junitxml={generated_junit}",
        ]
    generated_collect_command = None
    if include_generated_collect:
        collect_targets = generated_collect_targets or [".astap/generated_tests"]
        generated_collect_command = [
            *build_generated_pytest_command(execution_plan.generated_test_command.command, targets=collect_targets),
            "--collect-only",
            "--continue-on-collection-errors",
            "-q",
        ]
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
            "bootstrap": [["python", "-m", "venv", f"{config.workspace_root}/out/venv"]] if include_environment_setup else [],
            "install": [selection.command for selection in execution_plan.install_commands] if include_environment_setup else [],
            "existing_suite": [*execution_plan.existing_test_command.command, f"--junitxml={existing_junit}"] if include_environment_setup else None,
            "generated_collect": generated_collect_command,
            "generated_suite": generated_suite_command,
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
