from typing import Protocol

from codebase_qa.models import Chunk, GeneratedAnswer, RetrievedChunk, SourceFile


class Chunker(Protocol):
    name: str

    def chunk(self, source: SourceFile) -> list[Chunk]: ...


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class Retriever(Protocol):
    name: str

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]: ...


class Generator(Protocol):
    def generate(self, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer: ...
