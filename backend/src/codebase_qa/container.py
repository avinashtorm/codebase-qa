from collections.abc import Callable
from datetime import timedelta
from functools import cached_property

from codebase_qa.chunking.factory import build_chunker
from codebase_qa.config import Settings
from codebase_qa.generation.generator import LLMGenerator
from codebase_qa.generation.llm import OfflineLLM
from codebase_qa.indexing.access import AccessStore
from codebase_qa.indexing.indexer import Indexer
from codebase_qa.indexing.janitor import RepoJanitor
from codebase_qa.indexing.registry import RepoRecord, RepoRegistry
from codebase_qa.interfaces import LLM, Embedder, Generator, Reranker, Retriever
from codebase_qa.overview.builder import OverviewBuilder
from codebase_qa.overview.store import OverviewIndex, OverviewStore
from codebase_qa.overview.suggestions import QuestionSuggester
from codebase_qa.overview.summarizer import LLMSummarizer
from codebase_qa.qa import QAPipeline
from codebase_qa.retrieval.bm25 import BM25Index, BM25Retriever
from codebase_qa.retrieval.hybrid import HybridRetriever
from codebase_qa.retrieval.overview import OverviewRetriever
from codebase_qa.retrieval.reranker import RerankingRetriever
from codebase_qa.retrieval.vector import VectorRetriever
from codebase_qa.retrieval.vector_store import ChromaStore
from codebase_qa.routing.router import QuestionRouter
from codebase_qa.routing.tool import ToolAnswerer


def default_embedder(settings: Settings) -> Embedder:
    from codebase_qa.embedding.sentence import SentenceTransformerEmbedder

    return SentenceTransformerEmbedder(settings.embedding_model)


def default_llm(settings: Settings) -> LLM:
    if not settings.gemini_api_key:
        return OfflineLLM()
    from google import genai

    from codebase_qa.generation.cache import ResponseCache
    from codebase_qa.generation.gemini_llm import GeminiLLM

    cache = ResponseCache(settings.llm_cache_dir) if settings.llm_cache else None
    client = genai.Client(api_key=settings.gemini_api_key)
    return GeminiLLM(client, settings.gemini_model, cache=cache)


def default_reranker(settings: Settings) -> Reranker:
    from codebase_qa.retrieval.reranker import CrossEncoderReranker

    return CrossEncoderReranker(settings.reranker_model)


class Container:
    def __init__(
        self,
        settings: Settings,
        embedder_factory: Callable[[Settings], Embedder] = default_embedder,
        generator_factory: Callable[[Settings], Generator] | None = None,
        reranker_factory: Callable[[Settings], Reranker] = default_reranker,
        llm_factory: Callable[[Settings], LLM] = default_llm,
    ) -> None:
        self.settings = settings
        self.embedder_factory = embedder_factory
        self.generator_factory = generator_factory
        self.reranker_factory = reranker_factory
        self.llm_factory = llm_factory
        self.bm25_cache: dict[tuple[str, str], BM25Index] = {}
        self.overview_cache: dict[tuple[str, str], OverviewIndex] = {}

    @cached_property
    def embedder(self) -> Embedder:
        return self.embedder_factory(self.settings)

    @cached_property
    def llm(self) -> LLM:
        return self.llm_factory(self.settings)

    @cached_property
    def generator(self) -> Generator:
        if self.generator_factory is not None:
            return self.generator_factory(self.settings)
        return LLMGenerator(self.llm)

    @cached_property
    def overview_store(self) -> OverviewStore:
        return OverviewStore(self.settings.overview_dir)

    def overview_builder(self) -> OverviewBuilder | None:
        if not self.settings.overview:
            return None
        settings = self.settings
        summarizer = LLMSummarizer(self.llm, settings.overview_batch_size, settings.overview_max_calls)
        return OverviewBuilder(
            summarizer,
            max_files=settings.overview_max_files,
            max_folders=settings.overview_max_folders,
            file_chars=settings.overview_file_chars,
        )

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
            overview=self.overview_builder(),
            overview_store=self.overview_store,
            suggester=self.suggester(),
        )

    def suggester(self) -> QuestionSuggester | None:
        if not self.settings.suggested_questions:
            return None
        return QuestionSuggester(self.llm, self.embedder, self.settings.min_vector_score)

    @cached_property
    def access(self) -> AccessStore:
        return AccessStore(self.settings.access_path)

    @cached_property
    def janitor(self) -> RepoJanitor:
        return RepoJanitor(
            registry=self.registry,
            store=self.store,
            access=self.access,
            repos_dir=self.settings.repos_dir,
            bm25_dir=self.settings.bm25_dir,
            ttl=timedelta(hours=self.settings.repo_ttl_hours),
            max_repos=self.settings.max_visitor_repos,
            overview_dir=self.settings.overview_dir,
        )

    def visible_records(self, visitor: str | None) -> list[RepoRecord]:
        visible = self.access.visible(visitor)
        return [record for record in self.repo_records() if record.repo_id in visible]

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

    def overview_retriever(self, record: RepoRecord) -> OverviewRetriever | None:
        if not self.settings.overview:
            return None
        key = (record.collection, record.indexed_at)
        if key not in self.overview_cache:
            index = self.overview_store.load(record.collection)
            if index is None:
                return None
            self.overview_cache = {key: index}
        return OverviewRetriever(self.overview_cache[key], self.embedder)

    def router(self) -> QuestionRouter | None:
        if not self.settings.routing:
            return None
        return QuestionRouter(self.llm if self.settings.routing_llm else None)

    def pipeline(self, record: RepoRecord) -> QAPipeline:
        return QAPipeline(
            self.retriever(record),
            self.generator,
            top_k=self.settings.top_k,
            refusal_thresholds=self.settings.refusal_thresholds,
            router=self.router(),
            overview=self.overview_retriever(record),
            tool=ToolAnswerer(self.llm),
            overview_k=self.settings.overview_k,
            suggestions=record.suggested_questions,
        )
