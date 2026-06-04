"""
Pipeline MCP — adapter for running the full assembly line from IDE integrations.

Tools: run_pipeline

Interface:
    {
      "tool": "run_pipeline",
      "input": {
        "project_root": "demo_project",
        "target_file": "app/banking/payment_service.py",
        "task": "Fix ...",
        "output_dir": "outputs"
      }
    }
"""

from assembly_line.orchestrator import run_pipeline as _run_pipeline


def run_pipeline(
    project_root: str,
    target_file: str,
    task: str,
    output_dir: str = "outputs",
) -> dict:
    try:
        result = _run_pipeline(
            project_root=project_root,
            target_file=target_file,
            task=task,
            output_dir=output_dir,
        )
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def call(tool: str, input: dict) -> dict:
    dispatch = {
        "run_pipeline": lambda i: run_pipeline(
            project_root=i["project_root"],
            target_file=i["target_file"],
            task=i["task"],
            output_dir=i.get("output_dir", "outputs"),
        ),
    }
    if tool not in dispatch:
        return {"ok": False, "error": f"Unknown tool: {tool}"}
    return dispatch[tool](input)
