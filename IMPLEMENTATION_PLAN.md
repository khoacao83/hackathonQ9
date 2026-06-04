# AI Code Assembly Line — Implementation Plan

> **Hackathon deadline: 15:30, June 4, 2026**
> **Tech Lead: Nguyên** | Team: Nguyên, Khoa, Tuấn
> **Cập nhật lần cuối: June 3, 2026**

---

## Một câu chốt

> *We do not build another coding assistant. We build a control layer around AI-generated code. Every AI patch must pass context control, sandbox verification, self-healing, and evidence reporting before human review.*

---

## Trạng thái hiện tại (June 3, 2026)

| Module | Trạng thái | Ghi chú |
|--------|-----------|---------|
| `main.py` | ✅ Done | CLI entry point |
| `orchestrator.py` | ✅ Done | 7-step pipeline + self-healing loop |
| `graph/import_scanner.py` | ✅ Done | AST 1-hop scan |
| `context/context_builder.py` | ✅ Done | Prune + build context |
| `context/token_meter.py` | ✅ Done | Token estimate `len // 4` |
| `llm/mock_client.py` | ✅ Done | Structured prompt + deterministic response |
| `llm/proxy_client.py` | ✅ Done | Proxy-command backend for local bridge integration |
| `patch/patch_applier.py` | ✅ Done | Apply patch to sandbox |
| `sandbox/test_runner.py` | ✅ Done | Run pytest, extract error |
| `sandbox` test scoping | ✅ Done | Run only the relevant test slice for the selected demo file |
| `report/evidence_report.py` | ✅ Done | patch.diff + evidence_report.md + run_log.json |
| `mcp/filesystem_mcp.py` | ✅ Done | File System MCP mock |
| `mcp/codegraph_mcp.py` | ✅ Done | Code Graph MCP mock |
| `mcp/sandbox_mcp.py` | ✅ Done | Sandbox MCP mock |
| `demo_project/` | ✅ Done | Banking + inventory demo domains with isolated failing scenarios |
| `.github/prompts/` | ✅ Done | 4 skill prompt files |
| `configs/policy.yaml` | ✅ Done | Pipeline policy config |
| `README.md` | ✅ Done | Full documentation |
| `llm/copilot_client.py` | ✅ Done | Real Copilot Enterprise API (falls back to mock if no token) |
| `tools/copilot-lm-bridge-extension/` | ✅ Done | VS Code Language Model bridge extension |
| `tools/lm_proxy_http_client.py` | ✅ Done | HTTP command client for `LLM_PROXY_COMMAND` |
| `sandbox/docker_runner.py` | ✅ Done | Docker sandbox (falls back to local if Docker unavailable) |
| `tools/auto_fix_project.py` | ✅ Done | Auto-detect failing files from pytest + auto-run pipeline |
| Extension auto-detect command | ✅ Done | `Copilot LM Bridge: Auto-Detect and Fix Issues` |
| Generic pytest error parser | ✅ Done | Handles `FAILED`, `ERROR`, and `SyntaxError` collection failures |
| `patch/patch_applier.py` fallback | ✅ Done | Pure-Python unified diff apply if git is unavailable |
| Windows compatibility fixes | ✅ Done | ASCII output for cp1252, robust proxy path resolution |
| **End-to-end banking demo run** | ✅ **VERIFIED** | mock and proxy-command paths validated |

---

## Phân công theo người

### Nguyên (Tech Lead)
- [x] `orchestrator.py` — 7-step pipeline coordinator + env-var backend switching
- [x] `main.py` — CLI entry point
- [x] Unified prompt format (`_build_prompt` trong `mock_client.py`)
- [x] `.github/copilot-instructions.md` — global system context
- [x] VS Code tasks + launch config
- [x] `README.md`
- [x] `IMPLEMENTATION_PLAN.md` (file này)
- [x] `llm/copilot_client.py` — real Copilot Enterprise API (tự fallback về mock)
- [x] `llm/proxy_client.py` — proxy command backend
- [x] `tools/copilot-lm-bridge-extension/` — VS Code Language Model API bridge
- [x] `sandbox/docker_runner.py` — Docker sandbox runner (tự fallback về local)
- [x] `tools/auto_fix_project.py` — auto-detect lỗi từ pytest và fix theo batch
- [x] Bridge extension command `autoDetectFix` + path fallback (`relative`/`absolute`/`file:///`)
- [x] Windows cp1252-safe summary output
- [ ] **Slide pitch** — còn lại

### Khoa
- [x] `import_scanner.py` — AST 1-hop code graph
- [x] `context_builder.py` + `token_meter.py`
- [x] `mcp/codegraph_mcp.py` — Code Graph MCP mock
- [x] `.github/prompts/context-analyst.prompt.md`

### Tuấn
- [x] `test_runner.py` — sandbox pytest runner
- [x] `evidence_report.py` — audit trail
- [x] `mcp/sandbox_mcp.py` — Sandbox MCP mock
- [x] `.github/prompts/test-verifier.prompt.md`
- [x] `.github/prompts/evidence-reporter.prompt.md`

---

## Roadmap còn lại đến deadline

### Phase 1 — Polish (June 3, còn hôm nay)

