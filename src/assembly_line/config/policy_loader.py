from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_POLICY: dict[str, Any] = {
    "sandbox": {
        "max_self_heal_attempts": 3,
        "test_timeout_seconds": 30,
        "use_docker": False,
        "strict_docker": False,
        "docker_image": "ai-code-sandbox:py311",
        "docker_network": "none",
        "docker_memory": "512m",
        "docker_cpus": "1.0",
    },
    "context": {
        "import_depth": 1,
        "max_file_chars": 50000,
        "deny_file_globs": [
            "**/.env",
            "**/*.pem",
            "**/*.key",
            "secrets/**",
        ],
        "keep_comment_keywords": [
            "TODO",
            "FIXME",
            "NOTE",
            "IMPORTANT",
            "CHÚ Ý",
        ],
        "deny_regex": [
            r"(?i)api[_-]?key\\s*=\\s*['\"][^'\"]+['\"]",
            r"(?i)secret[_-]?key\\s*=\\s*['\"][^'\"]+['\"]",
            r"(?i)password\\s*=\\s*['\"][^'\"]+['\"]",
            r"-----BEGIN [A-Z ]+ PRIVATE KEY-----",
        ],
    },
    "llm": {
        "mode": "provider",
        "provider": "mock",
        "model": "",
        "base_url": "",
    },
    "patch": {
        "deny_patterns": [
            r"(^|/)\\.env($|\\.)",
            r"(^|/)secrets/",
            r"\\.pem$",
            r"\\.key$",
        ],
    },
    "report": {
        "final_pass_decision": "READY_FOR_HUMAN_REVIEW",
        "final_fail_decision": "NEED_DEVELOPER_REVIEW",
    },
}


@dataclass(frozen=True)
class PolicyLoader:
    policy_path: str | None = None

    def load(self) -> dict[str, Any]:
        policy = _deep_copy(DEFAULT_POLICY)

        if not self.policy_path:
            return policy

        path = Path(self.policy_path).resolve()
        if not path.exists():
            return policy

        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            return policy

        return _deep_merge(policy, loaded)


def load_policy(policy_path: str | None = None) -> dict[str, Any]:
    return PolicyLoader(policy_path=policy_path).load()


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_copy(base)

    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value

    return merged
