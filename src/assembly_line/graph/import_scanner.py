from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImportScanner:
    project_root: str
    max_depth: int = 1
    _cache: dict[Path, set[Path]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = Path(self.project_root).resolve()

    def scan(self, target_file: str) -> list[str]:
        target_path = (self.root / target_file).resolve()

        if not target_path.exists():
            raise FileNotFoundError(f"Target file not found: {target_path}")

        visited: set[Path] = set()
        queue: list[tuple[Path, int]] = [(target_path, 0)]

        while queue:
            current_file, depth = queue.pop(0)

            if current_file in visited:
                continue

            if not self._is_inside_project(current_file):
                continue

            visited.add(current_file)

            if depth >= self.max_depth:
                continue

            for dep in self._scan_one_file(current_file):
                if dep not in visited:
                    queue.append((dep, depth + 1))

        return [
            str(path.relative_to(self.root)).replace("\\", "/")
            for path in sorted(visited)
        ]

    def _scan_one_file(self, file_path: Path) -> set[Path]:
        if file_path in self._cache:
            return self._cache[file_path]

        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        deps: set[Path] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = self._module_to_path(alias.name)
                    if resolved:
                        deps.add(resolved)

            elif isinstance(node, ast.ImportFrom):
                if not node.module:
                    continue

                resolved = self._module_to_path(node.module)
                if resolved:
                    deps.add(resolved)

        self._cache[file_path] = deps
        return deps

    def _module_to_path(self, module_name: str) -> Path | None:
        """
        Convert:
            app.utils.excel_helper
        thành:
            <root>/app/utils/excel_helper.py
        """
        parts = module_name.split(".")
        candidate = self.root.joinpath(*parts)

        py_file = candidate.with_suffix(".py")
        package_init = candidate / "__init__.py"

        if py_file.exists():
            return py_file.resolve()

        if package_init.exists():
            return package_init.resolve()

        return None

    def _is_inside_project(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
            return True
        except ValueError:
            return False


def scan_related_files(
    project_root: str,
    target_file: str,
    depth: int = 1,
) -> list[str]:
    scanner = ImportScanner(project_root=project_root, max_depth=depth)
    return scanner.scan(target_file)