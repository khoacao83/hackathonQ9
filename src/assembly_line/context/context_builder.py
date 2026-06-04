import re
from pathlib import Path

# Comments that carry intent — keep them even after pruning
_KEEP_PATTERN = re.compile(r"#.*(TODO|FIXME|NOTE|CHÚ Ý|IMPORTANT)", re.IGNORECASE)


def _prune_source(source: str) -> str:
    """
    Remove noise from source code:
    - Regular inline/standalone comments (but keep TODO/FIXME/NOTE/IMPORTANT)
    - Blank lines
    """
    lines = source.splitlines()
    kept = []
    for line in lines:
        stripped = line.strip()
        # Skip blank lines
        if not stripped:
            continue
        # If line is a pure comment line, only keep if it matches important patterns
        if stripped.startswith("#"):
            if _KEEP_PATTERN.search(line):
                kept.append(line)
            # else: drop pure comment
            continue
        kept.append(line)
    return "\n".join(kept)


def build_context(project_root: str, target_file: str, related_files: list[str]) -> dict:
    """
    Read target file and all related files, build raw and optimized context strings.

    Returns:
        {
            "raw_context": str,
            "optimized_context": str,
            "files_included": list[str],
        }
    """
    target_path = Path(project_root) / target_file
    all_paths = [str(target_path)] + related_files

    sections_raw: list[str] = []
    sections_opt: list[str] = []
    files_included: list[str] = []

    for path in all_paths:
        p = Path(path)
        if not p.exists():
            continue
        source = p.read_text(encoding="utf-8")
        label = p.name
        files_included.append(str(p))

        sections_raw.append(f"# === {label} ===\n{source}")
        sections_opt.append(f"# === {label} ===\n{_prune_source(source)}")

    return {
        "raw_context": "\n\n".join(sections_raw),
        "optimized_context": "\n\n".join(sections_opt),
        "files_included": files_included,
    }
