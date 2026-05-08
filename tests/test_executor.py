import subprocess
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from executor.app import main as executor_main


def test_executor_rejects_workspace_path_outside_shared_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        executor_main,
        "settings",
        SimpleNamespace(
            shared_workspace_root=str(tmp_path / "shared"),
            host_workspace_root=str(tmp_path / "host-shared"),
            allowed_image="astsp-executor:latest",
        ),
    )
    client = TestClient(executor_main.app)

    response = client.post(
        "/executions",
        json={
            "run_id": "run-1",
            "workspace_id": "workspace-1",
            "workspace_path": str(tmp_path / "outside"),
            "image": "astsp-executor:latest",
            "install_timeout_seconds": 300,
            "suite_timeout_seconds": 600,
            "limits": {"cpus": 1.0, "memory_mb": 1024, "pids": 256, "tmpfs_mb": 128},
            "commands": {"bootstrap": [], "install": [], "existing_suite": None, "generated_suite": None},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "workspace_path must be inside the shared workspace root"


def test_executor_healthz_reports_missing_docker(monkeypatch) -> None:
    monkeypatch.setattr(executor_main.shutil, "which", lambda _: None)
    monkeypatch.setattr(executor_main.Path, "exists", lambda self: False)
    client = TestClient(executor_main.app)

    response = client.get("/healthz")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "degraded"
    assert "docker_cli_missing" in detail["issues"]
    assert "docker_socket_missing" in detail["issues"]


def test_executor_returns_503_when_docker_cli_is_missing(tmp_path: Path, monkeypatch) -> None:
    shared_root = tmp_path / "shared"
    host_root = tmp_path / "host-shared"
    workspace_path = shared_root / "run-1"
    workspace_path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        executor_main,
        "settings",
        SimpleNamespace(shared_workspace_root=str(shared_root), host_workspace_root=str(host_root), allowed_image="astsp-executor:latest"),
    )
    monkeypatch.setattr(executor_main.shutil, "which", lambda _: None)
    monkeypatch.setattr(executor_main.Path, "exists", lambda self: True if str(self) == "/var/run/docker.sock" else Path.exists(self))
    monkeypatch.setattr(executor_main.Path, "is_socket", lambda self: True if str(self) == "/var/run/docker.sock" else Path.is_socket(self))
    client = TestClient(executor_main.app)

    response = client.post(
        "/executions",
        json={
            "run_id": "run-1",
            "workspace_id": "workspace-1",
            "workspace_path": str(workspace_path),
            "image": "astsp-executor:latest",
            "install_timeout_seconds": 300,
            "suite_timeout_seconds": 600,
            "limits": {"cpus": 1.0, "memory_mb": 1024, "pids": 256, "tmpfs_mb": 128},
            "commands": {"bootstrap": [], "install": [], "existing_suite": None, "generated_suite": None},
        },
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "degraded"
    assert "docker_cli_missing" in detail["issues"]


def test_executor_creates_hardened_container_and_rewrites_python_commands(tmp_path: Path, monkeypatch) -> None:
    shared_root = tmp_path / "shared"
    host_root = tmp_path / "host-shared"
    workspace_path = shared_root / "run-1"
    for child in ("repo", "out", "tmp"):
        (workspace_path / child).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        executor_main,
        "settings",
        SimpleNamespace(shared_workspace_root=str(shared_root), host_workspace_root=str(host_root), allowed_image="astsp-executor:latest"),
    )
    monkeypatch.setattr(executor_main.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(executor_main.Path, "exists", lambda self: True if str(self) == "/var/run/docker.sock" else Path.exists(self))
    monkeypatch.setattr(executor_main.Path, "is_socket", lambda self: True if str(self) == "/var/run/docker.sock" else Path.is_socket(self))
    recorded_commands: list[list[str]] = []

    def fake_run(command: list[str], check: bool, capture_output: bool, text: bool, timeout: int | None = None):
        recorded_commands.append(command)
        if command[:2] == ["docker", "exec"] and command[-2:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout="Python 3.12.9\n", stderr="")
        if command[:2] == ["docker", "exec"] and command[3:] == ["python", "-c", "import platform; print(platform.system())"]:
            return SimpleNamespace(returncode=0, stdout="Linux\n", stderr="")
        if command[:2] == ["docker", "exec"]:
            return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(executor_main.subprocess, "run", fake_run)
    client = TestClient(executor_main.app)

    response = client.post(
        "/executions",
        json={
            "run_id": "run-1",
            "workspace_id": "workspace-1",
            "workspace_path": str(workspace_path),
            "image": "astsp-executor:latest",
            "install_timeout_seconds": 300,
            "suite_timeout_seconds": 600,
            "limits": {"cpus": 1.0, "memory_mb": 1024, "pids": 256, "tmpfs_mb": 128},
            "commands": {
                "bootstrap": [["python", "-m", "venv", "/workspace/out/venv"]],
                "install": [["python", "-m", "pip", "install", "pytest"]],
                "existing_suite": ["python", "-m", "pytest", "tests"],
                "generated_suite": ["python", "-m", "pytest", ".astap/generated_tests"],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["isolation"]["network_mode"] == "none"
    assert payload["isolation"]["read_only_rootfs"] is True
    assert payload["isolation"]["repo_mount_read_only"] is False
    assert payload["isolation"]["cap_drop_all"] is True
    assert payload["isolation"]["no_new_privileges"] is True
    assert payload["isolation"]["worker_has_docker_socket"] is False
    assert payload["platform_system"] == "Linux"

    create_command = recorded_commands[0]
    assert create_command[:2] == ["docker", "create"]
    assert "--network" in create_command and create_command[create_command.index("--network") + 1] == "none"
    assert "--read-only" in create_command
    assert "--cap-drop" in create_command and create_command[create_command.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in create_command and create_command[create_command.index("--security-opt") + 1] == "no-new-privileges:true"
    assert "--user" in create_command and create_command[create_command.index("--user") + 1] == "65532:65532"
    assert f"{host_root / 'run-1' / 'repo'}:/workspace/repo:rw" in create_command
    assert f"{host_root / 'run-1' / 'out'}:/workspace/out:rw" in create_command
    assert f"{host_root / 'run-1' / 'tmp'}:/workspace/tmp:rw" in create_command
    exec_commands = [cmd for cmd in recorded_commands if cmd[:2] == ["docker", "exec"]]
    assert any("/workspace/out/venv/bin/python" in cmd for cmd in exec_commands)
    assert any(cmd[3:6] == ["python", "-m", "pytest"] for cmd in exec_commands)
    assert recorded_commands[-1][:3] == ["docker", "rm", "-f"]


def test_executor_cleans_up_after_timeout(tmp_path: Path, monkeypatch) -> None:
    shared_root = tmp_path / "shared"
    host_root = tmp_path / "host-shared"
    workspace_path = shared_root / "run-1"
    for child in ("repo", "out", "tmp"):
        (workspace_path / child).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        executor_main,
        "settings",
        SimpleNamespace(shared_workspace_root=str(shared_root), host_workspace_root=str(host_root), allowed_image="astsp-executor:latest"),
    )
    monkeypatch.setattr(executor_main.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(executor_main.Path, "exists", lambda self: True if str(self) == "/var/run/docker.sock" else Path.exists(self))
    monkeypatch.setattr(executor_main.Path, "is_socket", lambda self: True if str(self) == "/var/run/docker.sock" else Path.is_socket(self))
    recorded_commands: list[list[str]] = []

    def fake_run(command: list[str], check: bool, capture_output: bool, text: bool, timeout: int | None = None):
        recorded_commands.append(command)
        if command[:2] == ["docker", "exec"] and command[-2:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout="Python 3.12.9\n", stderr="")
        if command[:2] == ["docker", "exec"] and command[3:] == ["python", "-c", "import platform; print(platform.system())"]:
            return SimpleNamespace(returncode=0, stdout="Linux\n", stderr="")
        if command[:2] == ["docker", "exec"] and "pytest" in command:
            raise subprocess.TimeoutExpired(command, timeout or 1, output="partial stdout", stderr="partial stderr")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(executor_main.subprocess, "run", fake_run)
    client = TestClient(executor_main.app)

    response = client.post(
        "/executions",
        json={
            "run_id": "run-1",
            "workspace_id": "workspace-1",
            "workspace_path": str(workspace_path),
            "image": "astsp-executor:latest",
            "install_timeout_seconds": 300,
            "suite_timeout_seconds": 1,
            "limits": {"cpus": 1.0, "memory_mb": 1024, "pids": 256, "tmpfs_mb": 128},
            "commands": {
                "bootstrap": [["python", "-m", "venv", "/workspace/out/venv"]],
                "install": [],
                "existing_suite": ["python", "-m", "pytest", "tests"],
                "generated_suite": None,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["steps"]["existing_suite"]["timed_out"] is True
    assert payload["steps"]["existing_suite"]["exit_code"] is None
    assert recorded_commands[-1][:3] == ["docker", "rm", "-f"]
