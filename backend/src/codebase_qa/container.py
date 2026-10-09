from collections.abc import Callable
from functools import cached_property

from codebase_qa.chunking.factory import build_chunker
from codebase_qa.config import Settings
from codebase_qa.indexing.indexer import Indexer
from codebase_qa.indexing.registry import RepoRecord, RepoRegistry
from codebase_qa.interfaces import Embedder, Generator, Reranker, Retriever
from codebase_qa.qa import QAPipeline
from codebase_qa.retrieval.bm25 import BM25Index, BM25Retriever
from codebase_qa.retrieval.hybrid import HybridRetriever
from codebase_qa.retrieval.reranker import RerankingRetriever
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


def default_reranker(settings: Settings) -> Reranker:
    from codebase_qa.retrieval.reranker import CrossEncoderReranker

    return CrossEncoderReranker(settings.reranker_model)


class Container:
    def __init__(
        self,
        settings: Settings,
        embedder_factory: Callable[[Settings], Embedder] = default_embedder,
        generator_factory: Callable[[Settings], Generator] = default_generator,
        reranker_factory: Callable[[Settings], Reranker] = default_reranker,
    ) -> None:
        self.settings = settings
        self.embedder_factory = embedder_factory
        self.generator_factory = generator_factory
        self.reranker_factory = reranker_factory
        self.bm25_cache: dict[tuple[str, str], BM25Index] = {}

    @cached_property
    def embedder(self) -> Embedder:
        return self.embedder_factory(self.settings)

    @cached_property
    def generator(self) -> Generator:
        return self.generator_factory(self.settings)

    @cached_property
    def reranker(self) -> Reranker:
        return self.reranker_factory(self.settings)

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
            bm25_dir=self.settings.bm25_dir,
            clone_timeout=self.settings.clone_timeout_seconds,
            max_repo_bytes=self.settings.max_repo_size_mb * 1024 * 1024,
        )

    def repo_record(self, repo_id: str) -> RepoRecord | None:
        return self.registry.get(self.indexer.collection_for(repo_id))

    def repo_records(self) -> list[RepoRecord]:
        return [record for record in self.registry.list() if record.chunker == self.settings.chunker]

    def bm25_index(self, record: RepoRecord) -> BM25Index:
        key = (record.collection, record.indexed_at)
        if key not in self.bm25_cache:
            path = self.indexer.bm25_path(record.collection)
            if BM25Index.exists(path):
                index = BM25Index.load(path)
            else:
                index = self.indexer.rebuild_bm25(self.store.collection(record.collection))
            self.bm25_cache = {key: index}
        return self.bm25_cache[key]

    def retriever(self, record: RepoRecord) -> Retriever:
        base = self.first_stage_retriever(record)
        if not self.settings.rerank:
            return base
        return RerankingRetriever(
            base, self.reranker, candidates=self.settings.rerank_candidates, fuse=self.settings.rerank_fusion
        )

    def first_stage_retriever(self, record: RepoRecord) -> Retriever:
        mode = self.settings.retrieval_mode
        if mode == "bm25":
            return BM25Retriever(self.bm25_index(record))
        vector = VectorRetriever(self.store.collection(record.collection), self.embedder)
        if mode == "vector":
            return vector
        return HybridRetriever(
            vector,
            BM25Retriever(self.bm25_index(record)),
            candidates=self.settings.hybrid_candidates,
            rrf_k=self.settings.rrf_k,
        )

    def pipeline(self, record: RepoRecord) -> QAPipeline:
        return QAPipeline(
            self.retriever(record),
            self.generator,
            top_k=self.settings.top_k,
            refusal_thresholds=self.settings.refusal_thresholds,
        )
