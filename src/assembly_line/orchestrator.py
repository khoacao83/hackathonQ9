"""
Central coordinator of the AI Code Assembly Line pipeline.

Pipeline steps:
  [1/7] Preparing sandbox
  [2/7] Scanning related files
  [3/7] Building optimized context
  [4/7] Generating patch (LLM)
  [5/7] Running tests
  [6/7] Self-healing  (up to MAX_ATTEMPTS times)
  [7/7] Generating evidence report
"""
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from assembly_line.graph.import_scanner import scan_related_files
from assembly_line.context.context_builder import build_context
from assembly_line.context.context_firewall import filter_related_files
from assembly_line.context.token_meter import estimate_tokens, token_saving_percent
from assembly_line.patch.patch_applier import apply_demo_patch
from assembly_line.patch.patch_validator import validate_patch
from assembly_line.report.evidence_report import write_report

# ── LLM backend selection ────────────────────────────────────────────────────
# Priority order:
# 1. LLM_PROXY_COMMAND / LLM_BACKEND=proxy_command -> local bridge command
# 2. GITHUB_TOKEN / LLM_BACKEND=copilot_api       -> Copilot Enterprise API
# 3. fallback                                      -> deterministic mock
llm_backend = os.environ.get("LLM_BACKEND", "").strip().lower()
proxy_command = os.environ.get("LLM_PROXY_COMMAND", "").strip()

if llm_backend == "proxy_command" or proxy_command:
    from assembly_line.llm.proxy_client import generate_patch
elif llm_backend == "copilot_api" or os.environ.get("GITHUB_TOKEN", "").strip():
    from assembly_line.llm.copilot_client import generate_patch
else:
    from assembly_line.llm.mock_client import generate_patch  # type: ignore[assignment]

# ── Sandbox backend selection ────────────────────────────────────────────────
# Local runner by default. Set USE_DOCKER=1 to opt into Docker sandbox.
# docker_runner still falls back to local when Docker is unavailable
# (unless SANDBOX_STRICT=1).
if os.environ.get("USE_DOCKER", "0").strip() != "0":
    from assembly_line.sandbox.docker_runner import run_pytest, extract_short_error  # type: ignore[assignment]
else:
    from assembly_line.sandbox.test_runner import run_pytest, extract_short_error  # type: ignore[assignment]

MAX_ATTEMPTS = 3


def _read_policy(path: str) -> dict[str, Any]:
    """Read YAML policy file; return empty config when unavailable/invalid."""
    try:
        import yaml  # type: ignore
    except Exception:  # noqa: BLE001
        return {}

    policy_path = Path(path)
    if not policy_path.exists():
        return {}

    try:
        loaded = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _policy_get(policy: dict[str, Any], keys: tuple[str, ...], default: Any) -> Any:
    current: Any = policy
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def select_test_targets(target_file: str) -> list[str]:
    """
    Select the narrowest pytest target for the requested demo slice.
    Falls back to the full tests directory when the target is unknown.
    """
    normalized = target_file.replace("\\", "/")
    if "/banking/" in f"/{normalized}":
        return ["tests/test_payment_service.py"]
    if "/inventory/" in f"/{normalized}":
        return ["tests/test_inventory_order_flow.py"]
    return ["tests"]


def prepare_sandbox(project_root: str) -> str:
    """
    Copy the entire project_root into a temporary directory and return its path.
    The sandbox is isolated so patches never touch the real source.
    """
    sandbox = tempfile.mkdtemp(prefix="aic_sandbox_")
    shutil.copytree(project_root, sandbox, dirs_exist_ok=True)
    return sandbox


def _expand_allowed_files(project_root: str, test_output: str, allowed_files: list[str]) -> None:
    """
    Parse test output for File "..." traceback lines and add any project source
    files mentioned there (that are not already allowed) to allowed_files in-place.
    This lets the model fix cascading SyntaxErrors in dependencies during self-healing.
    """
    import re as _re
    project_resolved = Path(project_root).resolve()
    for abs_path in _re.findall(r'File "([^"]+\.py)"', test_output):
        try:
            rel = Path(abs_path).resolve().relative_to(project_resolved).as_posix()
        except ValueError:
            continue
        if rel.startswith("tests/") or rel in allowed_files:
            continue
        if (project_resolved / rel).exists():
            allowed_files.append(rel)


