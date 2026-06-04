import fnmatch
from pathlib import Path
from typing import Any

_DEFAULT_DENY_GLOBS = [
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/secrets/**",
]


def _normalize_rel(path_value: str, project_root: str) -> str:
    p = Path(path_value)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(Path(project_root).resolve())
        except Exception:  # noqa: BLE001
            return ""
    return str(p).replace('\\', '/').lstrip('./')


def _get_deny_globs(policy: dict[str, Any]) -> list[str]:
    patch_cfg = policy.get("patch", {}) if isinstance(policy, dict) else {}
    forbidden = patch_cfg.get("forbidden_files", []) if isinstance(patch_cfg, dict) else []
    globs: list[str] = []
    for item in forbidden:
        if isinstance(item, str) and item.strip():
            globs.append(item.strip())
    globs.extend(_DEFAULT_DENY_GLOBS)
    return globs


def _is_denied(rel_path: str, deny_globs: list[str]) -> bool:
    for pat in deny_globs:
        # Support both direct fnmatch and recursive-style '**/' patterns.
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch('/' + rel_path, '*/' + pat.lstrip('/')):
            return True
    return False


def filter_related_files(
    project_root: str,
    target_file: str,
    related_files: list[str],
    policy: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """
    Keep only safe related files for context.

    Returns (allowed_related_abs_paths, blocked_related_rel_paths).
    """
    deny_globs = _get_deny_globs(policy)
    target_rel = _normalize_rel(target_file, project_root)

    allowed: list[str] = []
    blocked: list[str] = []

    for path in related_files:
        rel = _normalize_rel(path, project_root)
        if not rel:
            blocked.append(str(path))
            continue
        if rel == target_rel:
            continue
        if _is_denied(rel, deny_globs):
            blocked.append(rel)
            continue
        allowed.append(path)

    return allowed, blocked
