from dataclasses import dataclass, field
from pathlib import Path

from codebase_qa.indexing.registry import FileRecord
from codebase_qa.ingestion.git import GitError, diff_name_status
from codebase_qa.ingestion.walker import walk_repo


@dataclass
class ChangeSet:
    method: str
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def removed_paths(self) -> list[str]:
        return sorted({*self.modified, *self.deleted, *(old for old, _ in self.renamed), *self.added})

    @property
    def changed_paths(self) -> list[str]:
        return sorted({*self.added, *self.modified, *(new for _, new in self.renamed)})

    @property
    def file_count(self) -> int:
        return len(self.added) + len(self.modified) + len(self.deleted) + len(self.renamed)


def parse_name_status(rows: list[list[str]]) -> ChangeSet:
    changes = ChangeSet(method="git-diff")
    for row in rows:
        status = row[0]
        if status.startswith("R") and len(row) == 3:
            changes.renamed.append((row[1], row[2]))
        elif status.startswith("C") and len(row) == 3:
            changes.added.append(row[2])
        elif status == "A":
            changes.added.append(row[1])
        elif status == "D":
            changes.deleted.append(row[1])
        else:
            changes.modified.append(row[-1])
    return changes


def changes_by_hash(repo_path: Path, repo_id: str, known: dict[str, FileRecord]) -> ChangeSet:
    current = {source.path: source.content_hash for source in walk_repo(repo_path, repo_id)}
    return ChangeSet(
        method="hash",
        added=sorted(path for path in current if path not in known),
        modified=sorted(path for path in current if path in known and known[path].content_hash != current[path]),
        deleted=sorted(path for path in known if path not in current),
    )


def detect_changes(
    repo_path: Path, repo_id: str, old_sha: str, new_sha: str, known: dict[str, FileRecord]
) -> ChangeSet:
    try:
        return parse_name_status(diff_name_status(repo_path, old_sha, new_sha))
    except GitError:
        return changes_by_hash(repo_path, repo_id, known)
