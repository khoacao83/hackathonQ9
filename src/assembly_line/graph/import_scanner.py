import ast
import re
from collections import deque
from pathlib import Path


def module_to_path(module_name: str, project_root: str) -> str | None:
    """
    Convert a dotted module name (e.g. 'app.utils.excel_helper')
    to a file path relative to project_root.
    Returns the absolute path if found, else None.
    """
    parts = module_name.split(".")
    candidate = Path(project_root) / Path(*parts).with_suffix(".py")
    if candidate.exists():
        return str(candidate)
    # Also try as package __init__.py
    pkg = Path(project_root) / Path(*parts) / "__init__.py"
    if pkg.exists():
        return str(pkg)
    return None


def _relative_module_to_path(
    source_file: Path,
    module_name: str,
    level: int,
    project_root: str,
) -> str | None:
    """Resolve relative import module path from a source file."""
    base = source_file.parent
    for _ in range(max(level - 1, 0)):
        base = base.parent

    candidate_base = base / Path(*module_name.split(".")) if module_name else base
    file_candidate = candidate_base.with_suffix(".py")
    if file_candidate.exists() and str(file_candidate).startswith(str(Path(project_root).resolve())):
        return str(file_candidate)

    pkg_candidate = candidate_base / "__init__.py"
    if pkg_candidate.exists() and str(pkg_candidate).startswith(str(Path(project_root).resolve())):
        return str(pkg_candidate)

    return None


def _scan_one_file_regex(source: str, file_path: Path, project_root: str) -> list[str]:
    """Regex-based fallback import scanner for files that can't be parsed by AST."""
    related: list[str] = []
    # Match: import foo, from foo import bar, from .foo import bar
    for m in re.finditer(r"^\s*(?:from\s+(\.*)(\.+\S+|\S+)\s+import|import\s+(\S+))", source, re.M):
        level_dots, from_mod, imp_mod = m.group(1), m.group(2), m.group(3)
        if imp_mod:
            path = module_to_path(imp_mod.split(".")[0], project_root)
            if path:
                related.append(path)
        elif from_mod:
            if level_dots:
                path = _relative_module_to_path(file_path, from_mod or "", len(level_dots), project_root)
            else:
                path = module_to_path(from_mod, project_root)
            if path:
                related.append(path)
    return list(dict.fromkeys(related))


def _scan_one_file(file_path: Path, project_root: str) -> list[str]:
    """Collect directly imported local python files for a single module file."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError:
        return []

    try:
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        # File has a syntax error — fall back to regex-based import extraction
        # so we can still find related files even when the target is broken.
        return _scan_one_file_regex(source, file_path, project_root)

    related: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                path = module_to_path(alias.name, project_root)
                if path:
                    related.append(path)
            continue

        if not isinstance(node, ast.ImportFrom):
            continue

        module_name = node.module or ""
        if node.level > 0:
            path = _relative_module_to_path(file_path, module_name, node.level, project_root)
            if path:
                related.append(path)

            # Best effort for patterns like: from . import foo
            for alias in node.names:
                if alias.name == "*":
                    continue
                alias_mod = f"{module_name}.{alias.name}" if module_name else alias.name
                alias_path = _relative_module_to_path(file_path, alias_mod, node.level, project_root)
                if alias_path:
                    related.append(alias_path)
        elif module_name:
            path = module_to_path(module_name, project_root)
            if path:
                related.append(path)

            for alias in node.names:
                if alias.name == "*":
                    continue
                alias_path = module_to_path(f"{module_name}.{alias.name}", project_root)
                if alias_path:
                    related.append(alias_path)

    # Deduplicate while preserving order
    unique: list[str] = []
    seen: set[str] = set()
    for p in related:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def scan_related_files(project_root: str, target_file: str, max_depth: int = 1) -> list[str]:
    """
    Multi-hop import scan from `target_file`.

    - depth=1: direct imports only (legacy behavior)
    - depth=2+: recursively scan discovered local modules

    Returns a list of absolute paths (excluding the target itself), in discovery order.
    """
    target_path = (Path(project_root) / target_file).resolve()
    if not target_path.exists():
        return []

    depth_limit = max(1, max_depth)
    queue: deque[tuple[Path, int]] = deque([(target_path, 0)])
    visited: set[str] = {str(target_path)}
    discovered: list[str] = []

    while queue:
        current, depth = queue.popleft()
        if depth >= depth_limit:
            continue

        direct = _scan_one_file(current, project_root)
        for path in direct:
            if path in visited:
                continue
            visited.add(path)
            discovered.append(path)
            queue.append((Path(path), depth + 1))

    return discovered
