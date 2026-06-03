from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass
from pathlib import Path


KEEP_COMMENT_KEYWORDS = {
    "TODO",
    "FIXME",
    "NOTE",
    "IMPORTANT",
    "CHÚ Ý",
}


@dataclass(frozen=True)
class ContextBlock:
    file: str
    content: str
    chars: int
    lines: int


@dataclass
class ContextBuilder:
    project_root: str
    keep_comment_keywords: set[str] | None = None
    max_file_chars: int = 50000
    deny_regex: list[str] | None = None

    def __post_init__(self) -> None:
        self.root = Path(self.project_root).resolve()
        if self.keep_comment_keywords is None:
            self.keep_comment_keywords = KEEP_COMMENT_KEYWORDS
        if self.deny_regex is None:
            self.deny_regex = []

    def build(self, files: list[str]) -> dict:
        raw_blocks: list[ContextBlock] = []
        optimized_blocks: list[ContextBlock] = []

        for file in files:
            path = self.root / file

            if not path.exists():
                continue

            code = path.read_text(encoding="utf-8")
            code = self._apply_firewall(code)
            code = self._truncate_if_needed(code)

            optimized = self.prune_code(code, file)
            optimized = self._apply_firewall(optimized)

            raw_blocks.append(self._make_block(file, code))
            optimized_blocks.append(self._make_block(file, optimized))

        raw_context = self._blocks_to_prompt(raw_blocks)
        optimized_context = self._blocks_to_prompt(optimized_blocks)

        return {
            "raw_blocks": [asdict(block) for block in raw_blocks],
            "optimized_blocks": [asdict(block) for block in optimized_blocks],
            "raw_context": raw_context,
            "optimized_context": optimized_context,
        }

    def prune_code(self, code: str, file_name: str) -> str:
        if file_name.endswith(".py"):
            ts_pruned = self._prune_python_tree_sitter(code)
            if ts_pruned.strip():
                return ts_pruned

            ast_pruned = self._prune_python_ast(code)
            if ast_pruned.strip():
                return ast_pruned

        kept_lines: list[str] = []

        for line in code.splitlines():
            stripped = line.strip()

            if not stripped:
                continue

            if stripped.startswith("#"):
                if any(keyword in stripped for keyword in self.keep_comment_keywords):
                    kept_lines.append(line)
                continue

            kept_lines.append(line)

        return "\n".join(kept_lines)

    def _prune_python_tree_sitter(self, code: str) -> str:
        try:
            from tree_sitter_languages import get_parser
        except Exception:
            return ""

        parser = get_parser("python")
        tree = parser.parse(code.encode("utf-8"))
        root = tree.root_node

        keep_types = {
            "import_statement",
            "import_from_statement",
            "function_definition",
            "class_definition",
            "assignment",
        }

        chunks = self._collect_keyword_comments(code)

        for child in root.children:
            if child.type not in keep_types:
                continue

            segment = code[child.start_byte:child.end_byte]
            if segment.strip():
                chunks.append(segment)

        return "\n\n".join(chunk for chunk in chunks if chunk.strip())

    def _prune_python_ast(self, code: str) -> str:
        """
        Phase 2 pruning: keep semantically important top-level constructs.
        Falls back to line-based pruning when AST parsing fails.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return ""

        lines = code.splitlines()
        chunks: list[str] = []

        comment_keep = self._collect_keyword_comments(code)
        if comment_keep:
            chunks.append("\n".join(comment_keep))

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                segment = ast.get_source_segment(code, node)
                if segment:
                    chunks.append(segment)
                continue

            if isinstance(node, ast.Assign):
                # Keep module constants to preserve behavior hints.
                if any(
                    isinstance(target, ast.Name) and target.id.isupper()
                    for target in node.targets
                ):
                    segment = ast.get_source_segment(code, node)
                    if segment:
                        chunks.append(segment)
                continue

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = getattr(node, "lineno", None)
                end = getattr(node, "end_lineno", None)
                if start is None or end is None:
                    segment = ast.get_source_segment(code, node)
                    if segment:
                        chunks.append(segment)
                    continue

                start_idx = max(start - 1, 0)
                end_idx = min(end, len(lines))
                if start_idx < end_idx:
                    chunks.append("\n".join(lines[start_idx:end_idx]))

        return "\n\n".join(chunk for chunk in chunks if chunk.strip())

    def _collect_keyword_comments(self, code: str) -> list[str]:
        comments: list[str] = []
        for line in code.splitlines():
            stripped = line.strip()
            if not stripped.startswith("#"):
                continue

            if any(keyword in stripped for keyword in self.keep_comment_keywords):
                comments.append(line)

        return comments

    def _truncate_if_needed(self, code: str) -> str:
        if len(code) <= self.max_file_chars:
            return code

        return code[: self.max_file_chars]

    def _apply_firewall(self, code: str) -> str:
        redacted = code

        for pattern in self.deny_regex:
            try:
                redacted = re.sub(pattern, "[REDACTED]", redacted, flags=re.IGNORECASE)
            except re.error:
                continue

        return redacted

    def _make_block(self, file: str, content: str) -> ContextBlock:
        return ContextBlock(
            file=file,
            content=content,
            chars=len(content),
            lines=len(content.splitlines()),
        )

    def _blocks_to_prompt(self, blocks: list[ContextBlock]) -> str:
        chunks: list[str] = []

        for block in blocks:
            chunks.append(
                f"\n# FILE: {block.file}\n"
                f"# LINES: {block.lines}, CHARS: {block.chars}\n"
                f"{block.content}"
            )

        return "\n".join(chunks)


def build_context(
    project_root: str,
    files: list[str],
    keep_comment_keywords: set[str] | None = None,
    max_file_chars: int = 50000,
    deny_regex: list[str] | None = None,
) -> dict:
    builder = ContextBuilder(
        project_root=project_root,
        keep_comment_keywords=keep_comment_keywords,
        max_file_chars=max_file_chars,
        deny_regex=deny_regex,
    )
    return builder.build(files)