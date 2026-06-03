from __future__ import annotations

from typing import Protocol


class BaseLLMClient(Protocol):
    def generate_patch(
        self,
        task: str,
        context: str,
        error_summary: list[str] | None = None,
    ) -> str:
        ...
