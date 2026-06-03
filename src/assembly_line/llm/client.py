from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from assembly_line.llm.mock_client import MockLLMClient
from assembly_line.llm.prompt_builder import build_patch_prompt


@dataclass
class HttpLLMClient:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 45

    def generate_patch(
        self,
        task: str,
        context: str,
        error_summary: list[str] | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a senior software engineer. "
                        "Return ONLY a unified diff patch. "
                        "Do not include markdown fences."
                    ),
                },
                {
                    "role": "user",
                    "content": build_patch_prompt(task, context, error_summary),
                },
            ],
            "temperature": 0,
        }

        body = json.dumps(payload).encode("utf-8")
        endpoint = self.base_url.rstrip("/") + "/chat/completions"

        req = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        with request.urlopen(req, timeout=self.timeout_seconds) as resp:
            text = resp.read().decode("utf-8")

        data = json.loads(text)
        return _extract_message_content(data)


@dataclass
class PatchGenerator:
    provider: str = "mock"
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None

    def __post_init__(self) -> None:
        self.provider = (self.provider or "mock").lower()

        self.model = self.model or os.getenv("LLM_MODEL", "")
        self.base_url = self.base_url or os.getenv("LLM_API_BASE_URL", "")
        self.api_key = self.api_key or os.getenv("LLM_API_KEY", "")

        self._mock = MockLLMClient()
        self._http = None

        if self.provider != "mock" and self.base_url and self.api_key and self.model:
            self._http = HttpLLMClient(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
            )

    def generate_patch(
        self,
        task: str,
        context: str,
        error_summary: list[str] | None = None,
    ) -> str:
        if not self._http:
            return self._mock.generate_patch(task, context, error_summary)

        try:
            return self._http.generate_patch(task, context, error_summary)
        except (error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError):
            return self._mock.generate_patch(task, context, error_summary)


def _extract_message_content(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices") or []
    if not choices:
        raise ValueError("LLM response missing choices")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response missing content")

    return content
