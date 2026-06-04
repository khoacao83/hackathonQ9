# AI Code Assembly Line

> **A validation harness that prevents AI-generated code from entering an enterprise codebase without human-controlled checkpoints.**

Every patch proposed by an AI model must pass four gates before it earns a `READY_FOR_HUMAN_REVIEW` stamp:

```
Context Gate → Patch Gate → Test Gate → Evidence Gate
```

---

## The Problem

AI coding assistants generate code fast — but enterprises can't blindly merge AI patches:

- **Hallucination** — AI may miss edge cases (e.g. `None` inputs)
- **Context overload** — sending an entire codebase to an LLM is wasteful and unreliable
- **No audit trail** — who approved the patch? What tests passed?
- **No self-correction** — if the patch breaks tests, a human has to manually intervene

---

## The Solution

An **Autonomous Assembly Line** that orchestrates AI patching with built-in validation and self-healing:

```
┌─────────────────────────────────────────────────────────────┐
│                    AI Code Assembly Line                     │
│                                                             │
│  [1] Import Scanner  ──► find related files (1-hop graph)  │
│  [2] Context Builder ──► prune noise, optimise token usage  │
│  [3] LLM Backend     ──► mock / Copilot API / local bridge  │
│  [4] Patch Applier   ──► write to isolated sandbox          │
│  [5] Test Runner     ──► run pytest, capture result         │
│       │ FAIL                                                │
│  [6] Self-Healing    ──► feed error back → retry (max 3×)  │
│       │ PASS                                                │
│  [7] Evidence Report ──► patch.diff + report.md + log.json │
└─────────────────────────────────────────────────────────────┘
```

**Key properties:**
- Patches are validated in an isolated sandbox before any source apply decision
- Self-healing loop retries up to **3 times**, feeding pytest error output back to the LLM each attempt
- Full **audit trail** written to `outputs/` after every run
- No external LLM API needed — deterministic mock for reliable demos
- A local proxy command can be used as an LLM bridge when the Python CLI cannot call an API directly
- Auto-detect mode can run pytest first, discover failing files, then launch fix pipeline per file
- Extension single-flow mode includes a fail-fast Precheck Gate before model invocation

---

## Project Structure

```
ai-code-assembly-line/
├── src/assembly_line/
│   ├── main.py                  # CLI entry point
│   ├── orchestrator.py          # 7-step pipeline coordinator
│   ├── graph/
│   │   └── import_scanner.py    # AST-based 1-hop import scan
│   ├── context/
│   │   ├── context_builder.py   # prune comments, build context string
│   │   └── token_meter.py       # token estimation (len // 4)
│   ├── llm/
│   │   ├── mock_client.py       # deterministic mock LLM
│   │   └── copilot_client.py    # optional real Copilot API client
│   ├── patch/
│   │   └── patch_applier.py     # apply patch to sandbox
│   ├── sandbox/
│   │   ├── test_runner.py       # run pytest, extract error summary
│   │   └── docker_runner.py     # optional Docker sandbox runner
│   └── report/
│       └── evidence_report.py   # write audit artefacts
├── demo_project/
│   ├── app/
│   │   ├── banking/payment_service.py   # buggy transfer rule
│   │   └── inventory/                   # second demo domain
│   └── tests/                           # banking + inventory tests
├── configs/policy.yaml
├── outputs/                     # generated artefacts (git-ignored)
└── requirements.txt
```

---

## Demo Use Case

**Bug:** `PaymentService.transfer()` checks `sender_balance < amount` but ignores the fee, so a transfer can incorrectly succeed when balance covers the amount but not `amount + fee`.

**Expected pipeline behaviour:**

```
[1/7] Preparing sandbox
[2/7] Scanning related files        → found account_store.py, fee_calculator.py
[3/7] Building optimized context    → raw=96 tokens, saving=1%
[4/7] Generating patch
[5/7] Running tests → FAILED        (targeted banking test still fails)
[6/7] Self-healing attempt 1/2
[5/7] Running tests → PASSED
[7/7] Generating evidence report

Final decision: READY_FOR_HUMAN_REVIEW
```

