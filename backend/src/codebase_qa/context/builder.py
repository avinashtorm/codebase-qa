from dataclasses import replace

from codebase_qa.context.calls import callee_chunks
from codebase_qa.context.catalog import ChunkCatalog, LineReader
from codebase_qa.context.parent import parent_span
from codebase_qa.models import Chunk, RetrievedChunk, is_overview_path


def is_code(item: RetrievedChunk) -> bool:
    return not is_overview_path(item.chunk.path) and item.chunk.kind != "overview"


def contains(outer: Chunk, inner: Chunk) -> bool:
    return outer.path == inner.path and outer.start_line <= inner.start_line and inner.end_line <= outer.end_line


class ContextBuilder:
    def __init__(
        self,
        catalog: ChunkCatalog,
        reader: LineReader,
        parent: bool = True,
        calls: bool = True,
        parent_max_lines: int = 100,
        window: int = 10,
        call_max_functions: int = 4,
        call_max_lines: int = 150,
    ) -> None:
        self.catalog = catalog
        self.reader = reader
        self.parent = parent
        self.calls = calls
        self.parent_max_lines = parent_max_lines
        self.window = window
        self.call_max_functions = call_max_functions
        self.call_max_lines = call_max_lines

    def build(self, context: list[RetrievedChunk]) -> list[RetrievedChunk]:
        items = self.expand(context) if self.parent else list(context)
        if self.calls:
            items += self.callees([item.chunk for item in context if is_code(item)], items)
        return items

    def expand(self, context: list[RetrievedChunk]) -> list[RetrievedChunk]:
        expanded: list[RetrievedChunk] = []
        for item in context:
            grown = self.grow(item) if is_code(item) else item
            if any(is_code(kept) and contains(kept.chunk, grown.chunk) for kept in expanded):
                continue
            expanded.append(grown)
        return expanded

    def grow(self, item: RetrievedChunk) -> RetrievedChunk:
        chunk = item.chunk
        lines = self.reader.lines(chunk.path)
        if not lines or chunk.end_line > len(lines):
            return item
        start, end = parent_span(chunk, self.catalog, len(lines), self.parent_max_lines, self.window)
        if (start, end) == (chunk.start_line, chunk.end_line):
            return item
        grown = replace(
            chunk,
            chunk_id=f"{chunk.chunk_id}:parent",
            start_line=start,
            end_line=end,
            content="\n".join(lines[start - 1 : end]),
        )
        return RetrievedChunk(grown, item.score, item.scores | {"parent_lines": float(end - start + 1)})

    def callees(self, retrieved: list[Chunk], context: list[RetrievedChunk]) -> list[RetrievedChunk]:
        found = callee_chunks(retrieved, self.catalog, self.call_max_functions, self.call_max_lines)
        spans = [item.chunk for item in context if is_code(item)]
        return [
            RetrievedChunk(chunk, 0.0, {"callee": 1.0})
            for chunk in found
            if not any(contains(span, chunk) for span in spans)
        ]
