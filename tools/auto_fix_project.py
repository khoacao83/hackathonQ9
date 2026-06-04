#!/usr/bin/env python3
"""
Auto-detect and fix bugs in a project.

Usage:
    python tools/auto_fix_project.py --project /path/to/project [--output /path/to/outputs]

Flow:
1. Run pytest on entire project
2. Parse test output to extract failing files
3. Group failures by file
4. For each failing file, generate task from test error
5. Call orchestrator.run_pipeline() for each file
6. Collect and report results
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
import urllib.request
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add src to path so we can import assembly_line modules
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from assembly_line.orchestrator import run_pipeline


def _normalize_bridge_health_url(raw_url: str) -> str:
    url = (raw_url or "http://127.0.0.1:8765/patch").strip()
    if url.endswith("/patch"):
        return url[: -len("/patch")] + "/health"
    if url.endswith("/"):
        return url + "health"
    return url + "/health"


def ensure_proxy_backend_ready() -> Tuple[bool, str]:
    """Fail fast when proxy backend is selected but bridge is unreachable."""
    backend = os.environ.get("LLM_BACKEND", "").strip().lower()
    proxy_cmd = os.environ.get("LLM_PROXY_COMMAND", "").strip()
    using_proxy = backend == "proxy_command" or bool(proxy_cmd)
    if not using_proxy:
        return True, ""

    # In auto-fix mode, default to strict behavior to avoid wrong-domain mock patches.
    os.environ.setdefault("ALLOW_MOCK_FALLBACK", "0")

    bridge_url = os.environ.get("LM_BRIDGE_URL", "http://127.0.0.1:8765/patch")
    health_url = _normalize_bridge_health_url(bridge_url)
    try:
        with urllib.request.urlopen(health_url, timeout=3) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        if "ok" not in body:
            return False, f"Bridge health check returned unexpected response: {body}"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return (
            False,
            "Proxy bridge is not reachable. "
            f"Expected health endpoint: {health_url}. Error: {exc}",
        )


def run_pytest(project_root: str) -> Tuple[bool, str]:
    """
    Run pytest on project and return (success: bool, output: str).
    """
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "tests", "-v", "--tb=short"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, f"Error running pytest: {e}"


def normalize_project_relative_path(file_path: str, project_root: str) -> str:
    """Normalize traceback paths and return project-relative POSIX path when possible."""
    normalized_input = file_path.replace("\\", "/")

    try:
        file_resolved = Path(file_path).resolve(strict=False)
        project_resolved = Path(project_root).resolve(strict=False)
        try:
            return file_resolved.relative_to(project_resolved).as_posix()
        except ValueError:
            return file_resolved.as_posix()
    except Exception:
        # Fallback for malformed paths with duplicated separators.
        collapsed = re.sub(r"/{2,}", "/", normalized_input)
        proj = re.sub(r"/{2,}", "/", project_root.replace("\\", "/")).rstrip("/")
        if collapsed.lower().startswith(proj.lower() + "/"):
            return collapsed[len(proj) + 1 :]
        return collapsed


@lru_cache(maxsize=32)
def _list_python_files(project_root: str) -> List[str]:
    files: List[str] = []
    for root, dirs, filenames in os.walk(project_root):
        root_path = root.replace("\\", "/")
        # Skip common non-source directories
        dirs[:] = [
            d
            for d in dirs
            if d not in {".git", ".venv", "venv", "node_modules", "outputs", "__pycache__"}
        ]
        if "/tests" in root_path or root_path.endswith("/tests"):
            continue
        for name in filenames:
            if name.endswith(".py"):
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, project_root).replace("\\", "/")
                files.append(rel_path)
    return files


def _extract_import_candidates(test_abs_path: str) -> Set[str]:
    candidates: Set[str] = set()
    try:
        content = Path(test_abs_path).read_text(encoding="utf-8")
    except OSError:
        return candidates

    # from app.services.payroll_service import PayrollService
    for match in re.findall(r"^\s*from\s+([a-zA-Z_][\w\.]*)\s+import\s+", content, flags=re.M):
        module = match.strip()
        if module.startswith("app.") or module.startswith("src."):
            candidates.add(module.replace(".", "/") + ".py")

    # import app.services.payroll_service as ps
    for match in re.findall(r"^\s*import\s+([a-zA-Z_][\w\.]*)", content, flags=re.M):
        module = match.strip()
        if module.startswith("app.") or module.startswith("src."):
            candidates.add(module.replace(".", "/") + ".py")

    return candidates


def map_test_to_source_files(test_file: str, project_root: str) -> List[str]:
    """Map failing test file to likely source files using imports + filename heuristic."""
    normalized_test = test_file.replace("\\", "/")
    test_abs_path = os.path.join(project_root, normalized_test)
    project_files = _list_python_files(project_root)

    ranked: List[str] = []
    seen: Set[str] = set()

    # 1) Heuristic by filename: test_payroll_service.py -> payroll_service.py
    stem = Path(normalized_test).stem
    module_hint = stem[5:] if stem.startswith("test_") else stem

    by_basename = [p for p in project_files if Path(p).stem == module_hint]
    by_contains = [p for p in project_files if module_hint in Path(p).stem]

    def score(path: str) -> Tuple[int, int, str]:
        # Prefer app/ or src/ and shorter paths
        prefix_score = 0
        if path.startswith("app/"):
            prefix_score = 2
        elif path.startswith("src/"):
            prefix_score = 1
        return (-prefix_score, len(path.split("/")), path)

    for rel in sorted(by_basename, key=score):
        if rel not in seen:
            ranked.append(rel)
            seen.add(rel)

    for rel in sorted(by_contains, key=score):
        if rel not in seen:
            ranked.append(rel)
            seen.add(rel)

    # 2) Then include explicit imports from app./src. modules in test file.
    for rel in _extract_import_candidates(test_abs_path):
        if rel in project_files and rel not in seen:
            ranked.append(rel)
            seen.add(rel)

    # Keep list small to avoid over-fixing unrelated files.
    return ranked[:4]


def _module_hint_from_test_file(test_file: str) -> str:
    stem = Path(test_file.replace("\\", "/")).stem
    return stem[5:] if stem.startswith("test_") else stem


def pick_primary_source_file(source_files: List[str], test_file: str) -> str | None:
    """Pick the most likely target file for this failing test."""
    if not source_files:
        return None

    hint = _module_hint_from_test_file(test_file)

    # Best match: exact module name + service file
    for rel in source_files:
        if Path(rel).stem == hint and rel.endswith("_service.py"):
            return rel

    # Next best: exact module name
    for rel in source_files:
        if Path(rel).stem == hint:
            return rel

    # Then prefer service layer to avoid mapping to broad model/utils first
    for rel in source_files:
        if rel.endswith("_service.py"):
            return rel

    return source_files[0]


def parse_failing_tests(
    pytest_output: str,
    project_root: str,
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """
    Parse pytest output to extract failing test file and error message.
    
    Returns:
    - failing_by_file: {target_file: [error_message_1, ...]}
    - tests_by_file:   {target_file: [tests/test_x.py, ...]}
    """
    failing_by_file = {}
    tests_by_file: Dict[str, Set[str]] = {}
    
    # Collection/syntax errors can happen before FAILURES section exists.
    # Capture absolute/relative file paths from Python tracebacks.
    syntax_error_files = re.findall(r"File \"([^\"]+\.py)\", line \d+", pytest_output)
    syntax_error_msg_match = re.search(r"SyntaxError:\s*(.+)", pytest_output)
    syntax_error_msg = syntax_error_msg_match.group(1).strip() if syntax_error_msg_match else "Collection error"

    for file_path in syntax_error_files:
        rel_path = normalize_project_relative_path(file_path, project_root)
        if rel_path.endswith(".py") and rel_path not in failing_by_file:
            failing_by_file[rel_path] = [f"SyntaxError: {syntax_error_msg}"]
            if rel_path.startswith("tests/"):
                tests_by_file.setdefault(rel_path, set()).add(rel_path)

    # Summary can also contain "ERROR tests/test_foo.py".
    error_tests = re.findall(r"^ERROR\s+(tests[/\\][^\s]+\.py)\s*$", pytest_output, flags=re.M)
    for test_file in error_tests:
        source_files = map_test_to_source_files(test_file, project_root)
        normalized_test_file = test_file.replace("\\", "/")
        error_msg = f"Collection error in {normalized_test_file}"
        primary = pick_primary_source_file(source_files, normalized_test_file)
        if primary:
            if primary not in failing_by_file:
                failing_by_file[primary] = [error_msg]
            tests_by_file.setdefault(primary, set()).add(normalized_test_file)
        else:
            normalized_test = normalized_test_file
            if normalized_test not in failing_by_file:
                failing_by_file[normalized_test] = [error_msg]
            tests_by_file.setdefault(normalized_test, set()).add(normalized_test_file)

    # Extract failing test names from the summary section
    # Pattern: "FAILED tests/test_xxx.py::test_name"
    failing_tests = re.findall(r"FAILED\s+(tests[/\\][^\s:]+\.py)::", pytest_output)

    if not failing_tests:
        return failing_by_file, {k: sorted(v) for k, v in tests_by_file.items()}
    
    # For each failing test file, extract the error messages
    sections = pytest_output.split("=== FAILURES ===")
    if len(sections) < 2:
        # No detailed failures section, just use the test files
        for test_file in failing_tests:
            source_files = map_test_to_source_files(test_file, project_root)
            normalized_test = test_file.replace("\\", "/")
            primary = pick_primary_source_file(source_files, normalized_test)
            if primary and primary not in failing_by_file:
                failing_by_file[primary] = ["Test failure detected"]
                tests_by_file.setdefault(primary, set()).add(normalized_test)
        return failing_by_file, {k: sorted(v) for k, v in tests_by_file.items()}
    
    failures_section = sections[1]
    
    # Split each failure by test name underscores pattern
    failure_blocks = re.split(r"_{5,}", failures_section)
    
    for block in failure_blocks:
        if not block.strip():
            continue
        
        lines = block.strip().split("\n")
        if not lines:
            continue
        
        # Extract error message from this failure block
        error_lines = []
        current_test_file = None
        
        for line in lines:
            # Look for test file reference: "tests/test_xxx.py:NNN: in test_name"
            match = re.search(r"(tests[/\\][^\s:]+\.py):\d+:", line)
            if match:
                current_test_file = match.group(1)
            
            # Collect error lines
            if line.startswith("E "):
                error_text = re.sub(r"^E\s+", "", line).strip()
                if error_text:
                    error_lines.append(error_text)
            elif "AssertionError" in line or "assert" in line:
                error_lines.append(line.strip())
        
        # If we found a test file for this failure block, map it to source files
        if current_test_file:
            source_files = map_test_to_source_files(current_test_file, project_root)
            normalized_test = current_test_file.replace("\\", "/")
            error_msg = " | ".join(error_lines[:2]) if error_lines else "Test failure"
            primary = pick_primary_source_file(source_files, normalized_test)

            if primary:
                if primary not in failing_by_file:
                    failing_by_file[primary] = []
                if error_msg not in failing_by_file[primary]:
                    failing_by_file[primary].append(error_msg)
                tests_by_file.setdefault(primary, set()).add(normalized_test)
    
    # Fallback: if we couldn't extract from failures section, just map all failing tests
    if not failing_by_file:
        for test_file in failing_tests:
            source_files = map_test_to_source_files(test_file, project_root)
            normalized_test = test_file.replace("\\", "/")
            primary = pick_primary_source_file(source_files, normalized_test)
            if primary and primary not in failing_by_file:
                failing_by_file[primary] = ["Test failure detected"]
                tests_by_file.setdefault(primary, set()).add(normalized_test)

    return failing_by_file, {k: sorted(v) for k, v in tests_by_file.items()}


def generate_task_description(errors: List[str]) -> str:
    """
    Generate a task description from test errors.
    
    Example:
        Input: ["AssertionError: assert 950 >= 1100", "balance check failed"]
        Output: "Fix failing test: AssertionError - assert 950 >= 1100"
    """
    error_text = " | ".join(errors)
    # Clean up error text
    error_text = re.sub(r"^[E\s>]*", "", error_text)  # Remove E and > prefixes
    error_text = error_text.strip()
    
    if len(error_text) > 100:
        error_text = error_text[:100] + "..."
    
    return f"Fix failing test: {error_text}"


def _slugify_target_file(target_file: str, index: int) -> str:
    normalized = target_file.replace("\\", "/").strip("/")
    cleaned = re.sub(r"[^a-zA-Z0-9._/-]+", "_", normalized)
    cleaned = cleaned.replace("/", "__")
    return f"{index:02d}_{cleaned or 'unknown'}"


def persist_run_artifacts(output_dir: str, target_file: str, index: int) -> dict:
    """Copy latest run artifacts into a stable per-file folder for later review."""
    per_file_dir = os.path.join(output_dir, "batch_review", _slugify_target_file(target_file, index))
    os.makedirs(per_file_dir, exist_ok=True)

    copied = {
        "artifact_dir": per_file_dir,
        "patch_file": "",
        "evidence_file": "",
        "run_log_file": "",
    }

    mapping = {
        "patch.diff": "patch_file",
        "evidence_report.md": "evidence_file",
        "run_log.json": "run_log_file",
    }

    for src_name, key in mapping.items():
        src = os.path.join(output_dir, src_name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(per_file_dir, src_name)
        shutil.copy2(src, dst)
        copied[key] = dst

    return copied


def main():
    parser = argparse.ArgumentParser(
        description="Auto-detect and fix bugs in a project"
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Path to project root",
    )
    parser.add_argument(
        "--output",
        default="outputs",
        help="Output directory for reports",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=5,
        help="Maximum number of failing files to fix (default: 5)",
    )
    parser.add_argument(
        "--no-apply-source",
        action="store_true",
        help="Do not promote passing patches to source files; keep changes in reports/artifacts for human review.",
    )
    
    args = parser.parse_args()
    
    project_root = os.path.abspath(args.project)
    output_dir = os.path.abspath(args.output)
    
    if not os.path.isdir(project_root):
        print(f"Error: Project directory not found: {project_root}")
        sys.exit(1)
    
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"[Auto-Detect] Starting auto-fix on: {project_root}")

    ready, message = ensure_proxy_backend_ready()
    if not ready:
        print(f"[Auto-Detect] {message}")
        print("[Auto-Detect] Stop here to avoid fallback to demo mock patches.")
        return 1

    print(f"[Auto-Detect] Running pytest...")
    
    # Step 1: Run tests
    success, pytest_output = run_pytest(project_root)
    
    if success:
        print("[Auto-Detect] All tests passed! No fixes needed.")
        return 0
    
    print(f"[Auto-Detect] Tests failed. Parsing output...")
    print(f"[Auto-Detect] Output length: {len(pytest_output)} chars")
    print(f"[Auto-Detect] Has FAILURES section: {'FAILURES' in pytest_output}")
    
    # Debug: save full output to file
    with open(os.path.join(output_dir, "pytest_output.txt"), "w") as f:
        f.write(pytest_output)
    print(f"[Auto-Detect] Full pytest output saved to {output_dir}/pytest_output.txt")
    
    failing_files, tests_by_file = parse_failing_tests(pytest_output, project_root)
    
    if not failing_files:
        print("[Auto-Detect] Could not parse failing tests from output:")
        print(pytest_output[-500:])  # Last 500 chars
        return 1
    
    print(f"[Auto-Detect] Found {len(failing_files)} failing file(s):")
    for file_name in failing_files:
        print(f"  - {file_name}")
    
    # Step 3: Fix each failing file
    results = []
    files_to_fix = list(failing_files.items())[: args.max_files]
    
    for idx, (target_file, errors) in enumerate(files_to_fix, start=1):
        print(f"\n[Auto-Detect] Processing: {target_file}")
        
        task_description = generate_task_description(errors)
        print(f"[Auto-Detect] Task: {task_description}")
        
        try:
            # Call orchestrator pipeline
            test_targets = tests_by_file.get(target_file, ["tests"])
            result_dict = run_pipeline(
                project_root=project_root,
                target_file=target_file,
                task=task_description,
                output_dir=output_dir,
                apply_to_source=not args.no_apply_source,
                test_targets=test_targets,
            )
            
            decision = result_dict["decision"]
            attempts = result_dict["attempts"]
            token_stats = result_dict["token_stats"]
            
            result = {
                "file": target_file,
                "task": task_description,
                "tests": test_targets,
                "decision": decision,
                "attempts": attempts,
                "tokens": token_stats,
                "applied_to_source": bool(result_dict.get("applied_to_source")),
            }
            result.update(persist_run_artifacts(output_dir, target_file, idx))
            results.append(result)
            
            print(f"[Auto-Detect] Result: {decision} (attempts: {attempts})")
            
        except Exception as e:
            print(f"[Auto-Detect] Error processing {target_file}: {e}")
            results.append({
                "file": target_file,
                "task": task_description,
                "decision": "ERROR",
                "error": str(e),
                **persist_run_artifacts(output_dir, target_file, idx),
            })
    
    # Step 4: Report summary
    print("\n" + "=" * 70)
    print("AUTO-DETECT AND FIX SUMMARY")
    print("=" * 70)
    
    summary = {
        "project": project_root,
        "total_failing_files": len(failing_files),
        "processed": len(files_to_fix),
        "results": results,
    }
    
    ready_count = sum(1 for r in results if r.get("decision") == "READY_FOR_HUMAN_REVIEW")
    fixed_count = sum(1 for r in results if r.get("decision") == "READY_FOR_DEPLOYMENT")
    
    print(f"Total failing files detected: {len(failing_files)}")
    print(f"Files processed: {len(files_to_fix)}")
    print(f"  [OK] Ready for deployment: {fixed_count}")
    print(f"  [REVIEW] Ready for review: {ready_count}")
    print(f"  [NEEDS_DEV] Needs developer review: {len(files_to_fix) - ready_count - fixed_count}")
    
    # Save summary
    summary_file = os.path.join(output_dir, "auto_fix_summary.json")
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nFull report: {summary_file}")
    
    return 0 if ready_count + fixed_count == len(files_to_fix) else 1


if __name__ == "__main__":
    sys.exit(main())
