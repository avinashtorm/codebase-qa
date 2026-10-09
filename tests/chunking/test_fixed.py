from codebase_qa.chunking.fixed import FixedSizeChunker
from codebase_qa.ingestion.walker import content_hash
from codebase_qa.models import SourceFile


def make_source(line_count: int, path: str = "pkg/mod.py") -> SourceFile:
    content = "".join(f"line_{n} = {n}\n" for n in range(1, line_count + 1))
    return SourceFile("repo", path, "python", content, content_hash(content))


def test_chunks_cover_file_with_overlap_and_exact_lines() -> None:
    source = make_source(100)
    chunks = FixedSizeChunker(chunk_lines=40, overlap=10).chunk(source)
    assert [(c.start_line, c.end_line) for c in chunks] == [(1, 40), (31, 70), (61, 100)]
    for chunk in chunks:
        lines = chunk.content.split("\n")
        assert lines[0] == f"line_{chunk.start_line} = {chunk.start_line}"
        assert lines[-1] == f"line_{chunk.end_line} = {chunk.end_line}"
        assert chunk.path == "pkg/mod.py"
        assert chunk.language == "python"
        assert chunk.header == "# File: pkg/mod.py"


def test_short_file_is_single_chunk() -> None:
    [chunk] = FixedSizeChunker().chunk(make_source(5))
    assert (chunk.start_line, chunk.end_line) == (1, 5)


def test_chunk_ids_are_stable_and_unique() -> None:
    first = FixedSizeChunker().chunk(make_source(100))
    second = FixedSizeChunker().chunk(make_source(100))
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert len({c.chunk_id for c in first}) == len(first)
    other_path = FixedSizeChunker().chunk(make_source(100, path="other.py"))
    assert {c.chunk_id for c in first}.isdisjoint({c.chunk_id for c in other_path})


def test_blank_file_produces_no_chunks() -> None:
    source = SourceFile("repo", "empty.py", "python", "\n\n\n", content_hash("\n\n\n"))
    assert FixedSizeChunker().chunk(source) == []
