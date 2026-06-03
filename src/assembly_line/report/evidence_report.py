from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class EvidenceReportWriter:
    output_dir: str

    def __post_init__(self) -> None:
        self.out = Path(self.output_dir).resolve()
        self.out.mkdir(parents=True, exist_ok=True)

    def write(self, data: dict[str, Any]) -> dict[str, str]:
        patch_path = self.out / "patch.diff"
        report_path = self.out / "evidence_report.md"
        log_path = self.out / "run_log.json"

        patch_path.write_text(data.get("patch_text", ""), encoding="utf-8")
        log_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        report_path.write_text(
            self._render_markdown(data),
            encoding="utf-8",
        )

        return {
            "patch": str(patch_path),
            "report": str(report_path),
            "log": str(log_path),
        }

    def _render_markdown(self, data: dict[str, Any]) -> str:
        related_files = data.get("related_files", [])
        changed_files = data.get("changed_files", [])
        errors = data.get("last_error_summary", [])
        token_metrics = data.get("token_metrics", {})

        related_md = "\n".join(f"- `{file}`" for file in related_files) or "- None"
        changed_md = "\n".join(f"- `{file}`" for file in changed_files) or "- None"
        errors_md = "\n".join(f"- {line}" for line in errors) or "- None"

        final_status = data.get("final_status", "failed")
        decision = (
            "READY_FOR_HUMAN_REVIEW"
            if final_status == "passed"
            else "NEED_DEVELOPER_REVIEW"
        )
        engine = data.get("engine", {})
        fence = "```"
        return f"""# AI Code Assembly Line - Evidence Report

## Metadata

- Generated at: `{data.get("generated_at")}`
- Final status: **{final_status.upper()}**
- Final decision: **{decision}**

## User Task

{data.get("task")}

## Target File

`{data.get("target_file")}`

## Related Files Detected

{related_md}

## Context Optimization

- Raw context tokens: `{token_metrics.get("raw_tokens")}`
- Optimized context tokens: `{token_metrics.get("optimized_tokens")}`
- Saved tokens: `{token_metrics.get("saved_tokens")}`
- Saved percent: `{token_metrics.get("saved_percent")}%`

## Execution Engine

- LLM provider: `{engine.get("llm_provider", "mock")}`
- Docker sandbox: `{engine.get("use_docker", False)}`
- Docker image: `{engine.get("docker_image", "ai-code-sandbox:py311")}`

## Self-Healing

- Attempts used: `{data.get("attempts_used")}`
- Max attempts: `{data.get("max_attempts")}`

## Error Log Used For Healing

{errors_md}

## Files Changed

{changed_md}

## Test Output Summary

{fence}txt
{data.get("last_test_output", "")[-3000:]}
{fence}
"""


def write_outputs(
    output_dir: str,
    task: str,
    target_file: str,
    related_files: list[str],
    token_metrics: dict[str, Any],
    changed_files: list[str],
    final_status: str,
    attempts_used: int,
    last_error_summary: list[str],
    patch_text: str,
    last_test_output: str,
    max_attempts: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, str]:
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "target_file": target_file,
        "related_files": related_files,
        "token_metrics": token_metrics,
        "changed_files": changed_files,
        "final_status": final_status,
        "attempts_used": attempts_used,
        "last_error_summary": last_error_summary,
        "patch_text": patch_text,
        "last_test_output": last_test_output,
        "max_attempts": max_attempts,
    }

    if extra:
        payload.update(extra)

    writer = EvidenceReportWriter(output_dir=output_dir)
    return writer.write(payload)