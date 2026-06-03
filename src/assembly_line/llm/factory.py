from __future__ import annotations

from assembly_line.llm.client import PatchGenerator
from assembly_line.llm.external_patch_client import ExternalPatchClient
from assembly_line.llm.mock_client import MockLLMClient


def create_llm_client(
    mode: str,
    patch_file: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
):
    normalized_mode = (mode or "mock").strip().lower()

    if normalized_mode == "external-patch":
        if not patch_file:
            raise ValueError("patch_file is required when llm_mode=external-patch")
        return ExternalPatchClient(patch_file=patch_file)

    if normalized_mode == "api":
        return PatchGenerator(
            provider=provider or "api",
            model=model,
            base_url=base_url,
        )

    if normalized_mode == "provider":
        return PatchGenerator(
            provider=provider or "mock",
            model=model,
            base_url=base_url,
        )

    return MockLLMClient()
