from __future__ import annotations


def build_patch_prompt(
    task: str,
    context: str,
    error_summary: list[str] | None = None,
) -> str:
    errors = "\n".join(error_summary or []) or "None"

    return (
        "Return unified diff only.\n"
        "Do not explain.\n"
        "Do not modify files outside allowed context.\n"
        "Do not touch .env, secrets, credentials.\n\n"
        "Task:\n"
        f"{task}\n\n"
        "Current test errors:\n"
        f"{errors}\n\n"
        "Relevant code context:\n"
        f"{context}\n"
    )
