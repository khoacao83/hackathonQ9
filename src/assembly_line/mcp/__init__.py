"""
MCP mock adapters for the AI Code Assembly Line.

Four lightweight adapters that expose a unified { tool, input } → result interface,
wrapping the actual pipeline modules without adding external dependencies.

    from assembly_line.mcp import filesystem_mcp, codegraph_mcp, sandbox_mcp, pipeline_mcp

    result = codegraph_mcp.call("get_related_files", {
        "project_root": "demo_project",
        "target_file": "app/services/report_service.py",
    })
"""
from assembly_line.mcp import filesystem_mcp, codegraph_mcp, sandbox_mcp, pipeline_mcp

__all__ = ["filesystem_mcp", "codegraph_mcp", "sandbox_mcp", "pipeline_mcp"]
