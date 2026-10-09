from pathlib import Path

import pytest

from codebase_qa.models import Chunk
from codebase_qa.retrieval.vector_store import ChromaStore, collection_name


def make_chunk(chunk_id: str, path: str) -> Chunk:
    return Chunk(chunk_id, "repo", path, "python", 1, 2, f"content {chunk_id}", "# File: x")


def test_collection_name_is_valid_for_chroma() -> None:
    name = collection_name("fastapi__full-stack-fastapi-template", "treesitter")
    assert name == "fastapi__full-stack-fastapi-template--treesitter"
    assert len(collection_name("x" * 100, "fixed")) <= 63


def test_add_query_and_delete_by_path(tmp_path: Path) -> None:
    collection = ChromaStore(tmp_path).collection("test--fixed")
    chunks = [make_chunk("a", "one.py"), make_chunk("b", "two.py"), make_chunk("c", "two.py")]
    collection.add(chunks, [[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]])

    [(best, score), *_] = collection.query([1.0, 0.0], k=3)
    assert best.chunk_id == "a"
    assert best.header == "# File: x"
    assert score == pytest.approx(1.0, abs=1e-5)

    assert collection.delete_paths(["two.py"]) == 2
    assert [chunk.chunk_id for chunk in collection.all_chunks()] == ["a"]


def test_query_on_empty_collection(tmp_path: Path) -> None:
    assert ChromaStore(tmp_path).collection("empty--fixed").query([1.0, 0.0], k=5) == []
