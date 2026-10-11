from dataclasses import dataclass, field


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


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    repo_id: str
    path: str
    language: str
    start_line: int
    end_line: int
    content: str
    header: str = ""
    kind: str = "code"

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    @property
    def embedding_text(self) -> str:
        return f"{self.header}\n{self.content}" if self.header else self.content


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float
    scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Citation:
    path: str
    start_line: int
    end_line: int

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    citations: list[Citation]
    used_llm: bool = True
    invalid_citations: int = 0
