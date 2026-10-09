from dataclasses import replace

from codebase_qa.interfaces import Reranker, Retriever
from codebase_qa.models import RetrievedChunk
from codebase_qa.retrieval.hybrid import reciprocal_rank_fusion
from codebase_qa.timing import timed

MAX_PASSAGE_CHARS = 4000


def passage(item: RetrievedChunk) -> str:
    return item.chunk.embedding_text[:MAX_PASSAGE_CHARS]


class CrossEncoderReranker:
    def __init__(self, model_name: str, batch_size: int = 16, max_length: int = 512) -> None:
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_name, max_length=max_length)
        self.batch_size = batch_size

    def score(self, query: str, candidates: list[RetrievedChunk]) -> list[float]:
        if not candidates:
            return []
        pairs = [(query, passage(item)) for item in candidates]
        scores = self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
        return [float(score) for score in scores]


def rerank(query: str, candidates: list[RetrievedChunk], reranker: Reranker) -> list[RetrievedChunk]:
    scores = reranker.score(query, candidates)
    rescored = [
        replace(item, score=score, scores=item.scores | {"pre_rerank": item.score, "rerank": score})
        for item, score in zip(candidates, scores, strict=True)
    ]
    return sorted(rescored, key=lambda item: -item.score)


class RerankingRetriever:
    name = "rerank"

    def __init__(self, base: Retriever, reranker: Reranker, candidates: int = 30, fuse: bool = False) -> None:
        self.base = base
        self.reranker = reranker
        self.candidates = candidates
        self.fuse = fuse
        self.timings: dict[str, float] = {}

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        candidates = self.base.retrieve(query, max(k, self.candidates))
        timings = dict(self.base.timings)
        reranked = timed(timings, "rerank", lambda: rerank(query, candidates, self.reranker))
        if self.fuse:
            reranked = reciprocal_rank_fusion({"first_stage": candidates, "rerank": reranked})
        self.timings = timings
        return reranked[:k]
