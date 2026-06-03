from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assembly_line.config.policy_loader import load_policy
from assembly_line.context.context_builder import build_context
from assembly_line.context.context_firewall import filter_allowed_files
from assembly_line.context.token_meter import token_saving
from assembly_line.graph.import_scanner import scan_related_files
from assembly_line.llm.factory import create_llm_client
from assembly_line.patch.patch_validator import validate_patch
from assembly_line.patch.unified_diff_applier import apply_unified_diff
from assembly_line.report.evidence_report import write_outputs
from assembly_line.sandbox.test_runner import extract_short_error, run_pytest


@dataclass
class PipelineConfig:
    max_attempts: int | None = None
    import_depth: int | None = None
    sandbox_dir: str = ".sandbox_workdir"
    test_timeout_seconds: int | None = None
    policy_path: str = "configs/policy.yaml"
    use_docker: bool | None = None
    strict_docker: bool | None = None
    docker_image: str | None = None
    docker_network: str | None = None
    docker_memory: str | None = None
    docker_cpus: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_mode: str | None = None
    patch_file: str | None = None


def prepare_sandbox(project_root: str, sandbox_dir: str) -> str:
    source = Path(project_root).resolve()
    sandbox = Path(sandbox_dir).resolve()

    if not source.exists():
        raise FileNotFoundError(f"Project root not found: {source}")

    if sandbox.exists():
        shutil.rmtree(sandbox)

    ignore = shutil.ignore_patterns(
        "__pycache__",
        ".pytest_cache",
        ".venv",
        "venv",
        ".git",
    )

    shutil.copytree(source, sandbox, ignore=ignore)
    return str(sandbox)


