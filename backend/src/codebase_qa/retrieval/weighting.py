from codebase_qa.ingestion.hygiene import HygieneRules
from codebase_qa.interfaces import Retriever
from codebase_qa.models import RetrievedChunk
from codebase_qa.timing import timed


def reweight(results: list[RetrievedChunk], rules: HygieneRules) -> list[RetrievedChunk]:
    weighted = []
    for item in results:
        weight = rules.weight(item.chunk.path)
        scores = item.scores if weight == 1.0 else item.scores | {"weight": weight}
        weighted.append(RetrievedChunk(item.chunk, item.score * weight, scores))
    return sorted(weighted, key=lambda item: -item.score)


class DownweightingRetriever:
    def __init__(self, base: Retriever, rules: HygieneRules, candidates: int = 30) -> None:
        self.base = base
        self.rules = rules
        self.candidates = candidates
        self.name = base.name
        self.timings: dict[str, float] = {}

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        results = self.base.retrieve(query, max(k, self.candidates))
        timings = dict(self.base.timings)
        weighted = timed(timings, "downweight", lambda: reweight(results, self.rules))
        self.timings = timings
        return weighted[:k]
