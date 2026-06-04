import argparse
from assembly_line.orchestrator import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Code Assembly Line MVP")
    parser.add_argument("--project", required=True, help="Path to the target project root")
    parser.add_argument("--file", required=True, help="Relative path to the file to fix (from project root)")
    parser.add_argument("--task", required=True, help="Natural-language description of the fix task")
    parser.add_argument(
        "--llm-mode",
        default="auto",
        choices=["auto", "external-patch"],
        help="LLM mode: auto (default backends) or external-patch (read patch from file).",
    )
    parser.add_argument(
        "--patch-file",
        default="",
        help="Path to unified diff patch file used when --llm-mode external-patch.",
    )
    parser.add_argument("--output", default="outputs", help="Directory to write evidence artefacts (default: outputs)")
    parser.add_argument(
        "--apply-source",
        action="store_true",
        help="If set, apply the final passing patch back to the real project source.",
    )
    args = parser.parse_args()

    run_pipeline(
        project_root=args.project,
        target_file=args.file,
        task=args.task,
        output_dir=args.output,
        apply_to_source=args.apply_source,
        llm_mode=args.llm_mode,
        patch_file=args.patch_file,
    )


if __name__ == "__main__":
    main()