**Mock LLM behaviour (intentional for demo):**
- Attempt 1 → AI checks `sender_balance < amount or sender_balance < fee`, which still misses the combined constraint
- Attempt 2 → AI receives error feedback and switches to `sender_balance < amount + fee`

---

## Quick Start

### Prerequisites

- Python 3.11+
- Windows (PowerShell) or macOS/Linux

### Setup

```powershell
# Clone / open the project, then:
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If the checked-in `.venv` was created on another machine, run with `python` or recreate the virtual environment locally.

### Run the demo

```powershell
$env:PYTHONPATH = "src"
python -m assembly_line.main `
  --project demo_project `
  --file "app/banking/payment_service.py" `
  --task "Fix payment transfer when balance cannot cover amount plus fee"
```

Or use **Ctrl+Shift+B** in VS Code (task pre-configured).

### Run in single-flow external-patch mode

Use this mode when the extension already generated a patch file and you want the Python engine to run all gates in one consistent flow:

```powershell
$env:PYTHONPATH = "src"
$env:USE_DOCKER = "0"
python -m assembly_line.main `
  --project demo_project `
  --file "app/inventory/order_service.py" `
  --task "Validate external patch flow" `
  --llm-mode external-patch `
  --patch-file outputs/patch.diff `
  --output outputs
```

### LLM backend options

The Python CLI now supports three LLM backends:

| Backend | How to enable | Notes |
|------|----------|-------|
| Mock | default | Deterministic demo behaviour, no credentials needed |
| Copilot API | `GITHUB_TOKEN=...` or `LLM_BACKEND=copilot_api` | Uses `https://api.githubcopilot.com/chat/completions` |
| Local proxy command | `LLM_PROXY_COMMAND="..."` or `LLM_BACKEND=proxy_command` | Best fit when Copilot access is available only through a local proxy/bridge |

Why the proxy command exists:
- VS Code Language Model API / Copilot proxy lives inside the VS Code extension host, not inside this Python CLI process.
- Because of that boundary, the Python app cannot call the VS Code LM API directly.
- The supported integration point is a local bridge command that reads JSON from stdin and returns patch text on stdout.

Expected proxy command contract:
- stdin: JSON containing `task`, `target_file`, `related_files`, `attempt`, `error_feedback`, `context`, and `prompt`
- stdout: either raw unified diff text or JSON with one of `patch`, `patch_text`, `output`

If the proxy command is missing or fails, the pipeline falls back to the deterministic mock backend.

### VS Code Language Model bridge

This repository includes a real bridge implementation for VS Code Language Model API:
- Extension project: `tools/copilot-lm-bridge-extension/package.json`
- Bridge server code: `tools/copilot-lm-bridge-extension/extension.js`
- Python command client: `tools/lm_proxy_http_client.py`

Bridge flow:
1. VS Code extension starts a localhost server (default `http://127.0.0.1:8765`).
2. `proxy_client.py` invokes a command from `LLM_PROXY_COMMAND`.
3. That command (`python tools/lm_proxy_http_client.py`) forwards stdin JSON to `/patch`.
4. Extension calls `vscode.lm.selectChatModels()` and `sendRequest()`.
5. Returned patch text flows back to the pipeline.

Set up the bridge:
1. Open `tools/copilot-lm-bridge-extension` in VS Code.
2. Press `F5` to run an Extension Development Host.
3. Ensure Copilot is installed/sign-in in that host.
4. Run command palette action `Copilot LM Bridge: Request Copilot Consent` once.

Run the pipeline with bridge backend:

```powershell
$env:PYTHONPATH = "src"
$env:LLM_BACKEND = "proxy_command"
$env:LLM_PROXY_COMMAND = "python tools/lm_proxy_http_client.py"
python -m assembly_line.main `
  --project demo_project `
  --file "app/banking/payment_service.py" `
  --task "Fix payment transfer when balance cannot cover amount plus fee"
```

Optional bridge environment variables:
- `LM_BRIDGE_URL` (default `http://127.0.0.1:8765/patch`)
- `LM_BRIDGE_TIMEOUT` (default `90` seconds)

### Auto-Detect mode (Option B)

