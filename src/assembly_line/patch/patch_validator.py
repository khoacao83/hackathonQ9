import fnmatch
from pathlib import Path
from typing import Any


_DEFAULT_FORBIDDEN = [
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/secrets/**",
]


def _normalize_rel(path_value: str) -> str:
    rel = path_value.strip().replace('\\', '/')
    if rel.startswith('a/') or rel.startswith('b/'):
        rel = rel[2:]
    return rel.lstrip('./')


def extract_patch_targets(patch_text: str) -> list[str]:
    targets: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith('+++ '):
            rel = _normalize_rel(line[4:])
            if rel and rel != '/dev/null':
                targets.append(rel)
    # Deduplicate preserving order
    seen = set()
    unique: list[str] = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _build_forbidden_globs(policy: dict[str, Any]) -> list[str]:
    patch_cfg = policy.get("patch", {}) if isinstance(policy, dict) else {}
    forbidden = patch_cfg.get("forbidden_files", []) if isinstance(patch_cfg, dict) else []
    out: list[str] = []
    for item in forbidden:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    out.extend(_DEFAULT_FORBIDDEN)
    return out


def _is_forbidden(rel: str, globs: list[str]) -> bool:
    for pat in globs:
        if fnmatch.fnmatch(rel, pat):
            return True
    return False


def validate_patch(
    patch_text: str,
    project_root: str,
    allowed_files: list[str],
    policy: dict[str, Any],
) -> tuple[bool, str, list[str]]:
    """
    Validate unified diff format and policy constraints.

    Returns: (ok, reason, patch_targets)
    """
    if not patch_text.strip():
        return False, "Patch is empty", []

    if "--- " not in patch_text or "+++ " not in patch_text:
        return False, "Patch is not a unified diff", []

    targets = extract_patch_targets(patch_text)
    if not targets:
        return False, "Patch does not contain valid target file headers", []

    forbidden_globs = _build_forbidden_globs(policy)

    normalized_allowed = set()
    for f in allowed_files:
        rel = _normalize_rel(f)
        if rel:
            normalized_allowed.add(rel)

    for rel in targets:
        if Path(rel).is_absolute() or rel.startswith("../") or "/../" in rel:
            return False, f"Forbidden patch target path: {rel}", targets
        if _is_forbidden(rel, forbidden_globs):
            return False, f"Patch target blocked by policy: {rel}", targets
        if normalized_allowed and rel not in normalized_allowed:
            return False, f"Patch target outside allowed scope: {rel}", targets

    return True, "", targets
