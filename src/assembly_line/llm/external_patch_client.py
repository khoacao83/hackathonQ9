from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExternalPatchClient:
    patch_file: str

    def generate_patch(
        self,
        task: str,
        context: str,
        error_summary: list[str] | None = None,
    ) -> str:
        path = Path(self.patch_file).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Patch file not found: {path}")

        patch = path.read_text(encoding="utf-8").strip()
        if not patch:
            raise ValueError(f"Patch file is empty: {path}")

        return patch + "\n"
