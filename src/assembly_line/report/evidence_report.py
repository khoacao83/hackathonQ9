"""
Writes the audit trail after a successful pipeline run:
  outputs/patch.diff
  outputs/evidence_report.md
  outputs/run_log.json
"""
import json
from datetime import datetime
from pathlib import Path


def write_report(
    output_dir: str,
    task: str,
    target_file: str,
    patch_text: str,
    changed_files: list[str],
    attempts: int,
    token_stats: dict,
    test_output: str,
    decision: str,
) -> dict:
    """
    Write evidence artefacts to output_dir.

    Returns a dict with paths to the three generated files.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. patch.diff
    diff_path = out / "patch.diff"
    diff_path.write_text(patch_text, encoding="utf-8")

    # 2. evidence_report.md
    md_lines = [
        "# AI Code Assembly Line — Evidence Report",
        "",
        f"**Generated**: {timestamp}",
        f"**Task**: {task}",
        f"**Target file**: `{target_file}`",
        f"**Decision**: `{decision}`",
        "",
        "## Token Optimization",
        f"- Raw context tokens (est.): {token_stats.get('raw_tokens', 'N/A')}",
        f"- Optimized context tokens (est.): {token_stats.get('opt_tokens', 'N/A')}",
        f"- Saving: {token_stats.get('saving_pct', 'N/A')}%",
        "",
        f"## Self-Healing Attempts: {attempts}",
        "",
        "## Changed Files",
    ]
    for f in changed_files:
        md_lines.append(f"- `{f}`")
    md_lines += [
        "",
        "## Test Output (final run)",
        "```",
        test_output.strip(),
        "```",
        "",
        "## Patch Applied",
        "```diff",
        patch_text.strip(),
        "```",
    ]
    md_path = out / "evidence_report.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    # 3. run_log.json
    log = {
        "timestamp": timestamp,
        "task": task,
        "target_file": target_file,
        "decision": decision,
        "attempts": attempts,
        "token_stats": token_stats,
        "changed_files": changed_files,
    }
    log_path = out / "run_log.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "diff": str(diff_path),
        "report": str(md_path),
        "log": str(log_path),
    }
