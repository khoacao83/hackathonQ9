# Real GitHub Copilot Enterprise API client.
#
# Requires env var: GITHUB_TOKEN (a token with `copilot` scope)
# Falls back to mock_client if GITHUB_TOKEN is not set.
#
# API: OpenAI-compatible chat completions hosted by GitHub Copilot.

import json
import os
import urllib.error
import urllib.request

from assembly_line.llm.mock_client import _build_prompt
from assembly_line.llm.mock_client import generate_patch as _mock_generate_patch

COPILOT_API_URL = "https://api.githubcopilot.com/chat/completions"
COPILOT_MODEL = "gpt-4o"


def _call_copilot_api(prompt: str, token: str) -> str:
    """Send prompt to Copilot Enterprise API and return the text response."""
    payload = {
        "model": COPILOT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
        "temperature": 0,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        COPILOT_API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Copilot-Integration-Id": "vscode-chat",
            "Editor-Version": "vscode/1.90.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        body = json.loads(resp.read())
    return body["choices"][0]["message"]["content"].strip()


def generate_patch(
    task: str,
    context: str,
    attempt: int = 1,
    error_feedback: str = "",
    target_file: str = "",
    related_files: list[str] | None = None,
) -> str:
    """
    Generate a patch using the real GitHub Copilot Enterprise API.

    If GITHUB_TOKEN is not set, falls back to the deterministic mock client
    so the demo always works without credentials.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("       [copilot_client] GITHUB_TOKEN not set — falling back to mock")
        return _mock_generate_patch(
            task=task,
            context=context,
            attempt=attempt,
            error_feedback=error_feedback,
            target_file=target_file,
            related_files=related_files,
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

    try:
        print(f"       [copilot_client] Calling Copilot API (attempt {attempt}) …")
        patch = _call_copilot_api(prompt, token)
        return patch
    except urllib.error.HTTPError as exc:
        print(f"       [copilot_client] HTTP {exc.code} from API — falling back to mock")
        return _mock_generate_patch(
            task=task,
            context=context,
            attempt=attempt,
            error_feedback=error_feedback,
            target_file=target_file,
            related_files=related_files,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"       [copilot_client] API error ({exc}) — falling back to mock")
        return _mock_generate_patch(
            task=task,
            context=context,
            attempt=attempt,
            error_feedback=error_feedback,
            target_file=target_file,
            related_files=related_files,
        )
