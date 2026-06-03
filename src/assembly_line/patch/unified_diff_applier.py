from __future__ import annotations

from assembly_line.patch.patch_applier import apply_patch


def apply_unified_diff(project_root: str, patch_text: str) -> list[str]:
    return apply_patch(project_root=project_root, patch_text=patch_text)
