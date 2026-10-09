from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFile:
    repo_id: str
    path: str
    language: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class ClonedRepo:
    repo_id: str
    url: str
    local_path: str
    commit_sha: str
