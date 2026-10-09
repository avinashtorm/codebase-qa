from collections.abc import Callable
from functools import cached_property

from codebase_qa.chunking.factory import build_chunker
from codebase_qa.config import Settings
from codebase_qa.indexing.indexer import Indexer
from codebase_qa.indexing.registry import RepoRecord, RepoRegistry
from codebase_qa.interfaces import Embedder, Generator, Retriever
from codebase_qa.qa import QAPipeline
from codebase_qa.retrieval.vector import VectorRetriever
from codebase_qa.retrieval.vector_store import ChromaStore


def default_embedder(settings: Settings) -> Embedder:
    from codebase_qa.embedding.sentence import SentenceTransformerEmbedder

    return SentenceTransformerEmbedder(settings.embedding_model)


def default_generator(settings: Settings) -> Generator:
    from google import genai

    from codebase_qa.generation.cache import ResponseCache
    from codebase_qa.generation.gemini_generator import GeminiGenerator

    cache = ResponseCache(settings.llm_cache_dir) if settings.llm_cache else None
    client = genai.Client(api_key=settings.gemini_api_key)
    return GeminiGenerator(client, settings.gemini_model, cache=cache)


class Container:
    def __init__(
        self,
        settings: Settings,
        embedder_factory: Callable[[Settings], Embedder] = default_embedder,
        generator_factory: Callable[[Settings], Generator] = default_generator,
    ) -> None:
        self.settings = settings
        self.embedder_factory = embedder_factory
        self.generator_factory = generator_factory

    @cached_property
    def embedder(self) -> Embedder:
        return self.embedder_factory(self.settings)

    @cached_property
    def generator(self) -> Generator:
        return self.generator_factory(self.settings)

    @cached_property
    def store(self) -> ChromaStore:
        return ChromaStore(self.settings.chroma_dir)

    @cached_property
    def registry(self) -> RepoRegistry:
        return RepoRegistry(self.settings.registry_path)

    @cached_property
    def indexer(self) -> Indexer:
        return Indexer(
            store=self.store,
            embedder=self.embedder,
            chunker=build_chunker(self.settings.chunker),
            registry=self.registry,
            repos_dir=self.settings.repos_dir,
            clone_timeout=self.settings.clone_timeout_seconds,
        )

    def repo_record(self, repo_id: str) -> RepoRecord | None:
        return self.registry.get(self.indexer.collection_for(repo_id))

    def repo_records(self) -> list[RepoRecord]:
        return [record for record in self.registry.list() if record.chunker == self.settings.chunker]

    def retriever(self, record: RepoRecord) -> Retriever:
        return VectorRetriever(self.store.collection(record.collection), self.embedder)

    def pipeline(self, record: RepoRecord) -> QAPipeline:
        return QAPipeline(self.retriever(record), self.generator, top_k=self.settings.top_k)
