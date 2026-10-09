from codebase_qa.models import Chunk, RetrievedChunk
from codebase_qa.retrieval.reranker import RerankingRetriever, rerank


def item(chunk_id: str, content: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(Chunk(chunk_id, "r", f"{chunk_id}.py", "python", 1, 1, content), score, {"rrf": score})


class OverlapReranker:
    def score(self, query: str, candidates: list[RetrievedChunk]) -> list[float]:
        words = set(query.split())
        return [float(len(words & set(c.chunk.content.split()))) for c in candidates]


class FixedRetriever:
    name = "fixed"

    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.requested: list[int] = []
        self.timings: dict[str, float] = {"vector_search": 2.0}

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        self.requested.append(k)
        return self.results[:k]


CANDIDATES = [
    item("a", "unrelated text", 0.9),
    item("b", "password hash function", 0.5),
    item("c", "password reset", 0.4),
]


def test_rerank_orders_by_cross_encoder_score_and_keeps_previous_score() -> None:
    reranked = rerank("password hash", CANDIDATES, OverlapReranker())
    assert [r.chunk.chunk_id for r in reranked] == ["b", "c", "a"]
    assert reranked[0].scores == {"rrf": 0.5, "pre_rerank": 0.5, "rerank": 2.0}


def test_reranking_retriever_scores_candidates_and_truncates() -> None:
    base = FixedRetriever(CANDIDATES)
    retriever = RerankingRetriever(base, OverlapReranker(), candidates=30)
    results = retriever.retrieve("password hash", 2)
    assert base.requested == [30]
    assert [r.chunk.chunk_id for r in results] == ["b", "c"]
    assert retriever.timings["vector_search"] == 2.0
    assert "rerank" in retriever.timings


def test_rerank_fusion_combines_first_stage_and_reranker_ranks() -> None:
    retriever = RerankingRetriever(FixedRetriever(CANDIDATES), OverlapReranker(), candidates=30, fuse=True)
    results = retriever.retrieve("password hash", 3)
    assert [r.chunk.chunk_id for r in results] == ["b", "a", "c"]
    assert {"first_stage", "rerank", "rrf"} <= set(results[0].scores)
