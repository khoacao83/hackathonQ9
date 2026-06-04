# AI Code Assembly Line — Copilot Instructions

## Project Purpose
A pipeline that prevents AI-generated code from entering an enterprise codebase without validation.
Every patch must pass: Context Gate → Patch Gate → Test Gate → Evidence Gate.

## Architecture
```
CLI: src/assembly_line/main.py
  └─ orchestrator.py          ← central coordinator (7-step pipeline)
       ├─ graph/import_scanner.py    ← AST-based 1-hop import scan
       ├─ context/context_builder.py ← prune comments, build context
       ├─ context/token_meter.py     ← estimate tokens (len // 4)
       ├─ llm/mock_client.py         ← deterministic mock: attempt 1 buggy, attempt 2+ correct
  ├─ llm/proxy_client.py        ← local proxy-command backend
       ├─ patch/patch_applier.py     ← apply patch to sandbox copy
       ├─ sandbox/test_runner.py     ← run pytest, extract error summary
       └─ report/evidence_report.py  ← write patch.diff, evidence_report.md, run_log.json
```

## Demo Use Case
- Target file: `demo_project/app/banking/payment_service.py`
- Bug: `transfer()` ignores the transfer fee when validating sender balance
- Tests: `demo_project/tests/test_payment_service.py` (3 cases)
- Expected flow: attempt 1 FAIL (balance check still wrong) → self-heal → attempt 2 PASS → READY_FOR_HUMAN_REVIEW

## Run Command (PowerShell)
```powershell
$env:PYTHONPATH="src"
$env:LLM_BACKEND="proxy_command"
$env:LLM_PROXY_COMMAND="python tools/lm_proxy_http_client.py"
python -m assembly_line.main --project demo_project --file "app/banking/payment_service.py" --task "Fix payment transfer when balance cannot cover amount plus fee"
```

## Conventions
- Python 3.11, supports mock, Copilot API token, or VS Code LM proxy backend
- venv at `.venv/`, activate with `.venv\Scripts\Activate.ps1`
- `PYTHONPATH=src` required for imports
- Outputs go to `outputs/` directory
- Sandbox is a temp copy — original files never modified by pipeline
- Token estimate: `len(text) // 4`
- Comment pruning: keep lines matching TODO|FIXME|NOTE|IMPORTANT|CHÚ Ý, drop rest
- Test execution is scoped to the selected demo slice
- VS Code Language Model API is accessed through `tools/copilot-lm-bridge-extension/`

## Key Constraints
- MAX_ATTEMPTS = 3 for self-healing loop
- Mock LLM: banking attempt=1 checks amount and fee separately (buggy); attempt>=2 checks `amount + fee` (correct)
- All pipeline modules are under `src/assembly_line/`
- Demo project is under `demo_project/` and must NOT be modified by the pipeline (sandbox isolation)
