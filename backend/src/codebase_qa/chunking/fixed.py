from codebase_qa.chunking.ids import chunk_id
from codebase_qa.models import Chunk, SourceFile


def split_lines(content: str) -> list[str]:
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def file_header(path: str) -> str:
    return f"# File: {path}"


def line_windows(first: int, last: int, size: int, overlap: int) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    start = first
    while start <= last:
        end = min(start + size - 1, last)
        windows.append((start, end))
        if end == last:
            break
        start = end + 1 - overlap
    return windows


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


class FixedSizeChunker:
    name = "fixed"

    def __init__(self, chunk_lines: int = 40, overlap: int = 10) -> None:
        if overlap >= chunk_lines:
            raise ValueError("overlap must be smaller than chunk_lines")
        self.chunk_lines = chunk_lines
        self.overlap = overlap

    def chunk(self, source: SourceFile) -> list[Chunk]:
        lines = split_lines(source.content)
        chunks: list[Chunk] = []
        for start, end in line_windows(1, len(lines), self.chunk_lines, self.overlap):
            text = "\n".join(lines[start - 1 : end])
            if text.strip():
                chunks.append(make_chunk(source, text, start, end))
        return chunks
