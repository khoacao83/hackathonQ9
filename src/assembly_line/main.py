from __future__ import annotations

import argparse

from assembly_line.orchestrator import PipelineConfig, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AI Code Assembly Line - Advanced MVP",
    )

    parser.add_argument(
        "--project",
        required=True,
        help="Path to project root, e.g. demo_project",
    )

    parser.add_argument(
        "--file",
        required=True,
        help="Target file relative to project root",
    )

    parser.add_argument(
        "--task",
        required=True,
        help="User coding task",
    )

    parser.add_argument(
        "--output",
        default="outputs",
        help="Output directory",
    )

    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="Maximum self-healing attempts",
    )

    parser.add_argument(
        "--import-depth",
        type=int,
        default=None,
        help="Import graph scan depth",
    )

    parser.add_argument(
        "--policy",
        default="configs/policy.yaml",
        help="Policy YAML path",
    )

    parser.add_argument(
        "--use-docker",
        action="store_true",
        help="Run tests in Docker sandbox",
    )

    parser.add_argument(
        "--strict-docker",
        action="store_true",
        help="Fail pipeline if Docker is unavailable",
    )

    parser.add_argument(
        "--docker-image",
        default=None,
        help="Docker image for sandbox test execution",
    )

    parser.add_argument(
        "--llm-provider",
        default=None,
        help="LLM provider: mock or api",
    )

    parser.add_argument(
        "--llm-mode",
        default=None,
        help="LLM mode: mock | provider | api | external-patch",
    )

    parser.add_argument(
        "--patch-file",
        default=None,
        help="Path to unified diff patch file when llm-mode=external-patch",
    )

    parser.add_argument(
        "--llm-model",
        default=None,
        help="LLM model name",
    )

    parser.add_argument(
        "--llm-base-url",
        default=None,
        help="Base URL for OpenAI-compatible LLM API",
    )

    parser.add_argument(
        "--sandbox-dir",
        default=".sandbox_workdir",
        help="Sandbox working directory",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = PipelineConfig(
        max_attempts=args.max_attempts,
        import_depth=args.import_depth,
        sandbox_dir=args.sandbox_dir,
        policy_path=args.policy,
        use_docker=args.use_docker,
        strict_docker=args.strict_docker,
        docker_image=args.docker_image,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
        llm_mode=args.llm_mode,
        patch_file=args.patch_file,
    )

    run_pipeline(
        project_root=args.project,
        target_file=args.file,
        task=args.task,
        output_dir=args.output,
        config=config,
    )


if __name__ == "__main__":
    main()