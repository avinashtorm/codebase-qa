from codebase_qa.interfaces import Embedder
from codebase_qa.models import RetrievedChunk
from codebase_qa.retrieval.vector_store import VectorCollection
from codebase_qa.timing import timed


class VectorRetriever:
    name = "vector"

    def __init__(self, collection: VectorCollection, embedder: Embedder) -> None:
        self.collection = collection
        self.embedder = embedder
        self.timings: dict[str, float] = {}

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        timings: dict[str, float] = {}
        embedding = timed(timings, "embed_query", lambda: self.embedder.embed_query(query))
        rows = timed(timings, "vector_search", lambda: self.collection.query(embedding, k))
        self.timings = timings
        return [RetrievedChunk(chunk=chunk, score=score, scores={"vector": score}) for chunk, score in rows]
