from codebase_qa.interfaces import Retriever
from codebase_qa.models import Chunk, RetrievedChunk


def reciprocal_rank_fusion(rankings: dict[str, list[RetrievedChunk]], k: int = 60) -> list[RetrievedChunk]:
    fused: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    component_scores: dict[str, dict[str, float]] = {}
    for source, ranking in rankings.items():
        for rank, item in enumerate(ranking, start=1):
            chunk_id = item.chunk.chunk_id
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
            chunks[chunk_id] = item.chunk
            component_scores.setdefault(chunk_id, {})[source] = item.score
            component_scores[chunk_id][f"{source}_rank"] = float(rank)
    ordered = sorted(fused, key=lambda chunk_id: (-fused[chunk_id], chunk_id))
    return [
        RetrievedChunk(chunks[chunk_id], fused[chunk_id], component_scores[chunk_id] | {"rrf": fused[chunk_id]})
        for chunk_id in ordered
    ]


class HybridRetriever:
    name = "hybrid"

    def __init__(self, vector: Retriever, keyword: Retriever, candidates: int = 50, rrf_k: int = 60) -> None:
        self.vector = vector
        self.keyword = keyword
        self.candidates = candidates
        self.rrf_k = rrf_k

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        rankings = {
            "vector": self.vector.retrieve(query, self.candidates),
            "bm25": self.keyword.retrieve(query, self.candidates),
        }
        return reciprocal_rank_fusion(rankings, self.rrf_k)[:k]
