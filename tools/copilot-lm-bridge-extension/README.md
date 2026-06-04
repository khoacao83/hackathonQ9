# Copilot LM Bridge Extension

This extension exposes a local HTTP endpoint that forwards prompts to VS Code Language Model API.

- Endpoint: `POST /patch`
- Health check: `GET /health`
- Default URL: `http://127.0.0.1:8765`

## Request body

```json
{
  "task": "Fix ...",
  "target_file": "app/banking/payment_service.py",
  "related_files": ["..."],
  "attempt": 1,
  "error_feedback": "...",
  "context": "...",
  "prompt": "..."
}
```

## Response body

```json
{
  "patch": "--- a/...\n+++ b/...\n..."
}
```

## Commands

- `Copilot LM Bridge: Start Server`
- `Copilot LM Bridge: Stop Server`
- `Copilot LM Bridge: Request Copilot Consent`
- `Copilot LM Bridge: Run Pipeline Fix For Active File`

## IDE workflow command

`Run Pipeline Fix For Active File` lets you run the assembly-line pipeline directly from VS Code:

1. Uses the active editor file as `--file` when it is inside the configured project root.
2. Prompts for a natural-language fix task.
3. Runs Precheck Gate (workspace/file scope, python executable, bridge health).
4. Calls Copilot model through the local bridge to generate unified diff patch text.
5. Saves patch to `.tmp/copilot_patch.diff` in the project root.
6. Runs `python -m assembly_line.main` in `external-patch` mode.
7. Reads `outputs/run_log.json` and shows token saving percent in output.
8. If decision is `READY_FOR_HUMAN_REVIEW`, asks user consent before source apply.

If precheck fails, command stops immediately (fail-fast, no model call) and writes precheck artefacts:

- `outputs/run_log.json` (stage=`PRECHECK`)
- `outputs/evidence_report.md`

The command automatically sets:

- `LLM_BACKEND=proxy_command`
- `LLM_PROXY_COMMAND=<pythonCommand> <proxyClientPath>`
- `PYTHONPATH=<assemblyLineRoot>/src` when `setPythonPath=true` and the folder exists

And invokes engine args:

- `--llm-mode external-patch`
- `--patch-file <projectRoot>/.tmp/copilot_patch.diff`

Configurable settings:

- `copilotLmBridge.projectRoot` (default: `.`)
- `copilotLmBridge.assemblyLineRoot` (default: empty, means current workspace)
- `copilotLmBridge.outputDir` (default: `outputs`)
- `copilotLmBridge.proxyClientPath` (default: `tools/lm_proxy_http_client.py`)
- `copilotLmBridge.setPythonPath` (default: `true`)
- `copilotLmBridge.pythonCommand` (default: `python`)

Legacy setting:

- `copilotLmBridge.workspaceProjectRoot` (kept for backward compatibility)

## Run on any project window

You can open a completely different project in a new VS Code window and still run this extension.

Example setup for a different project window:

- `copilotLmBridge.projectRoot = .`
- `copilotLmBridge.assemblyLineRoot = C:/OJT/ai-code-assembly-line`
- `copilotLmBridge.proxyClientPath = tools/lm_proxy_http_client.py`

This keeps your target code in the new window, while the engine and bridge client are loaded from the assembly-line repo.

## Local VSIX install

This repo can package the extension without `npm`, `npx`, or `vsce`.

From the workspace root:

```powershell
python tools/package_vsix.py --extension-dir tools/copilot-lm-bridge-extension --output dist/copilot-lm-bridge-extension.vsix
```

Then install it into the main VS Code instance:

```powershell
"$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe" --install-extension "dist/copilot-lm-bridge-extension.vsix" --force
```

You can also run the root workspace tasks:

- `Build Copilot LM Bridge VSIX`
- `Install Copilot LM Bridge VSIX`

After installation, reload VS Code and find these commands in the main instance:

- `Copilot LM Bridge: Start Server`
- `Copilot LM Bridge: Stop Server`
- `Copilot LM Bridge: Request Copilot Consent`
- `Copilot LM Bridge: Run Pipeline Fix For Active File`

## Notes

- This bridge depends on GitHub Copilot model availability in VS Code.
- If no model is available, run the consent command and ensure Copilot is signed in.
