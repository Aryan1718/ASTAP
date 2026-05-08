import shutil
import subprocess
import tempfile
from pathlib import Path
from time import monotonic

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    shared_workspace_root: str = Field(default="/executor-workspaces", alias="EXECUTE_TESTS_SHARED_WORKSPACE_ROOT")
    host_workspace_root: str = Field(default="/executor-workspaces", alias="EXECUTE_TESTS_HOST_WORKSPACE_ROOT")
    allowed_image: str = Field(default="astsp-executor:latest", alias="EXECUTOR_ALLOWED_IMAGE")


settings = ExecutorSettings()
app = FastAPI(title="ASTAP Executor")


class ExecutionLimits(BaseModel):
    cpus: float
    memory_mb: int
    pids: int
    tmpfs_mb: int


class ExecutionCommands(BaseModel):
    bootstrap: list[list[str]]
    install: list[list[str]]
    existing_suite: list[str] | None = None
    generated_suite: list[str] | None = None


class ExecutionRequest(BaseModel):
    run_id: str
    workspace_id: str
    workspace_path: str
    image: str
    install_timeout_seconds: int
    suite_timeout_seconds: int
    limits: ExecutionLimits
    commands: ExecutionCommands


class StepResult(BaseModel):
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


class ExecutionResponse(BaseModel):
    python_version: str
    platform_system: str
    isolation: dict
    steps: dict
    error: dict | None = None


class CommandExecutionError(RuntimeError):
    def __init__(self, *, step: str, message: str, result: StepResult | None = None) -> None:
        super().__init__(message)
        self.step = step
        self.result = result


@app.get("/healthz")
def healthz() -> dict[str, object]:
    diagnostics = docker_diagnostics()
    if diagnostics["status"] != "ok":
        raise HTTPException(status_code=503, detail=diagnostics)
    return diagnostics


@app.post("/executions", response_model=ExecutionResponse)
def create_execution(payload: ExecutionRequest) -> ExecutionResponse:
    workspace_path = validate_workspace_path(payload.workspace_path)
    if payload.image != settings.allowed_image:
        raise HTTPException(status_code=400, detail="Execution image is not allowed")
    ensure_executor_runtime_ready()

    container_name = f"astap-exec-{next(tempfile._get_candidate_names())}"
    steps = {
        "bootstrap": [],
        "install": [],
        "existing_suite": None,
        "generated_suite": None,
    }
    try:
        create_container(container_name, workspace_path, payload)
        start_container(container_name)

        for command in payload.commands.bootstrap:
            steps["bootstrap"].append(run_command(container_name, command, payload.install_timeout_seconds))
            if steps["bootstrap"][-1].exit_code != 0:
                raise CommandExecutionError(step="bootstrap", message="Bootstrap command failed", result=steps["bootstrap"][-1])

        python_version_result = run_command(
            container_name,
            ["/workspace/out/venv/bin/python", "--version"],
            payload.install_timeout_seconds,
        )
        python_version = (python_version_result.stdout or python_version_result.stderr).strip() or "unknown"
        platform_system_result = run_command(
            container_name,
            ["python", "-c", "import platform; print(platform.system())"],
            payload.install_timeout_seconds,
        )
        platform_system = (platform_system_result.stdout or platform_system_result.stderr).strip() or "unknown"

        for command in payload.commands.install:
            rewritten = rewrite_python_command(command)
            result = run_command(container_name, rewritten, payload.install_timeout_seconds)
            steps["install"].append(result)
            if result.exit_code != 0:
                return build_response(
                    python_version=python_version,
                    platform_system=platform_system,
                    limits=payload.limits,
                    steps=steps,
                    error={"type": "environment_setup_failed", "message": f"Dependency install failed: {' '.join(rewritten)}"},
                )

        if payload.commands.existing_suite is not None:
            steps["existing_suite"] = run_command(
                container_name,
                rewrite_python_command(payload.commands.existing_suite),
                payload.suite_timeout_seconds,
            )

        if payload.commands.generated_suite is not None:
            steps["generated_suite"] = run_command(
                container_name,
                rewrite_python_command(payload.commands.generated_suite),
                payload.suite_timeout_seconds,
            )

        return build_response(
            python_version=python_version,
            platform_system=platform_system,
            limits=payload.limits,
            steps=steps,
            error=None,
        )
    except CommandExecutionError as exc:
        return build_response(
            python_version="unknown",
            platform_system="unknown",
            limits=payload.limits,
            steps=steps,
            error={"type": f"{exc.step}_failed", "message": str(exc)},
        )
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.stderr.strip() or exc.stdout.strip() or str(exc)) from exc
    finally:
        remove_container(container_name)