def run_pipeline(
    project_root: str,
    target_file: str,
    task: str,
    output_dir: str = "outputs",
    apply_to_source: bool = False,
    test_targets: list[str] | None = None,
    llm_mode: str = "auto",
    patch_file: str = "",
) -> dict[str, Any]:
    """
    Execute the full 7-step assembly line pipeline.
    """
    project_root = project_root.strip()
    target_file = target_file.strip()
    task = task.strip()
    output_dir = output_dir.strip()
    llm_mode = llm_mode.strip().lower() or "auto"
    patch_file = patch_file.strip()

    policy_file = os.environ.get("POLICY_FILE", "configs/policy.yaml").strip()
    policy = _read_policy(policy_file)

    max_attempts = _as_int(
        os.environ.get("MAX_ATTEMPTS", _policy_get(policy, ("pipeline", "max_attempts"), MAX_ATTEMPTS)),
        MAX_ATTEMPTS,
    )
    graph_depth = _as_int(
        os.environ.get("GRAPH_MAX_DEPTH", _policy_get(policy, ("graph", "max_depth"), 1)),
        1,
    )
    test_timeout = _as_int(
        os.environ.get("TEST_TIMEOUT_SECONDS", _policy_get(policy, ("sandbox", "test_timeout_seconds"), 120)),
        120,
    )
    docker_timeout = _as_int(
        os.environ.get(
            "DOCKER_TEST_TIMEOUT_SECONDS",
            _policy_get(policy, ("sandbox", "docker_test_timeout_seconds"), test_timeout),
        ),
        test_timeout,
    )
    sandbox_strict = _as_bool(
        os.environ.get("SANDBOX_STRICT", _policy_get(policy, ("sandbox", "strict_mode"), False)),
        False,
    )
    pass_label = str(
        os.environ.get("PASS_LABEL", _policy_get(policy, ("decisions", "pass_label"), "READY_FOR_HUMAN_REVIEW"))
    )
    fail_label = str(
        os.environ.get("FAIL_LABEL", _policy_get(policy, ("decisions", "fail_label"), "NEED_DEVELOPER_REVIEW"))
    )

    # Keep backends in sync with policy-driven values.
    os.environ["DOCKER_TEST_TIMEOUT_SECONDS"] = str(docker_timeout)
    if sandbox_strict:
        os.environ["SANDBOX_STRICT"] = "1"
    elif os.environ.get("SANDBOX_STRICT", "").strip() == "":
        os.environ["SANDBOX_STRICT"] = "0"

    # ── [1/7] Prepare sandbox ────────────────────────────────────────────────
    print("[1/7] Preparing sandbox")
    sandbox = prepare_sandbox(project_root)

    # ── [2/7] Scan related files ─────────────────────────────────────────────
    print("[2/7] Scanning related files")
    related_scanned = scan_related_files(project_root, target_file, max_depth=graph_depth)
    related, blocked_related = filter_related_files(project_root, target_file, related_scanned, policy)
    print(f"       Graph depth: {max(1, graph_depth)}")
    print(f"       Found {len(related)} related file(s): {[Path(p).name for p in related]}")
    if blocked_related:
        print(f"       Blocked by context firewall: {blocked_related}")

    # ── [3/7] Build optimized context ────────────────────────────────────────
    print("[3/7] Building optimized context")
    ctx = build_context(project_root, target_file, related)
    raw_tokens = estimate_tokens(ctx["raw_context"])
    opt_tokens = estimate_tokens(ctx["optimized_context"])
    saving = token_saving_percent(ctx["raw_context"], ctx["optimized_context"])
    print(f"       Tokens: raw={raw_tokens}  optimized={opt_tokens}  saving={saving}%")
    token_stats = {
        "raw_tokens": raw_tokens,
        "opt_tokens": opt_tokens,
        "saving_pct": saving,
    }

    # ── [4/7 ... 6/7] Generate patch -> test -> self-heal loop ───────────────────
    patch_text: str = ""
    changed_files: list[str] = []
    promoted_files: list[str] = []
    test_result: dict = {}
    error_feedback: str = ""
    attempt = 0
    selected_test_targets = test_targets if test_targets else select_test_targets(target_file)
    allowed_files: list[str] = [target_file]

    if llm_mode == "external-patch":
        if not patch_file:
            raise ValueError("--patch-file is required when --llm-mode external-patch")
        patch_path = Path(patch_file)
        if not patch_path.is_absolute():
            cwd_candidate = (Path.cwd() / patch_path).resolve()
            project_candidate = (Path(project_root) / patch_path).resolve()
            patch_path = cwd_candidate if cwd_candidate.exists() else project_candidate
        if not patch_path.exists():
            raise FileNotFoundError(f"Patch file not found: {patch_path}")
        patch_text = patch_path.read_text(encoding="utf-8")
        # External patch mode validates a provided patch file, so retries are not useful.
        max_attempts = 1

    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            print("[4/7] Generating patch")
        else:
            print(f"[6/7] Self-healing attempt {attempt - 1}/{max_attempts - 1}")

        if llm_mode == "external-patch":
            if attempt == 1:
                print("       Using external patch from file")
        else:
            patch_text = generate_patch(
                task=task,
                context=ctx["raw_context"],
                attempt=attempt,
                error_feedback=error_feedback,
                target_file=target_file,
                related_files=related,
            )

        # Apply patch to sandbox. If apply fails, feed it back to the model
        # for the next self-heal attempt instead of crashing the run.
        try:
            related_rel: list[str] = []
            for rel in related:
                try:
                    related_rel.append(Path(rel).resolve().relative_to(Path(project_root).resolve()).as_posix())
                except Exception:  # noqa: BLE001
                    continue

            target_dir = (Path(target_file).parent.as_posix() if Path(target_file).parent.as_posix() != "." else "")
            sibling_rel: list[str] = []
            if target_dir:
                sibling_dir = Path(project_root) / target_dir
                if sibling_dir.exists() and sibling_dir.is_dir():
                    for p in sibling_dir.glob("*.py"):
                        try:
                            sibling_rel.append(p.resolve().relative_to(Path(project_root).resolve()).as_posix())
                        except Exception:  # noqa: BLE001
                            continue

            allowed_files = [target_file] + related_rel + sibling_rel

            ok, reason, _targets = validate_patch(
                patch_text=patch_text,
                project_root=project_root,
                allowed_files=allowed_files,
                policy=policy,
            )
            if not ok:
                raise RuntimeError(f"Patch validation failed: {reason}")

            changed_files = apply_demo_patch(sandbox, patch_text, allowed_files=allowed_files)
        except Exception as exc:  # noqa: BLE001
            error_feedback = f"Patch apply failed: {exc}"
            print(f"[5/7] Running tests -> Result: FAILED ({error_feedback})")
            test_result = {"passed": False, "output": error_feedback}
            continue

        # Run tests
        print("[5/7] Running tests", end=" -> ", flush=True)
        test_result = run_pytest(sandbox, selected_test_targets, test_timeout)

        if test_result["passed"]:
            print("Result: PASSED")
            break
        else:
            errors = extract_short_error(test_result["output"])
            error_feedback = "\n".join(errors)
            print(f"Result: FAILED ({error_feedback})")
            # Expand allowed_files if error mentions a project source file not yet allowed.
            _expand_allowed_files(project_root, test_result["output"], allowed_files)
    else:
        # All attempts exhausted
        pass

    # ── [7/7] Evidence report ────────────────────────────────────────────────
    if test_result.get("passed") and apply_to_source:
        try:
            promoted_files = apply_demo_patch(project_root, patch_text, allowed_files=allowed_files)
            if promoted_files:
                print(f"[7/7] Promoted patch to source ({len(promoted_files)} file(s))")
            else:
                print("[7/7] Promote to source completed (no concrete file list from diff parser)")
        except Exception as exc:  # noqa: BLE001
            test_result = {
                "passed": False,
                "output": f"Source apply failed after sandbox pass: {exc}",
            }

    print("[7/7] Generating evidence report")
    decision = pass_label if test_result.get("passed") else fail_label

    paths = write_report(
        output_dir=output_dir,
        task=task,
        target_file=target_file,
        patch_text=patch_text,
        changed_files=promoted_files or changed_files,
        attempts=attempt,
        token_stats=token_stats,
        test_output=test_result.get("output", ""),
        decision=decision,
    )

    print(f"\nFinal decision: {decision}")
    print(f"  patch.diff       -> {paths['diff']}")
    print(f"  evidence_report  -> {paths['report']}")
    print(f"  run_log          -> {paths['log']}")

    # Clean up sandbox
    shutil.rmtree(sandbox, ignore_errors=True)

    return {
        "decision": decision,
        "attempts": attempt,
        "max_attempts": max_attempts,
        "paths": paths,
        "test_passed": bool(test_result.get("passed")),
        "token_stats": token_stats,
        "applied_to_source": bool(promoted_files),
    }
