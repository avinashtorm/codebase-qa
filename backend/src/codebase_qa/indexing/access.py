import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from codebase_qa.jsonfile import JsonFile

VISITOR_ID = re.compile(r"^[0-9a-f]{32}$")
TOUCH_INTERVAL = timedelta(seconds=60)


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_valid_visitor(visitor: str | None) -> bool:
    return bool(visitor) and VISITOR_ID.match(visitor or "") is not None


@dataclass
class RepoAccess:
    pinned: bool = False
    owners: list[str] = field(default_factory=list)
    last_used_at: str = ""

    def visible_to(self, visitor: str | None) -> bool:
        return visitor is not None and visitor in self.owners


class AccessStore:
    def __init__(
        self, path: Path, clock: Callable[[], datetime] = utc_now, touch_interval: timedelta = TOUCH_INTERVAL
    ) -> None:
        self.path = path
        self.clock = clock
        self.touch_interval = touch_interval
        self.file = JsonFile(path)
        self.lock = threading.Lock()

    def load(self) -> dict[str, RepoAccess]:
        return {repo_id: RepoAccess(**entry) for repo_id, entry in self.file.read().items()}

    def write(self, entries: dict[str, RepoAccess]) -> None:
        self.file.write({key: asdict(value) for key, value in entries.items()})

    def update(self, repo_id: str, change: Callable[[RepoAccess], None]) -> None:
        with self.lock:
            entries = self.load()
            entry = entries.setdefault(repo_id, RepoAccess())
            change(entry)
            entry.last_used_at = self.clock().isoformat(timespec="seconds")
            self.write(entries)

    def grant(self, repo_id: str, visitor: str) -> None:
        def add_owner(entry: RepoAccess) -> None:
            if visitor not in entry.owners:
                entry.owners.append(visitor)

        self.update(repo_id, add_owner)

    def pin(self, repo_id: str) -> None:
        def set_pinned(entry: RepoAccess) -> None:
            entry.pinned = True

        self.update(repo_id, set_pinned)

    def touch(self, repo_id: str) -> None:
        entry = self.load().get(repo_id)
        if entry is not None and entry.last_used_at:
            if self.clock() - datetime.fromisoformat(entry.last_used_at) < self.touch_interval:
                return
        self.update(repo_id, lambda entry: None)

    def can_see(self, repo_id: str, visitor: str | None) -> bool:
        entry = self.load().get(repo_id)
        return entry is not None and entry.visible_to(visitor)

    def visible(self, visitor: str | None) -> set[str]:
        return {repo_id for repo_id, entry in self.load().items() if entry.visible_to(visitor)}

    def remove(self, repo_id: str) -> None:
        with self.lock:
            entries = self.load()
            if entries.pop(repo_id, None) is not None:
                self.write(entries)
