"""
Sandbox MCP — mock adapter
Maps MCP tool calls to test_runner in an isolated sandbox.

Tools: run_tests, extract_error_summary

Interface:
    {"tool": "run_tests",            "input": {"sandbox_root": ".sandbox_workdir", "test_targets": ["tests/test_payment_service.py"], "timeout_seconds": 120}}
    {"tool": "extract_error_summary","input": {"output": "...", "max_lines": 3}}
"""
from assembly_line.sandbox.test_runner import run_pytest, extract_short_error


def run_tests(
    sandbox_root: str,
    test_targets: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> dict:
    result = run_pytest(sandbox_root, test_targets, timeout_seconds)
    errors = extract_short_error(result["output"]) if not result["passed"] else []
    return {
        "ok": True,
        "passed": result["passed"],
        "returncode": result["returncode"],
        "output": result["output"],
        "error_summary": errors,
        "retryable": not result["passed"],
    }


def extract_error_summary(output: str, max_lines: int = 3) -> dict:
    errors = extract_short_error(output, max_lines)
    return {"ok": True, "error_summary": errors}


def call(tool: str, input: dict) -> dict:
    """Unified MCP call dispatcher."""
    dispatch = {
        "run_tests": lambda i: run_tests(i["sandbox_root"], i.get("test_targets"), i.get("timeout_seconds")),
        "extract_error_summary": lambda i: extract_error_summary(i["output"], i.get("max_lines", 3)),
    }
    if tool not in dispatch:
        return {"ok": False, "error": f"Unknown tool: {tool}"}
    return dispatch[tool](input)
