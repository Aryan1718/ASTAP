from pathlib import Path


def test_worker_no_longer_mounts_docker_socket_and_executor_does() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    worker_section = compose.split("  worker:", 1)[1].split("  executor:", 1)[0]
    executor_section = compose.split("  executor:", 1)[1].split("  client:", 1)[0]

    assert "/var/run/docker.sock:/var/run/docker.sock" not in worker_section
    assert "/var/run/docker.sock:/var/run/docker.sock" in executor_section
    assert "executor_workspaces:/executor-workspaces" in worker_section
    assert "executor_workspaces:/executor-workspaces" in executor_section
