# Docker-based sandbox test runner.
#
# Requires Docker to be installed and the daemon to be running.
# Falls back to the local subprocess runner if Docker is unavailable.
#
# Usage: set env var USE_DOCKER=1 to activate.

import subprocess
from pathlib import Path
import os

from assembly_line.sandbox.test_runner import run_pytest as _local_run_pytest
from assembly_line.sandbox.test_runner import extract_short_error  # re-export

DOCKER_IMAGE = "python:3.11-slim"


def is_docker_available() -> bool:
    """Return True if the Docker daemon is reachable."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_pytest_docker(
    project_root: str,
    test_targets: list[str] | None = None,
    image: str = DOCKER_IMAGE,
    timeout_seconds: int | None = None,
) -> dict:
    """
    Run pytest for project_root inside a Docker container.

    The project is bind-mounted read-write at /workspace so the patched
    sandbox copy is tested in a clean, isolated environment.

    Returns the same dict shape as test_runner.run_pytest():
        {"passed": bool, "output": str, "returncode": int}
    """
    host_path = str(Path(project_root).resolve())
    selected_targets = test_targets or ["tests"]
    pytest_targets = " ".join(selected_targets)
    timeout = timeout_seconds or int(os.environ.get("DOCKER_TEST_TIMEOUT_SECONDS", os.environ.get("TEST_TIMEOUT_SECONDS", "120")))
    docker_cmd = (
        "if [ -f requirements.txt ]; then "
        "pip install -q --disable-pip-version-check -r requirements.txt; "
        "else pip install -q --disable-pip-version-check pytest; fi "
        f"&& pytest {pytest_targets} -v --tb=short"
    )
    cmd = [
        "docker", "run", "--rm",
        "--network", "none",          # no outbound network from sandbox
        "-v", f"{host_path}:/workspace",
        "-w", "/workspace",
        image,
        "sh", "-c", docker_cmd,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout + result.stderr
        return {
            "passed": result.returncode == 0,
            "output": output,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + (exc.stderr or "")
        output = partial + f"\n[timeout] docker pytest exceeded {timeout}s"
        return {
            "passed": False,
            "output": output,
            "returncode": 124,
        }


def run_pytest(
    project_root: str,
    test_targets: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> dict:
    """
    Entry point used by orchestrator.
    Tries Docker first; falls back to local subprocess if Docker is unavailable.
    """
    strict_mode = os.environ.get("SANDBOX_STRICT", "").strip().lower() in {"1", "true", "yes"}
    if is_docker_available():
        print("       [docker_runner] Running tests inside Docker container …")
        return run_pytest_docker(project_root, test_targets, timeout_seconds=timeout_seconds)

    if strict_mode:
        return {
            "passed": False,
            "output": "[docker_runner] Docker not available and SANDBOX_STRICT is enabled",
            "returncode": 125,
        }

    print("       [docker_runner] Docker not available — falling back to local runner")
    return _local_run_pytest(project_root, test_targets, timeout_seconds)
