from __future__ import annotations

import re
from dataclasses import dataclass


PATCH_FILE_RE = re.compile(r"^(?:--- a/|\+\+\+ b/)(?P<path>.+)$", re.MULTILINE)


@dataclass(frozen=True)
class PatchValidationResult:
    valid: bool
    changed_files: list[str]
    errors: list[str]


def validate_patch(patch_text: str, policy: dict | None = None) -> PatchValidationResult:
    errors: list[str] = []

    if "--- a/" not in patch_text or "+++ b/" not in patch_text:
        errors.append("Patch is not unified diff (missing --- a/ or +++ b/ headers)")

    changed_files: list[str] = []
    for match in PATCH_FILE_RE.finditer(patch_text):
        raw = match.group("path").strip().replace("\\", "/")
        if not raw or raw == "/dev/null":
            continue
        changed_files.append(raw)

    changed_files = sorted(set(changed_files))

    if not changed_files:
        errors.append("No target files detected in patch")

    deny_patterns = [
        r"(^|/)\.env($|\.)",
        r"(^|/)secrets/",
        r"\.pem$",
        r"\.key$",
        r"\.pfx$",
    ]

    if isinstance(policy, dict):
        patch_policy = policy.get("patch", {})
        deny_patterns.extend(list(patch_policy.get("deny_patterns", [])))

    for file in changed_files:
        if "../" in file or file.startswith("/"):
            errors.append(f"Unsafe target path: {file}")
            continue

        if any(re.search(pattern, file, flags=re.IGNORECASE) for pattern in deny_patterns):
            errors.append(f"Forbidden patch target: {file}")

    return PatchValidationResult(
        valid=not errors,
        changed_files=changed_files,
        errors=errors,
    )
