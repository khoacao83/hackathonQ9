from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TestResult:
    passed: bool
    return_code: int
    output: str
    command: list[str]


@dataclass
class PytestRunner:
    timeout_seconds: int = 30
    use_docker: bool = False
    strict_docker: bool = False
    docker_image: str = "ai-code-sandbox:py311"
    docker_network: str = "none"
    docker_memory: str = "512m"
    docker_cpus: str = "1.0"

    def run(self, project_root: str) -> TestResult:
        root = Path(project_root).resolve()

        if self.use_docker:
            docker_result = self._run_in_docker(root)
            if docker_result is not None:
                return docker_result

            if self.strict_docker:
                return TestResult(
                    passed=False,
                    return_code=127,
                    output=(
                        "Docker mode is enabled but Docker is unavailable or failed to start."
                    ),
                    command=["docker", "run", "..."],
                )

        command = [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-q",
        ]

        env = os.environ.copy()
        env["PYTHONPATH"] = str(root)

        try:
            proc = subprocess.run(
                command,
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
            )

            output = (proc.stdout or "") + "\n" + (proc.stderr or "")

            return TestResult(
                passed=proc.returncode == 0,
                return_code=proc.returncode,
                output=output,
                command=command,
            )

        except subprocess.TimeoutExpired as exc:
            output = (
                f"Test timeout after {self.timeout_seconds} seconds.\n"
                f"stdout={exc.stdout}\n"
                f"stderr={exc.stderr}"
            )

            return TestResult(
                passed=False,
                return_code=124,
                output=output,
                command=command,
            )

    def _run_in_docker(self, root: Path) -> TestResult | None:
        if not self._is_docker_available():
            return None

        mount_src = root.as_posix()
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            self.docker_network,
            "--memory",
            self.docker_memory,
            "--cpus",
            self.docker_cpus,
            "-v",
            f"{mount_src}:/app",
            "-w",
            "/app",
            self.docker_image,
            "python",
            "-m",
            "pytest",
            "tests",
            "-q",
        ]

        try:
            proc = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
            )

            output = (proc.stdout or "") + "\n" + (proc.stderr or "")

            return TestResult(
                passed=proc.returncode == 0,
                return_code=proc.returncode,
                output=output,
                command=command,
            )

        except subprocess.TimeoutExpired as exc:
            output = (
                f"Docker test timeout after {self.timeout_seconds} seconds.\n"
                f"stdout={exc.stdout}\n"
                f"stderr={exc.stderr}"
            )

            return TestResult(
                passed=False,
                return_code=124,
                output=output,
                command=command,
            )

    def _is_docker_available(self) -> bool:
        try:
            proc = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                text=True,
                capture_output=True,
                timeout=8,
            )
            return proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False


def run_pytest(
    project_root: str,
    timeout_seconds: int = 30,
    use_docker: bool = False,
    strict_docker: bool = False,
    docker_image: str = "ai-code-sandbox:py311",
    docker_network: str = "none",
    docker_memory: str = "512m",
    docker_cpus: str = "1.0",
) -> dict:
    runner = PytestRunner(
        timeout_seconds=timeout_seconds,
        use_docker=use_docker,
        strict_docker=strict_docker,
        docker_image=docker_image,
        docker_network=docker_network,
        docker_memory=docker_memory,
        docker_cpus=docker_cpus,
    )
    result = runner.run(project_root)

    return {
        "passed": result.passed,
        "return_code": result.return_code,
        "output": result.output,
        "command": result.command,
    }


def extract_short_error(test_output: str, max_lines: int = 6) -> list[str]:
    keywords = [
        "FAILED",
        "AssertionError",
        "TypeError",
        "AttributeError",
        "NameError",
        "ImportError",
        "ModuleNotFoundError",
        "Error",
        "assert",
    ]

    lines = [line.strip() for line in test_output.splitlines() if line.strip()]
    important = [
        line
        for line in lines
        if any(keyword in line for keyword in keywords)
    ]

    if important:
        return important[:max_lines]

    return lines[-max_lines:]