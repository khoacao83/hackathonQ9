from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from unidiff import PatchSet


PATCH_BLOCK_RE = re.compile(
    r"\*\*\* Begin File:\s*(?P<file>.*?)\n(?P<content>.*?)\n\*\*\* End File",
    re.DOTALL,
)


@dataclass(frozen=True)
class AppliedPatch:
    changed_files: list[str]


@dataclass
class PatchApplier:
    project_root: str

    def __post_init__(self) -> None:
        self.root = Path(self.project_root).resolve()

    def apply(self, patch_text: str) -> AppliedPatch:
        unified_changed = self._apply_unified_diff(patch_text)
        if unified_changed:
            return AppliedPatch(changed_files=unified_changed)

        # Backward compatibility for MVP mock format.
        blocks = list(PATCH_BLOCK_RE.finditer(patch_text))

        if not blocks:
            raise ValueError(
                "Unsupported patch format. Expected *** Begin File blocks."
            )

        changed_files: list[str] = []

        for block in blocks:
            relative_file = block.group("file").strip().replace("\\", "/")
            content = block.group("content")

            target = (self.root / relative_file).resolve()
            self._ensure_safe_path(target)

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content + "\n", encoding="utf-8")

            changed_files.append(relative_file)

        return AppliedPatch(changed_files=changed_files)

    def _apply_unified_diff(self, patch_text: str) -> list[str]:
        try:
            patch_set = PatchSet(patch_text.splitlines(keepends=True))
        except Exception:
            return []

        if not patch_set:
            return []

        changed_files: list[str] = []

        for patched_file in patch_set:
            relative_file = patched_file.path.replace("\\", "/").strip()
            if not relative_file:
                continue

            target = (self.root / relative_file).resolve()
            self._ensure_safe_path(target)

            if target.exists():
                source_lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
            else:
                source_lines = []

            updated_lines = self._apply_hunks(source_lines, patched_file)

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(updated_lines), encoding="utf-8")

            changed_files.append(relative_file)

        return changed_files

    def _apply_hunks(self, source_lines: list[str], patched_file) -> list[str]:
        result: list[str] = []
        src_index = 0

        for hunk in patched_file:
            hunk_start = max(hunk.source_start - 1, 0)
            if src_index < hunk_start:
                result.extend(source_lines[src_index:hunk_start])
                src_index = hunk_start

            for line in hunk:
                value = line.value
                if line.is_context:
                    if src_index < len(source_lines):
                        result.append(source_lines[src_index])
                        src_index += 1
                    else:
                        result.append(value)
                elif line.is_removed:
                    if src_index < len(source_lines):
                        src_index += 1
                elif line.is_added:
                    result.append(value)

        if src_index < len(source_lines):
            result.extend(source_lines[src_index:])

        return result

    def _ensure_safe_path(self, target: Path) -> None:
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Unsafe patch target outside project: {target}") from exc


def apply_patch(project_root: str, patch_text: str) -> list[str]:
    applier = PatchApplier(project_root=project_root)
    result = applier.apply(patch_text)
    return result.changed_files