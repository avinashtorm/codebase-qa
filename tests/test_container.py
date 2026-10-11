from collections.abc import Callable
from pathlib import Path

import pytest

from codebase_qa.container import Container
from codebase_qa.models import RetrievedChunk
from codebase_qa.retrieval.bm25 import BM25Retriever
from codebase_qa.retrieval.hybrid import HybridRetriever
from codebase_qa.retrieval.reranker import RerankingRetriever
from codebase_qa.retrieval.vector import VectorRetriever
from codebase_qa.retrieval.weighting import DownweightingRetriever
from tests.fakes import fake_embedder, fake_generator, make_settings

RepoFactory = Callable[..., Path]


class LengthReranker:
    def score(self, query: str, candidates: list[RetrievedChunk]) -> list[float]:
        return [float(len(item.chunk.content)) for item in candidates]


def build(tmp_path: Path, **overrides: object) -> Container:
    settings = make_settings(tmp_path / "data", **overrides)
    return Container(
        settings,
        embedder_factory=fake_embedder,
        generator_factory=fake_generator,
        reranker_factory=lambda _: LengthReranker(),
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("vector", VectorRetriever), ("bm25", BM25Retriever), ("hybrid", HybridRetriever)],
)
def test_retriever_matches_configured_mode(
    tmp_path: Path, make_repo: RepoFactory, mode: str, expected: type
) -> None:
    container = build(tmp_path, retrieval_mode=mode)
    record = container.indexer.index(make_repo().as_uri())
    retriever = container.retriever(record)
    assert isinstance(retriever, DownweightingRetriever) and isinstance(retriever.base, expected)
    results = retriever.retrieve("AuthService login token", 3)
    assert results and results[0].chunk.path == "app/auth.py"
    assert retriever.timings


def test_rerank_wraps_first_stage_and_reorders(tmp_path: Path, make_repo: RepoFactory) -> None:
    container = build(tmp_path, retrieval_mode="hybrid", rerank=True, rerank_candidates=30)
    record = container.indexer.index(make_repo().as_uri())
    retriever = container.retriever(record)
    assert isinstance(retriever, RerankingRetriever)
    assert isinstance(retriever.base, DownweightingRetriever) and isinstance(retriever.base.base, HybridRetriever)
    results = retriever.retrieve("login", 3)
    lengths = [len(item.chunk.content) for item in results]
    assert lengths == sorted(lengths, reverse=True)
    assert "rerank" in retriever.timings and "fusion" in retriever.timings


def test_bm25_index_is_rebuilt_from_chroma_when_missing(tmp_path: Path, make_repo: RepoFactory) -> None:
    container = build(tmp_path, retrieval_mode="bm25")
    record = container.indexer.index(make_repo().as_uri())
    bm25_dir = container.indexer.bm25_path(record.collection)
    for path in bm25_dir.iterdir():
        path.unlink()
    bm25_dir.rmdir()
    results = container.retriever(record).retrieve("greet name", 2)
    assert results[0].chunk.path == "web/index.ts"
    assert bm25_dir.exists()


def test_hygiene_off_returns_plain_first_stage(tmp_path: Path, make_repo: RepoFactory) -> None:
    container = build(tmp_path, hygiene=False)
    record = container.indexer.index(make_repo().as_uri())
    assert isinstance(container.retriever(record), VectorRetriever)