The VS Code extension now supports a fully automatic command:

- `Copilot LM Bridge: Auto-Detect and Fix Issues`

Flow:
1. Run pytest on the project.
2. Parse failures (`FAILED ...`) and collection errors (`ERROR ...`, `SyntaxError`).
3. Map failing tests to likely source files.
4. Run the standard 7-step pipeline per detected file.
5. Write summary to `outputs/auto_fix_summary.json`.

Recommended workspace settings:

```json
{
  "copilotLmBridge.assemblyLineRoot": "C:/OJT/ai-code-assembly-line",
  "copilotLmBridge.projectRoot": ".",
  "copilotLmBridge.port": 8766,
  "copilotLmBridge.host": "127.0.0.1",
  "copilotLmBridge.pythonCommand": "C:/Users/TuanPDT/AppData/Local/Programs/Python/Python311/python.exe",
  "copilotLmBridge.proxyClientPath": "tools/lm_proxy_http_client.py",
  "copilotLmBridge.autoStart": true,
  "copilotLmBridge.setPythonPath": true,
  "copilotLmBridge.outputDir": "outputs"
}
```

Notes:
- `proxyClientPath` supports relative path, absolute path, and `file:///...` URI values.
- Windows cp1252 terminals are supported by ASCII-only summary markers (`[OK]`, `[REVIEW]`, `[NEEDS_DEV]`).
- If bridge is unavailable, proxy backend falls back to deterministic mock backend.

### Extension single-flow behavior

`Copilot LM Bridge: Run Pipeline Fix For Active File` now follows a strict one-way flow:

1. Run Precheck Gate in extension (workspace, python, bridge health, active file scope).
2. If precheck fails: stop immediately and write `outputs/run_log.json` + `outputs/evidence_report.md` with stage `PRECHECK`.
3. If precheck passes: extension calls Copilot via bridge to generate unified diff.
4. Save patch to `.tmp/copilot_patch.diff`.
5. Invoke Python engine in `external-patch` mode.
6. Read `outputs/run_log.json` and show token saving percent in output.
7. Only when decision is `READY_FOR_HUMAN_REVIEW`, ask user consent before source apply.

### Output artefacts

After a successful run, three files are written to `outputs/`:

| File | Contents |
|------|----------|
| `patch.diff` | The unified diff applied to the target file |
| `evidence_report.md` | Human-readable summary: token stats, attempts, test output |
| `run_log.json` | Machine-readable audit log |

---

## CLI Reference

```
usage: python -m assembly_line.main [-h] --project PROJECT --file FILE --task TASK [--llm-mode {auto,external-patch}] [--patch-file PATCH_FILE] [--output OUTPUT] [--apply-source]

  --project   Path to the target project root
  --file      Relative path to the file to fix (from project root)
  --task      Natural-language description of the fix task
  --llm-mode  Patch source mode: auto or external-patch
  --patch-file Unified diff file path when llm-mode=external-patch
  --output    Directory for evidence artefacts (default: outputs)
  --apply-source Apply validated patch back to source files
```

---

## Development

```powershell
# Run tests directly
python -m pytest demo_project/tests -v

# Debug in VS Code — press F5 (launch.json pre-configured)
```

### Key conventions

- `PYTHONPATH=src` is required for all imports
- Sandbox isolation: `shutil.copytree` → temp dir, cleaned up after run
- Token estimate: `len(text) // 4`
- Comment pruning keeps lines matching `TODO|FIXME|NOTE|IMPORTANT|CHÚ Ý`
- `MAX_ATTEMPTS = 3` in `orchestrator.py`
- Test execution is scoped to the active demo slice: banking runs `tests/test_payment_service.py`, inventory runs `tests/test_inventory_order_flow.py`

---

## Architecture Decision: Why a Mock LLM?

The mock client makes the demo **100% reproducible** — no API keys, no rate limits, no flaky responses. The deterministic two-attempt behaviour cleanly illustrates the self-healing loop without network dependency, which is critical for a live hackathon pitch.

Swapping in a real LLM (OpenAI, Azure OpenAI, Gemini) requires only replacing `mock_client.generate_patch()`.
