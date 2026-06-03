from __future__ import annotations

import fnmatch
from pathlib import Path


def filter_allowed_files(
    files: list[str],
    policy: dict,
) -> tuple[list[str], list[dict[str, str]]]:
    context_policy = policy.get("context", {}) if isinstance(policy, dict) else {}
    deny_globs = list(context_policy.get("deny_file_globs", []))

    if not deny_globs:
        deny_globs = ["**/.env", "**/*.pem", "**/*.key", "secrets/**"]

    allowed: list[str] = []
    excluded: list[dict[str, str]] = []

    for file in files:
        normalized = file.replace("\\", "/")

        denied = next((pattern for pattern in deny_globs if _match(normalized, pattern)), None)
        if denied:
            excluded.append({"file": normalized, "reason": f"matches deny pattern: {denied}"})
            continue

        allowed.append(normalized)

    return sorted(set(allowed)), excluded


def _match(path: str, pattern: str) -> bool:
    if fnmatch.fnmatch(path, pattern):
        return True

    if pattern.startswith("**/"):
        return fnmatch.fnmatch(path, pattern[3:])

    return False
