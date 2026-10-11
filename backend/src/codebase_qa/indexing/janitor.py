import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from codebase_qa.fs import remove_tree
from codebase_qa.indexing.access import AccessStore, utc_now
from codebase_qa.indexing.registry import RepoRegistry
from codebase_qa.retrieval.vector_store import ChromaStore

logger = logging.getLogger(__name__)


class RepoJanitor:
    def __init__(
        self,
        registry: RepoRegistry,
        store: ChromaStore,
        access: AccessStore,
        repos_dir: Path,
        bm25_dir: Path,
        ttl: timedelta,
        max_repos: int,
        overview_dir: Path | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.registry = registry
        self.store = store
        self.access = access
        self.repos_dir = repos_dir
        self.bm25_dir = bm25_dir
        self.ttl = ttl
        self.max_repos = max_repos
        self.clock = clock
        self.overview_dir = overview_dir

    def last_used(self) -> dict[str, datetime]:
        entries = self.access.load()
        indexed = {record.repo_id: record.indexed_at for record in self.registry.list()}
        used: dict[str, datetime] = {}
        for repo_id in set(indexed) | set(entries):
            entry = entries.get(repo_id)
            if entry is not None and entry.pinned:
                continue
            stamp = entry.last_used_at if entry is not None and entry.last_used_at else indexed.get(repo_id)
            if stamp:
                used[repo_id] = parse(stamp)
        return used

    def removable(self, keep: set[str], reserve: int = 0) -> list[str]:
        used = {repo_id: stamp for repo_id, stamp in self.last_used().items() if repo_id not in keep}
        cutoff = self.clock() - self.ttl
        expired = sorted(repo_id for repo_id, stamp in used.items() if stamp < cutoff)
        remaining = sorted((stamp, repo_id) for repo_id, stamp in used.items() if repo_id not in expired)
        overflow = len(remaining) + reserve - self.max_repos
        return expired + [repo_id for _, repo_id in remaining[: max(0, overflow)]]

    def cleanup(self, keep: set[str] | None = None, reserve: int = 0) -> list[str]:
        removed = self.removable(keep or set(), reserve)
        for repo_id in removed:
            self.delete(repo_id)
        if removed:
            logger.info("removed visitor repos", extra={"repo_ids": removed})
        return removed

    def delete(self, repo_id: str) -> None:
        for key, record in self.registry.load_all().items():
            if record.repo_id == repo_id:
                self.store.delete_collection(record.collection)
                remove_tree(self.bm25_dir / record.collection)
                if self.overview_dir is not None:
                    (self.overview_dir / f"{record.collection}.json").unlink(missing_ok=True)
                self.registry.delete(key)
        remove_tree(self.repos_dir / repo_id)
        self.access.remove(repo_id)


def parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)