def run_pipeline(
    project_root: str,
    target_file: str,
    task: str,
    output_dir: str = "outputs",
    config: PipelineConfig | None = None,
) -> dict:
    config = config or PipelineConfig()
    policy = load_policy(config.policy_path)
    sandbox_policy = policy.get("sandbox", {})
    context_policy = policy.get("context", {})
    llm_policy = policy.get("llm", {})
    report_policy = policy.get("report", {})

    max_attempts = (
        config.max_attempts
        if config.max_attempts is not None
        else int(sandbox_policy.get("max_self_heal_attempts", 3))
    )
    import_depth = (
        config.import_depth
        if config.import_depth is not None
        else int(context_policy.get("import_depth", 1))
    )
    test_timeout_seconds = (
        config.test_timeout_seconds
        if config.test_timeout_seconds is not None
        else int(sandbox_policy.get("test_timeout_seconds", 30))
    )
    use_docker = (
        config.use_docker
        if config.use_docker is not None
        else bool(sandbox_policy.get("use_docker", False))
    )
    strict_docker = (
        config.strict_docker
        if config.strict_docker is not None
        else bool(sandbox_policy.get("strict_docker", False))
    )
    docker_image = config.docker_image or str(
        sandbox_policy.get("docker_image", "ai-code-sandbox:py311")
    )
    docker_network = config.docker_network or str(sandbox_policy.get("docker_network", "none"))
    docker_memory = config.docker_memory or str(sandbox_policy.get("docker_memory", "512m"))
    docker_cpus = config.docker_cpus or str(sandbox_policy.get("docker_cpus", "1.0"))

    llm_provider = config.llm_provider or str(llm_policy.get("provider", "mock"))
    llm_model = config.llm_model or str(llm_policy.get("model", ""))
    llm_base_url = config.llm_base_url or str(llm_policy.get("base_url", ""))
    llm_mode = config.llm_mode or str(llm_policy.get("mode", "provider"))
    patch_file = config.patch_file

    if llm_mode == "external-patch":
        max_attempts = 1

    keep_comment_keywords = set(context_policy.get("keep_comment_keywords", []))
    max_file_chars = int(context_policy.get("max_file_chars", 50000))
    deny_regex = list(context_policy.get("deny_regex", []))

    print("AI Code Assembly Line - Advanced MVP")
    print("=" * 48)

    print("[1/7] Preparing sandbox")
    sandbox_root = prepare_sandbox(project_root, config.sandbox_dir)
    print(f"      Sandbox: {sandbox_root}")

    print("[2/7] Scanning related files")
    related_files = scan_related_files(
        project_root=sandbox_root,
        target_file=target_file,
        depth=import_depth,
    )

    related_files, excluded_files = filter_allowed_files(related_files, policy)

    for file in related_files:
        print(f"      - {file}")

    for item in excluded_files:
        print(f"      excluded: {item['file']} ({item['reason']})")

    print("[3/7] Building optimized context")
    contexts = build_context(
        project_root=sandbox_root,
        files=related_files,
        keep_comment_keywords=keep_comment_keywords,
        max_file_chars=max_file_chars,
        deny_regex=deny_regex,
    )

    metrics = token_saving(
        contexts["raw_context"],
        contexts["optimized_context"],
    )

    print(f"      Raw tokens:       {metrics['raw_tokens']}")
    print(f"      Optimized tokens: {metrics['optimized_tokens']}")
    print(f"      Saved:            {metrics['saved_percent']}%")

    llm = create_llm_client(
        mode=llm_mode,
        patch_file=patch_file,
        provider=llm_provider,
        model=llm_model,
        base_url=llm_base_url,
    )

    final_status = "failed"
    final_patch = ""
    changed_files: list[str] = []
    last_error_summary: list[str] = []
    last_test_output = ""
    attempts_used = 0

    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt

        if attempt == 1:
            print("[4/7] Generating initial patch")
        else:
            print(f"[6/7] Self-healing attempt {attempt - 1}/{max_attempts - 1}")

        patch_text = llm.generate_patch(
            task=task,
            context=contexts["optimized_context"],
            error_summary=last_error_summary or None,
        )

        final_patch = patch_text

        validation = validate_patch(patch_text=patch_text, policy=policy)
        if not validation.valid:
            print("      Patch validation failed")
            for err in validation.errors:
                print(f"      - {err}")
            last_error_summary = validation.errors
            continue

        print("      Applying patch")
        changed_files = apply_unified_diff(sandbox_root, patch_text)

        for file in changed_files:
            print(f"      changed: {file}")

        print("[5/7] Running tests")
        test_result = run_pytest(
            sandbox_root,
            timeout_seconds=test_timeout_seconds,
            use_docker=use_docker,
            strict_docker=strict_docker,
            docker_image=docker_image,
            docker_network=docker_network,
            docker_memory=docker_memory,
            docker_cpus=docker_cpus,
        )

        last_test_output = test_result["output"]

        if test_result["passed"]:
            final_status = "passed"
            print("      Result: PASSED")
            break

        print("      Result: FAILED")

        last_error_summary = extract_short_error(test_result["output"])
        print("      Error summary:")
        for line in last_error_summary:
            print(f"      - {line}")

    print("[7/7] Generating evidence report")
    output_payload: dict[str, Any] = {
        "engine": {
            "llm_provider": llm_provider,
            "llm_mode": llm_mode,
            "use_docker": use_docker,
            "docker_image": docker_image,
            "patch_file": patch_file,
        }
    }

    output_paths = write_outputs(
        output_dir=output_dir,
        task=task,
        target_file=target_file,
        related_files=related_files,
        token_metrics=metrics,
        changed_files=changed_files,
        final_status=final_status,
        attempts_used=attempts_used,
        last_error_summary=last_error_summary,
        patch_text=final_patch,
        last_test_output=last_test_output,
        max_attempts=max_attempts,
        extra=output_payload,
    )

    decision = (
        str(report_policy.get("final_pass_decision", "READY_FOR_HUMAN_REVIEW"))
        if final_status == "passed"
        else str(report_policy.get("final_fail_decision", "NEED_DEVELOPER_REVIEW"))
    )

    print()
    print("=" * 48)
    print(f"Final status:   {final_status.upper()}")
    print(f"Final decision: {decision}")
    print(f"Report:         {output_paths['report']}")

    return {
        "status": final_status,
        "decision": decision,
        "outputs": output_paths,
        "changed_files": changed_files,
        "attempts_used": attempts_used,
    }