| Việc | Người | Ưu tiên |
|------|-------|---------|
| Viết slide pitch (5–7 slides) | Nguyên | 🔴 |
| `llm/copilot_client.py` real API | Nguyên | ✅ Done |
| `sandbox/docker_runner.py` Docker | Nguyên | ✅ Done |
| Auto-detect command cho project bất kỳ | Nguyên | ✅ Done |
| Sửa parser pytest collection error (`ERROR`/`SyntaxError`) | Nguyên | ✅ Done |
| Fix apply patch khi thiếu git trên Windows | Nguyên | ✅ Done |
| Chạy demo thử 3–5 lần để quen | Cả nhóm | 🔴 |

### Phase 2 — Nice-to-have (June 4, nếu còn thời gian)

| Việc | Người | Ưu tiên |
|------|-------|---------|
| JSON trace mỗi pipeline step | Tuấn | 🟡 |
| `policy.yaml` đọc thật vào orchestrator | Nguyên | 🟡 |
| Thêm 1 demo case thứ 2 (file khác) | Khoa | ✅ Done |
| Package/install bridge extension | Nguyên | ✅ Done |

### Không làm

- GitHub PR automation
- MCP chuẩn đầy đủ

---

## Demo Script (chuẩn bị cho pitch)

### Setup (chỉ làm 1 lần)
```powershell
cd "c:\Users\NguyenTK14\ai-code-assembly-line"
.venv\Scripts\Activate.ps1
```

### Reset về trạng thái buggy (trước mỗi demo)
```powershell
# Không cần — demo_project không bao giờ bị sửa (sandbox isolation)
```

### Chạy demo
```powershell
$env:PYTHONPATH = "src"
$env:LLM_BACKEND = "proxy_command"
$env:LLM_PROXY_COMMAND = "python tools/lm_proxy_http_client.py"
python -m assembly_line.main `
  --project demo_project `
  --file "app/banking/payment_service.py" `
  --task "Fix payment transfer when balance cannot cover amount plus fee"
```

### Output kỳ vọng (giải thích cho judge)
```
[1/7] Preparing sandbox         ← copy sang temp dir, source không bị đụng
[2/7] Scanning related files    ← AST scan, tìm account_store.py + fee_calculator.py
[3/7] Building optimized context← prune comment, tiết kiệm token
[4/7] Generating patch          ← AI nhận structured prompt, trả unified diff
[5/7] Running tests → FAILED    ← patch đầu chỉ check balance với amount hoặc fee riêng lẻ
[6/7] Self-healing attempt 1/2  ← nhận error, gửi lại AI
[5/7] Running tests → PASSED    ← AI fix đúng bằng `amount + fee`
[7/7] Generating evidence report← ghi audit trail

Final decision: READY_FOR_HUMAN_REVIEW
```

### Sau demo — mở evidence report
```powershell
Get-Content outputs\evidence_report.md
```

---

## Cấu trúc Slide Pitch (đề xuất)

| Slide | Nội dung |
|-------|----------|
| 1 | **Title** — "AI Code Assembly Line" + tagline câu chốt |
| 2 | **Problem** — AI code: hallucination, no audit, no self-correction |
| 3 | **Solution** — 4 gates: Context → Patch → Test → Evidence |
| 4 | **Architecture** — diagram 7-step pipeline |
| 5 | **Demo** — live terminal hoặc screenshot output |
| 6 | **Evidence** — mở `evidence_report.md`, show audit trail |
| 7 | **Closing** — "We don't build AI. We control it." + next steps |

---

## Câu trả lời cho judge hay hỏi

**"System prompt của nhóm là gì?"**
> AI is not allowed to directly change the enterprise codebase. It can only propose a minimal patch based on optimized context. The patch must be applied in sandbox, verified by tests, and recorded in an evidence report. If tests fail, the system extracts a short error summary and allows at most 3 self-healing attempts. If still failing, the patch is rejected and escalated to developer review.

**"Tại sao dùng mock LLM?"**
> Mock makes demo 100% reproducible — no API keys, no rate limits, no flaky responses. Swapping in a real LLM requires only replacing `mock_client.generate_patch()`.

**"Không có API key thì dùng gì?"**
> Dùng VS Code Language Model API bridge: extension chạy trong VS Code gọi Copilot model, còn Python CLI gọi `tools/lm_proxy_http_client.py` qua `LLM_PROXY_COMMAND`.

**"Self-healing hoạt động thế nào?"**
> Test runner captures pytest output → `extract_short_error()` lấy 3 dòng lỗi quan trọng nhất → feed vào prompt `ERROR SUMMARY IF ANY` → AI nhận được lỗi cụ thể và sinh patch đúng hơn.

**"Demo hiện sửa file nào?"**
> Demo mặc định hiện tại dùng `demo_project/app/banking/payment_service.py`. Hệ thống sẽ chỉ chạy test slice tương ứng là `tests/test_payment_service.py` để tránh unrelated failing scenarios chặn kết quả của patch đang được đánh giá.

**"Sandbox isolation là gì?"**
> `shutil.copytree` copy toàn bộ project vào `tempfile.mkdtemp()`. Tất cả patch chỉ apply vào bản copy đó. Source gốc không bao giờ bị đụng. Sau khi xong, sandbox bị xóa.
