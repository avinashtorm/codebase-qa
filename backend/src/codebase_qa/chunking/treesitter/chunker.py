import logging
import re

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_parser

from codebase_qa.chunking.fixed import FixedSizeChunker, file_header, line_windows, make_chunk, split_lines
from codebase_qa.chunking.treesitter.languages import LANGUAGE_SPECS, LanguageSpec
from codebase_qa.chunking.treesitter.nodes import (
    Definition,
    body_of,
    class_body,
    definitions_in,
    end_line,
    name_of,
    receiver_type,
    signature,
    start_line,
)
from codebase_qa.models import Chunk, SourceFile

logger = logging.getLogger(__name__)
MEANINGFUL = re.compile(r"[^\s{}()\[\];,]")
Span = tuple[int, int]


def uncovered_runs(first: int, last: int, covered: list[Span]) -> list[Span]:
    runs: list[Span] = []
    cursor = first
    for start, end in sorted(covered):
        if start > cursor:
            runs.append((cursor, start - 1))
        cursor = max(cursor, end + 1)
    if cursor <= last:
        runs.append((cursor, last))
    return runs


class FileChunks:
    def __init__(self, source: SourceFile, spec: LanguageSpec, source_bytes: bytes, max_lines: int) -> None:
        self.source = source
        self.spec = spec
        self.bytes = source_bytes
        self.lines = split_lines(source.content)
        self.max_lines = max_lines
        self.chunks: list[Chunk] = []

    def meaningful_lines(self, start: int, end: int) -> int:
        return sum(1 for line in self.lines[start - 1 : end] if MEANINGFUL.search(line))

    def trim(self, start: int, end: int) -> Span | None:
        while start <= end and not self.lines[start - 1].strip():
            start += 1
        while end >= start and not self.lines[end - 1].strip():
            end -= 1
        return (start, end) if start <= end else None

    def emit(self, start: int, end: int, header: str) -> None:
        text = "\n".join(self.lines[start - 1 : end])
        if text.strip():
            self.chunks.append(make_chunk(self.source, text, start, end, header))

    def emit_windows(self, start: int, end: int, header: str, size: int) -> None:
        for window_start, window_end in line_windows(start, end, size, 0):
            self.emit(window_start, window_end, header)

    def header(self, *parts: str) -> str:
        return "\n".join([file_header(self.source.path), *parts])

    def process_root(self, root: Node) -> None:
        definitions = definitions_in(root, self.spec)
        for definition in definitions:
            self.process_definition(definition, None)
        covered = [(d.start_line, d.end_line) for d in definitions]
        for run in uncovered_runs(1, len(self.lines), covered):
            trimmed = self.trim(*run)
            if trimmed and self.meaningful_lines(*trimmed) > 0:
                self.emit_windows(*trimmed, self.header("# Top-level code"), self.max_lines)

    def process_definition(self, definition: Definition, enclosing: str | None) -> None:
        if definition.kind == "function":
            self.process_function(definition, enclosing)
        elif definition.kind == "class":
            self.process_class(definition, enclosing)
        else:
            sig = signature(definition.inner, self.bytes, self.spec)
            self.emit_windows(
                definition.start_line, definition.end_line, self.header(f"# Definition: {sig}"), self.max_lines
            )

    def process_class(self, definition: Definition, enclosing: str | None) -> None:
        name = name_of(definition.inner, self.bytes)
        qualified = f"{enclosing}.{name}" if enclosing else name
        class_header = self.header(f"# Class: {signature(definition.inner, self.bytes, self.spec)}")
        body = class_body(definition.inner)
        members = definitions_in(body, self.spec) if body is not None else []
        if not members:
            self.emit_windows(definition.start_line, definition.end_line, class_header, self.max_lines)
            return
        for member in members:
            self.process_definition(member, qualified)
        covered = [(m.start_line, m.end_line) for m in members]
        for run in uncovered_runs(definition.start_line, definition.end_line, covered):
            trimmed = self.trim(*run)
            if trimmed and self.meaningful_lines(*trimmed) >= 2:
                self.emit_windows(*trimmed, class_header, self.max_lines)

    def process_function(self, definition: Definition, enclosing: str | None) -> None:
        owner = enclosing or receiver_type(definition.inner, self.bytes, self.spec)
        sig = signature(definition.inner, self.bytes, self.spec)
        parts = [f"# Class: {owner}", f"# Method: {sig}"] if owner else [f"# Function: {sig}"]
        header = self.header(*parts)
        if definition.end_line - definition.start_line + 1 <= self.max_lines:
            self.emit(definition.start_line, definition.end_line, header)
            return
        for start, end in self.statement_groups(definition):
            if end - start + 1 > self.max_lines:
                self.emit_windows(start, end, header, self.max_lines)
            else:
                self.emit(start, end, header)

    def statement_groups(self, definition: Definition) -> list[Span]:
        body = body_of(definition.inner, self.spec)
        statements = body.named_children if body is not None else []
        if not statements:
            return [(definition.start_line, definition.end_line)]
        groups: list[Span] = []
        group_start = definition.start_line
        for statement in statements:
            statement_start = start_line(statement)
            if statement_start > group_start and end_line(statement) - group_start + 1 > self.max_lines:
                groups.append((group_start, statement_start - 1))
                group_start = statement_start
        groups.append((group_start, definition.end_line))
        return groups


class TreeSitterChunker:
    name = "treesitter"

    def __init__(self, max_lines: int = 60, fallback: FixedSizeChunker | None = None) -> None:
        self.max_lines = max_lines
        self.fallback = fallback or FixedSizeChunker()
        self.parsers: dict[str, Parser] = {}

    def parser(self, grammar: str) -> Parser:
        if grammar not in self.parsers:
            self.parsers[grammar] = get_parser(grammar)
        return self.parsers[grammar]

    def chunk(self, source: SourceFile) -> list[Chunk]:
        spec = LANGUAGE_SPECS.get(source.language)
        if spec is None:
            return self.fallback.chunk(source)
        source_bytes = source.content.encode("utf-8")
        try:
            tree = self.parser(spec.grammar).parse(source_bytes)
        except Exception:
            logger.warning("tree-sitter parse failed, using fixed chunks", extra={"path": source.path})
            return self.fallback.chunk(source)
        builder = FileChunks(source, spec, source_bytes, self.max_lines)
        builder.process_root(tree.root_node)
        return sorted(builder.chunks, key=lambda chunk: (chunk.start_line, chunk.end_line))
