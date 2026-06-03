# AI Code Assembly Line - Phase 2 (Copilot LM)

This repository now supports a Phase 2 flow that does not require a separate LLM API key.

## Architecture

- VS Code extension uses `vscode.lm.selectChatModels({ vendor: 'copilot' })` to generate unified diff patch text.
- Extension writes patch to `.tmp/copilot_patch.diff`.
- Python pipeline runs in `external-patch` mode and reads patch from file.
- Patch is validated, applied in sandbox, tested, and reported.

## Run Python Pipeline With External Patch

```powershell
$env:PYTHONPATH = "src"
python -m assembly_line.main `
	--project demo_project `
	--file app/services/report_service.py `
	--task "Fix export_report when data is empty" `
	--llm-mode external-patch `
	--patch-file .tmp/copilot_patch.diff `
	--output outputs
```

## VS Code Extension

Extension files are in `vscode-extension/`.

- Command: `AI Code Assembly: Safe Patch Current File`
- Entry: `vscode-extension/extension.js`
- Manifest: `vscode-extension/package.json`

The command:

1. Reads active file and task input.
2. Calls Copilot model via VS Code LM API.
3. Saves patch to `.tmp/copilot_patch.diff`.
4. Starts Python pipeline with `--llm-mode external-patch`.
