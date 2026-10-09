from codebase_qa.chunking.ids import chunk_id
from codebase_qa.models import Chunk, SourceFile


def split_lines(content: str) -> list[str]:
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def file_header(path: str) -> str:
    return f"# File: {path}"


class FixedSizeChunker:
    name = "fixed"

    def __init__(self, chunk_lines: int = 40, overlap: int = 10) -> None:
        if overlap >= chunk_lines:
            raise ValueError("overlap must be smaller than chunk_lines")
        self.chunk_lines = chunk_lines
        self.overlap = overlap

    def chunk(self, source: SourceFile) -> list[Chunk]:
        return self.chunk_span(source, split_lines(source.content), 1)

    def chunk_span(self, source: SourceFile, lines: list[str], first_line: int) -> list[Chunk]:
        chunks: list[Chunk] = []
        step = self.chunk_lines - self.overlap
        start = 0
        while start < len(lines):
            end = min(start + self.chunk_lines, len(lines))
            text = "\n".join(lines[start:end])
            if text.strip():
                chunks.append(make_chunk(source, text, first_line + start, first_line + end - 1))
            if end == len(lines):
                break
            start += step
        return chunks


def make_chunk(source: SourceFile, text: str, start_line: int, end_line: int, header: str = "") -> Chunk:
    return Chunk(
        chunk_id=chunk_id(source.repo_id, source.path, start_line, end_line, text),
        repo_id=source.repo_id,
        path=source.path,
        language=source.language,
        start_line=start_line,
        end_line=end_line,
        content=text,
        header=header or file_header(source.path),
    )