def validate_workspace_path(workspace_path: str) -> Path:
    shared_root = Path(settings.shared_workspace_root).resolve()
    candidate = Path(workspace_path).resolve()
    if candidate != shared_root and shared_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="workspace_path must be inside the shared workspace root")
    return candidate


def docker_diagnostics() -> dict[str, object]:
    docker_path = shutil.which("docker")
    socket_path = Path("/var/run/docker.sock")
    issues: list[str] = []
    if docker_path is None:
        issues.append("docker_cli_missing")
    if not socket_path.exists():
        issues.append("docker_socket_missing")
    elif not socket_path.is_socket():
        issues.append("docker_socket_invalid")

    status = "ok" if not issues else "degraded"
    return {
        "status": status,
        "docker_cli_path": docker_path,
        "docker_socket_path": str(socket_path),
        "issues": issues,
    }


def ensure_executor_runtime_ready() -> None:
    diagnostics = docker_diagnostics()
    if diagnostics["status"] == "ok":
        return

    issue_messages = {
        "docker_cli_missing": "Docker CLI is not installed in the executor container.",
        "docker_socket_missing": "Docker socket is not mounted into the executor container.",
        "docker_socket_invalid": "Docker socket mount is not a Unix socket.",
    }
    message = " ".join(issue_messages[issue] for issue in diagnostics["issues"])
    raise HTTPException(
        status_code=503,
        detail={
            "message": (
                f"{message} Rebuild the executor image and verify the "
                "`/var/run/docker.sock` mount is present."
            ),
            **diagnostics,
        },
    )


def create_container(container_name: str, workspace_path: Path, payload: ExecutionRequest) -> None:
    host_workspace_path = resolve_host_workspace_path(workspace_path)
    subprocess.run(
        [
            "docker",
            "create",
            "--name",
            container_name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            str(payload.limits.pids),
            "--memory",
            f"{payload.limits.memory_mb}m",
            "--cpus",
            str(payload.limits.cpus),
            "--user",
            "65532:65532",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={payload.limits.tmpfs_mb}m",
            "-e",
            "HOME=/workspace/tmp/home",
            "-e",
            "TMPDIR=/workspace/tmp",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PIP_CACHE_DIR=/workspace/tmp/pip-cache",
            "-e",
            "PIP_DISABLE_PIP_VERSION_CHECK=1",
            "-v",
            f"{host_workspace_path / 'repo'}:/workspace/repo:rw",
            "-v",
            f"{host_workspace_path / 'out'}:/workspace/out:rw",
            "-v",
            f"{host_workspace_path / 'tmp'}:/workspace/tmp:rw",
            "-w",
            "/workspace/repo",
            payload.image,
            "sleep",
            "infinity",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def resolve_host_workspace_path(workspace_path: Path) -> Path:
    shared_root = Path(settings.shared_workspace_root).resolve()
    host_root = Path(settings.host_workspace_root).resolve()
    relative_path = workspace_path.resolve().relative_to(shared_root)
    return host_root / relative_path


def start_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "start", container_name],
        check=True,
        capture_output=True,
        text=True,
    )


def run_command(container_name: str, command: list[str], timeout_seconds: int) -> StepResult:
    started = monotonic()
    try:
        completed = subprocess.run(
            ["docker", "exec", container_name, *command],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return StepResult(
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=round(monotonic() - started, 3),
        )
    except subprocess.TimeoutExpired as exc:
        return StepResult(
            command=command,
            exit_code=None,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            duration_seconds=round(monotonic() - started, 3),
            timed_out=True,
        )


def remove_container(container_name: str) -> None:
    if shutil.which("docker") is None:
        return
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        check=False,
        capture_output=True,
        text=True,
    )


def rewrite_python_command(command: list[str]) -> list[str]:
    if len(command) >= 3 and command[0] == "python":
        if command[1] == "-m" and command[2] == "pytest":
            return command
        return ["/workspace/out/venv/bin/python", *command[1:]]
    return command


def build_response(
    *,
    python_version: str,
    platform_system: str,
    limits: ExecutionLimits,
    steps: dict,
    error: dict | None,
) -> ExecutionResponse:
    return ExecutionResponse(
        python_version=python_version,
        platform_system=platform_system,
        isolation={
            "network_mode": "none",
            "read_only_rootfs": True,
            "repo_mount_read_only": False,
            "cap_drop_all": True,
            "no_new_privileges": True,
            "cpus": limits.cpus,
            "memory_mb": limits.memory_mb,
            "pids": limits.pids,
            "tmpfs_mb": limits.tmpfs_mb,
            "worker_has_docker_socket": False,
        },
        steps=steps,
        error=error,
    )
