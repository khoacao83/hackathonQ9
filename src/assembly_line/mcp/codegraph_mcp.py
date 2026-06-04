"""
Code Graph MCP — mock adapter
Maps MCP tool calls to import scanner, context builder, and token meter.

Tools: scan_imports, get_related_files, build_context, estimate_tokens

Interface:
    {"tool": "get_related_files", "input": {"project_root": "demo_project", "target_file": "app/services/report_service.py", "max_depth": 2}}
    {"tool": "build_context",     "input": {"project_root": "...", "target_file": "...", "related_files": [...]}}
    {"tool": "estimate_tokens",   "input": {"text": "..."}}
"""
from assembly_line.graph.import_scanner import scan_related_files
from assembly_line.context.context_builder import build_context as _build_context
from assembly_line.context.token_meter import estimate_tokens as _estimate_tokens, token_saving_percent


def scan_imports(project_root: str, target_file: str, max_depth: int = 1) -> dict:
    related = scan_related_files(project_root, target_file, max_depth=max_depth)
    return {"ok": True, "related_files": related}


def get_related_files(project_root: str, target_file: str, max_depth: int = 1) -> dict:
    related = scan_related_files(project_root, target_file, max_depth=max_depth)
    return {"ok": True, "related_files": related}


def build_context(project_root: str, target_file: str, related_files: list[str]) -> dict:
    ctx = _build_context(project_root, target_file, related_files)
    raw_tokens = _estimate_tokens(ctx["raw_context"])
    opt_tokens = _estimate_tokens(ctx["optimized_context"])
    saving = token_saving_percent(ctx["raw_context"], ctx["optimized_context"])
    return {
        "ok": True,
        "raw_context": ctx["raw_context"],
        "optimized_context": ctx["optimized_context"],
        "files_included": ctx["files_included"],
        "raw_tokens": raw_tokens,
        "optimized_tokens": opt_tokens,
        "saved_percent": saving,
    }


def estimate_tokens(text: str) -> dict:
    return {"ok": True, "tokens": _estimate_tokens(text)}


def call(tool: str, input: dict) -> dict:
    """Unified MCP call dispatcher."""
    dispatch = {
        "scan_imports": lambda i: scan_imports(i["project_root"], i["target_file"], i.get("max_depth", 1)),
        "get_related_files": lambda i: get_related_files(i["project_root"], i["target_file"], i.get("max_depth", 1)),
        "build_context": lambda i: build_context(i["project_root"], i["target_file"], i.get("related_files", [])),
        "estimate_tokens": lambda i: estimate_tokens(i["text"]),
    }
    if tool not in dispatch:
        return {"ok": False, "error": f"Unknown tool: {tool}"}
    return dispatch[tool](input)
