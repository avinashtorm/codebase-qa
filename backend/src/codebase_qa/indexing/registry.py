import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from codebase_qa.jsonfile import JsonFile


@dataclass
class FileRecord:
    content_hash: str
    chunk_ids: list[str]


@dataclass
class RepoRecord:
    repo_id: str
    url: str
    local_path: str
    commit_sha: str
    collection: str
    chunker: str
    indexed_at: str
    file_count: int = 0
    chunk_count: int = 0
    overview_count: int = 0
    files: dict[str, FileRecord] = field(default_factory=dict)
    suggested_questions: list[str] = field(default_factory=list)
    branch: str = ""
    private: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "RepoRecord":
        files = {path: FileRecord(**record) for path, record in data.get("files", {}).items()}
        return cls(**{**data, "files": files})


class RepoRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file = JsonFile(path)
        self.lock = threading.Lock()

    def load_all(self) -> dict[str, RepoRecord]:
        return {key: RepoRecord.from_dict(value) for key, value in self.file.read().items()}

    def get(self, key: str) -> RepoRecord | None:
        return self.load_all().get(key)

    def list(self) -> list[RepoRecord]:
        return sorted(self.load_all().values(), key=lambda record: record.repo_id)

    def save(self, key: str, record: RepoRecord) -> None:
        with self.lock:
            records = self.load_all()
            records[key] = record
            self.write(records)

    def delete(self, key: str) -> None:
        with self.lock:
            records = self.load_all()
            if records.pop(key, None) is not None:
                self.write(records)

    def write(self, records: dict[str, RepoRecord]) -> None:
        self.file.write({key: asdict(record) for key, record in records.items()})
