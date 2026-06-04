"""
File System MCP — mock adapter
Maps MCP tool calls to local filesystem operations.

Tools: read_file, write_file, list_files, copy_project_to_sandbox

Interface:
    {"tool": "read_file",  "input": {"path": "app/services/report_service.py"}}
    {"tool": "write_file", "input": {"path": "...", "content": "..."}}
    {"tool": "list_files", "input": {"directory": "app/"}}
    {"tool": "copy_project_to_sandbox", "input": {"project_root": "demo_project"}}
"""
import shutil
import tempfile
from pathlib import Path


def read_file(path: str, base: str = ".") -> dict:
    p = Path(base) / path
    if not p.exists():
        return {"ok": False, "error": f"File not found: {p}"}
    return {"ok": True, "content": p.read_text(encoding="utf-8")}


def write_file(path: str, content: str, base: str = ".") -> dict:
    p = Path(base) / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(p)}


def list_files(directory: str, base: str = ".") -> dict:
    d = Path(base) / directory
    if not d.exists():
        return {"ok": False, "error": f"Directory not found: {d}"}
    files = [str(f.relative_to(Path(base))) for f in d.rglob("*.py")]
    return {"ok": True, "files": files}


def copy_project_to_sandbox(project_root: str) -> dict:
    sandbox = tempfile.mkdtemp(prefix="aic_sandbox_")
    shutil.copytree(project_root, sandbox, dirs_exist_ok=True)
    return {"ok": True, "sandbox_root": sandbox}


def call(tool: str, input: dict) -> dict:
    """Unified MCP call dispatcher."""
    dispatch = {
        "read_file": lambda i: read_file(i["path"], i.get("base", ".")),
        "write_file": lambda i: write_file(i["path"], i["content"], i.get("base", ".")),
        "list_files": lambda i: list_files(i["directory"], i.get("base", ".")),
        "copy_project_to_sandbox": lambda i: copy_project_to_sandbox(i["project_root"]),
    }
    if tool not in dispatch:
        return {"ok": False, "error": f"Unknown tool: {tool}"}
    return dispatch[tool](input)
