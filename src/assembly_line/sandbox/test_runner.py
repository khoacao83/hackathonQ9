import subprocess
import sys
from pathlib import Path
import os


def run_pytest(
    project_root: str,
    test_targets: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> dict:
    """
    Run pytest inside project_root against the provided test targets.

    Returns:
        {
            "passed": bool,
            "output": str,       # full captured stdout+stderr
            "returncode": int,
        }
    """
    selected_targets = test_targets or ["tests"]
    pytest_targets = [str(Path(project_root) / target) for target in selected_targets]
    timeout = timeout_seconds or int(os.environ.get("TEST_TIMEOUT_SECONDS", "120"))
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *pytest_targets, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return {
            "passed": result.returncode == 0,
            "output": output,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + (exc.stderr or "")
        output = partial + f"\n[timeout] pytest exceeded {timeout}s"
        return {
            "passed": False,
            "output": output,
            "returncode": 124,
        }


def extract_short_error(output: str, max_lines: int = 3) -> list[str]:
    """
    Extract a short, human-readable error summary from pytest output.
    Looks for FAILED lines and the first few lines of the traceback/error section.
    """
    lines = output.splitlines()
    errors: list[str] = []

    # Collect FAILED test names
    for line in lines:
        if line.startswith("FAILED") or "ERROR" in line:
            errors.append(line.strip())
        if len(errors) >= max_lines:
            break

    # If we found nothing specific, fall back to last N lines
    if not errors:
        errors = [l.strip() for l in lines[-max_lines:] if l.strip()]

    return errors[:max_lines]
