from codebase_qa.interfaces import Embedder
from codebase_qa.models import RetrievedChunk
from codebase_qa.retrieval.vector_store import VectorCollection


class VectorRetriever:
    name = "vector"

    def __init__(self, collection: VectorCollection, embedder: Embedder) -> None:
        self.collection = collection
        self.embedder = embedder

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        embedding = self.embedder.embed_query(query)
        return [
            RetrievedChunk(chunk=chunk, score=score, scores={"vector": score})
            for chunk, score in self.collection.query(embedding, k)
        ]
