import logging
from datetime import UTC, datetime
from pathlib import Path

from codebase_qa.indexing.registry import FileRecord, RepoRecord, RepoRegistry
from codebase_qa.ingestion.git import clone_repo
from codebase_qa.ingestion.walker import walk_repo
from codebase_qa.interfaces import Chunker, Embedder
from codebase_qa.models import Chunk, ClonedRepo, SourceFile
from codebase_qa.retrieval.bm25 import BM25Index
from codebase_qa.retrieval.vector_store import ChromaStore, VectorCollection, collection_name

logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Indexer:
    def __init__(
        self,
        store: ChromaStore,
        embedder: Embedder,
        chunker: Chunker,
        registry: RepoRegistry,
        repos_dir: Path,
        bm25_dir: Path,
        clone_timeout: float = 120.0,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.chunker = chunker
        self.registry = registry
        self.repos_dir = repos_dir
        self.bm25_dir = bm25_dir
        self.clone_timeout = clone_timeout

    def collection_for(self, repo_id: str) -> str:
        return collection_name(repo_id, self.chunker.name)

    def index(self, url: str, repo_id: str | None = None) -> RepoRecord:
        cloned = clone_repo(url, self.repos_dir, repo_id=repo_id, timeout=self.clone_timeout)
        return self.index_checkout(cloned)

    def index_checkout(self, cloned: ClonedRepo) -> RepoRecord:
        name = self.collection_for(cloned.repo_id)
        self.store.delete_collection(name)
        collection = self.store.collection(name)
        sources = walk_repo(Path(cloned.local_path), cloned.repo_id)
        files = self.add_sources(collection, sources)
        self.rebuild_bm25(collection)
        record = RepoRecord(
            repo_id=cloned.repo_id,
            url=cloned.url,
            local_path=cloned.local_path,
            commit_sha=cloned.commit_sha,
            collection=name,
            chunker=self.chunker.name,
            indexed_at=now_iso(),
            file_count=len(files),
            chunk_count=collection.count(),
            files=files,
        )
        self.registry.save(name, record)
        logger.info("indexed repo", extra={"repo_id": cloned.repo_id, "chunks": record.chunk_count})
        return record

    def bm25_path(self, name: str) -> Path:
        return self.bm25_dir / name

    def rebuild_bm25(self, collection: VectorCollection) -> BM25Index:
        index = BM25Index.build(collection.all_chunks())
        index.save(self.bm25_path(collection.name))
        return index

    def add_sources(self, collection: VectorCollection, sources: list[SourceFile]) -> dict[str, FileRecord]:
        files: dict[str, FileRecord] = {}
        all_chunks: list[Chunk] = []
        for source in sources:
            chunks = self.chunker.chunk(source)
            files[source.path] = FileRecord(
                content_hash=source.content_hash, chunk_ids=[chunk.chunk_id for chunk in chunks]
            )
            all_chunks.extend(chunks)
        unique = list({chunk.chunk_id: chunk for chunk in all_chunks}.values())
        if unique:
            embeddings = self.embedder.embed_documents([chunk.embedding_text for chunk in unique])
            collection.add(unique, embeddings)
        return files
