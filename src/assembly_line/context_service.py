"""Context service CLI – trả JSON qua stdout cho VS Code Extension.

Usage:
    PYTHONPATH=src python -m assembly_line.context_service \
        --project demo_project \
        --file app/services/report_service.py

Output (stdout):
    {
        "related_files": ["app/services/report_service.py", ...],
        "optimized_context": "...",
        "token_metrics": {"raw_tokens": ..., "optimized_tokens": ..., ...}
    }
"""
from __future__ import annotations

import argparse
import json
import sys

from assembly_line.config.policy_loader import load_policy
from assembly_line.context.context_builder import build_context
from assembly_line.context.context_firewall import filter_allowed_files
from assembly_line.context.token_meter import token_saving
from assembly_line.graph.import_scanner import scan_related_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AI Code Assembly Line – Context Service (JSON output)",
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Path to project root, e.g. demo_project",
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Target file relative to project root",
    )
    parser.add_argument(
        "--policy",
        default="configs/policy.yaml",
        help="Policy YAML path",
    )
    parser.add_argument(
        "--import-depth",
        type=int,
        default=None,
        help="Import graph scan depth (default from policy)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    policy = load_policy(args.policy)
    context_policy = policy.get("context", {})

    import_depth = (
        args.import_depth
        if args.import_depth is not None
        else int(context_policy.get("import_depth", 1))
    )
    keep_comment_keywords = set(context_policy.get("keep_comment_keywords", []))
    max_file_chars = int(context_policy.get("max_file_chars", 50000))
    deny_regex = list(context_policy.get("deny_regex", []))

    # 1) Scan related files (AST import graph)
    related_files = scan_related_files(
        project_root=args.project,
        target_file=args.file,
        depth=import_depth,
    )

    # 2) Filter by firewall policy
    related_files, excluded_files = filter_allowed_files(related_files, policy)

    # 3) Build optimized context
    contexts = build_context(
        project_root=args.project,
        files=related_files,
        keep_comment_keywords=keep_comment_keywords,
        max_file_chars=max_file_chars,
        deny_regex=deny_regex,
    )

    # 4) Compute token metrics
    metrics = token_saving(
        contexts["raw_context"],
        contexts["optimized_context"],
    )

    result = {
        "related_files": related_files,
        "excluded_files": excluded_files,
        "optimized_context": contexts["optimized_context"],
        "raw_context": contexts["raw_context"],
        "token_metrics": metrics,
    }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
