"""
Local bridge client for environments that cannot call an LLM HTTP API directly.

This module is intended for a trusted local proxy command, for example a small
VS Code extension bridge or any other local process that can access Copilot on
the user's machine. The Python CLI sends a JSON payload to the command's stdin
and expects the patch on stdout.
"""

import json
import os
import subprocess

from assembly_line.llm.mock_client import _build_prompt
from assembly_line.llm.mock_client import generate_patch as _mock_generate_patch


def _allow_mock_fallback() -> bool:
    value = os.environ.get("ALLOW_MOCK_FALLBACK", "1").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _fallback_to_mock(
    reason: str,
    task: str,
    context: str,
    attempt: int,
    error_feedback: str,
    target_file: str,
    related_files: list[str] | None,
) -> str:
    if not _allow_mock_fallback():
        raise RuntimeError(f"proxy backend failure: {reason}")
    print(f"       [proxy_client] {reason} — falling back to mock")
    return _mock_generate_patch(
        task=task,
        context=context,
        attempt=attempt,
        error_feedback=error_feedback,
        target_file=target_file,
        related_files=related_files,
    )


def _extract_patch(stdout: str) -> str:
    """Accept either raw unified diff text or JSON containing a patch field."""
    cleaned = stdout.strip()
    if not cleaned:
        raise ValueError("proxy command returned empty stdout")

    if cleaned.startswith("{"):
        payload = json.loads(cleaned)
        for key in ("patch", "patch_text", "output"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raise ValueError("proxy command JSON did not include patch text")

    return cleaned


def generate_patch(
    task: str,
    context: str,
    attempt: int = 1,
    error_feedback: str = "",
    target_file: str = "",
    related_files: list[str] | None = None,
) -> str:
    """
    Generate a patch by calling a trusted local proxy command.

    Configure one of the following:
    - LLM_PROXY_COMMAND="your-command-here"
    - LLM_BACKEND=proxy_command together with LLM_PROXY_COMMAND

    The command receives JSON over stdin and should return either:
    - raw unified diff text on stdout, or
    - JSON with one of: patch, patch_text, output
    """
    command = os.environ.get("LLM_PROXY_COMMAND", "").strip()
    if not command:
        return _fallback_to_mock(
            "LLM_PROXY_COMMAND not set",
            task,
            context,
            attempt,
            error_feedback,
            target_file,
            related_files,
        )

    objective = (
        "Fix the failing behavior identified in the error summary."
        if error_feedback
        else "Generate a minimal patch to satisfy the user task."
    )
    prompt = _build_prompt(
        task=task,
        target_file=target_file,
        related_files=related_files or [],
        optimized_context=context,
        error_summary=error_feedback,
        objective=objective,
    )
    request_payload = {
        "task": task,
        "target_file": target_file,
        "related_files": related_files or [],
        "attempt": attempt,
        "error_feedback": error_feedback,
        "context": context,
        "prompt": prompt,
    }

    try:
        print(f"       [proxy_client] Calling local proxy command (attempt {attempt}) …")
        result = subprocess.run(
            command,
            input=json.dumps(request_payload),
            capture_output=True,
            text=True,
            timeout=120,
            shell=True,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return _fallback_to_mock(
            f"proxy command failed to start ({exc})",
            task,
            context,
            attempt,
            error_feedback,
            target_file,
            related_files,
        )

    if result.returncode != 0:
        stderr_text = result.stderr.strip()
        stdout_text = result.stdout.strip()
        reason = (
            stderr_text
            or stdout_text
            or f"proxy command exited with code {result.returncode}"
        )
        return _fallback_to_mock(
            reason,
            task,
            context,
            attempt,
            error_feedback,
            target_file,
            related_files,
        )

    try:
        return _extract_patch(result.stdout)
    except Exception as exc:  # noqa: BLE001
        return _fallback_to_mock(
            f"invalid proxy output ({exc})",
            task,
            context,
            attempt,
            error_feedback,
            target_file,
            related_files,
        )