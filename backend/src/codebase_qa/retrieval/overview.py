from codebase_qa.interfaces import Embedder
from codebase_qa.models import RetrievedChunk
from codebase_qa.overview.store import OverviewIndex
from codebase_qa.timing import timed


class OverviewRetriever:
    name = "overview"

    def __init__(self, index: OverviewIndex, embedder: Embedder) -> None:
        self.index = index
        self.embedder = embedder
        self.timings: dict[str, float] = {}

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        timings: dict[str, float] = {}
        embedding = timed(timings, "overview_embed", lambda: self.embedder.embed_query(query))
        results = timed(timings, "overview_search", lambda: self.index.search(embedding, k))
        self.timings = timings
        return results
