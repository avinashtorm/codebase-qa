from pydantic import BaseModel, Field

from codebase_qa.generation.grounding import snippet_for
from codebase_qa.indexing.registry import RepoRecord
from codebase_qa.qa import AskResult


class IndexRepoRequest(BaseModel):
    url: str = Field(min_length=1, max_length=300)


class RepoOut(BaseModel):
    repo_id: str
    url: str
    commit_sha: str
    chunker: str
    indexed_at: str
    file_count: int
    chunk_count: int

    @classmethod
    def from_record(cls, record: RepoRecord) -> "RepoOut":
        return cls(
            repo_id=record.repo_id,
            url=record.url,
            commit_sha=record.commit_sha,
            chunker=record.chunker,
            indexed_at=record.indexed_at,
            file_count=record.file_count,
            chunk_count=record.chunk_count,
        )


class AskRequest(BaseModel):
    repo_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=2000)


class CitationOut(BaseModel):
    path: str
    start_line: int
    end_line: int
    language: str
    snippet: str


class ContextChunkOut(BaseModel):
    path: str
    start_line: int
    end_line: int
    language: str
    score: float
    scores: dict[str, float]
    content: str


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    context: list[ContextChunkOut]
    timings_ms: dict[str, float]
    used_llm: bool
    invalid_citations: int
    commit_sha: str

    @classmethod
    def from_result(cls, result: AskResult, commit_sha: str) -> "AskResponse":
        languages = {item.chunk.path: item.chunk.language for item in result.context}
        return cls(
            answer=result.answer.answer,
            citations=[
                CitationOut(
                    path=c.path,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    language=languages.get(c.path, "text"),
                    snippet=snippet_for(c, result.context),
                )
                for c in result.answer.citations
            ],
            context=[
                ContextChunkOut(
                    path=item.chunk.path,
                    start_line=item.chunk.start_line,
                    end_line=item.chunk.end_line,
                    language=item.chunk.language,
                    score=item.score,
                    scores=item.scores,
                    content=item.chunk.content,
                )
                for item in result.context
            ],
            timings_ms=result.timings_ms,
            used_llm=result.answer.used_llm,
            invalid_citations=result.answer.invalid_citations,
            commit_sha=commit_sha,
        )
