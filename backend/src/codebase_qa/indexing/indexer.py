import logging
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from codebase_qa.fs import remove_tree
from codebase_qa.indexing.changes import ChangeSet, detect_changes
from codebase_qa.indexing.jobs import Progress
from codebase_qa.indexing.registry import FileRecord, RepoRecord, RepoRegistry
from codebase_qa.ingestion.git import clone_repo, pull_latest
from codebase_qa.ingestion.github import RepoTooLarge, directory_size_bytes
from codebase_qa.ingestion.walker import MAX_FILE_BYTES, load_source_file, walk_repo
from codebase_qa.interfaces import Chunker, Embedder
from codebase_qa.models import Chunk, ClonedRepo, SourceFile
from codebase_qa.retrieval.bm25 import BM25Index
from codebase_qa.retrieval.vector_store import ChromaStore, VectorCollection, collection_name
from codebase_qa.timing import timed

logger = logging.getLogger(__name__)


def ignore_progress(_: str) -> None:
    return None


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ReindexReport:
    repo_id: str
    old_sha: str
    new_sha: str
    method: str
    files_added: int
    files_modified: int
    files_deleted: int
    files_renamed: int
    chunks_added: int
    chunks_removed: int
    seconds: float
    stage_ms: dict[str, float]

    @property
    def files_changed(self) -> int:
        return self.files_added + self.files_modified + self.files_deleted + self.files_renamed


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
        max_repo_bytes: int | None = None,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.chunker = chunker
        self.registry = registry
        self.repos_dir = repos_dir
        self.bm25_dir = bm25_dir
        self.clone_timeout = clone_timeout
        self.max_repo_bytes = max_repo_bytes

    def collection_for(self, repo_id: str) -> str:
        return collection_name(repo_id, self.chunker.name)

    def index(self, url: str, repo_id: str | None = None, progress: Progress = ignore_progress) -> RepoRecord:
        progress("cloning repository")
        cloned = clone_repo(url, self.repos_dir, repo_id=repo_id, timeout=self.clone_timeout)
        self.enforce_size_limit(Path(cloned.local_path))
        return self.index_checkout(cloned, progress)

    def enforce_size_limit(self, checkout: Path) -> None:
        if self.max_repo_bytes is None:
            return
        size = directory_size_bytes(checkout)
        if size > self.max_repo_bytes:
            remove_tree(checkout)
            limit_mb = self.max_repo_bytes // (1024 * 1024)
            raise RepoTooLarge(f"repository checkout is {size // (1024 * 1024)} MB, the limit is {limit_mb} MB")

    def index_checkout(self, cloned: ClonedRepo, progress: Progress = ignore_progress) -> RepoRecord:
        name = self.collection_for(cloned.repo_id)
        self.store.delete_collection(name)
        collection = self.store.collection(name)
        progress("reading files")
        sources = walk_repo(Path(cloned.local_path), cloned.repo_id)
        progress(f"chunking and embedding {len(sources)} files")
        files = self.add_sources(collection, sources)
        progress("building keyword index")
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

    def reindex(self, record: RepoRecord, progress: Progress = ignore_progress) -> tuple[RepoRecord, ReindexReport]:
        started = time.perf_counter()
        stages: dict[str, float] = {}
        repo_path = Path(record.local_path)
        progress("pulling latest commit")
        new_sha = timed(stages, "pull", lambda: pull_latest(repo_path, timeout=self.clone_timeout))
        if new_sha == record.commit_sha:
            changes = ChangeSet(method="unchanged")
        else:
            changes = timed(
                stages,
                "detect_changes",
                lambda: detect_changes(repo_path, record.repo_id, record.commit_sha, new_sha, record.files),
            )
        collection = self.store.collection(record.collection)
        removed = timed(stages, "delete_chunks", lambda: collection.delete_paths(changes.removed_paths))
        removed_paths = set(changes.removed_paths)
        files = {path: entry for path, entry in record.files.items() if path not in removed_paths}
        sources = [
            source
            for path in changes.changed_paths
            if (source := load_source_file(repo_path, path, record.repo_id, MAX_FILE_BYTES)) is not None
        ]
        progress(f"re-indexing {len(sources)} changed files")
        added_files = timed(stages, "chunk_embed_add", lambda: self.add_sources(collection, sources))
        files.update(added_files)
        if changes.file_count:
            timed(stages, "bm25_rebuild", lambda: self.rebuild_bm25(collection))
        updated = replace(
            record,
            commit_sha=new_sha,
            indexed_at=now_iso(),
            file_count=len(files),
            chunk_count=collection.count(),
            files=files,
        )
        self.registry.save(record.collection, updated)
        report = ReindexReport(
            repo_id=record.repo_id,
            old_sha=record.commit_sha,
            new_sha=new_sha,
            method=changes.method,
            files_added=len(changes.added),
            files_modified=len(changes.modified),
            files_deleted=len(changes.deleted),
            files_renamed=len(changes.renamed),
            chunks_added=len({cid for entry in added_files.values() for cid in entry.chunk_ids}),
            chunks_removed=removed,
            seconds=round(time.perf_counter() - started, 3),
            stage_ms=stages,
        )
        logger.info("reindexed repo", extra={"repo_id": record.repo_id, "files_changed": report.files_changed})
        return updated, report

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
