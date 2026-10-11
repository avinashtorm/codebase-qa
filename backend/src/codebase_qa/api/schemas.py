from typing import Any

from pydantic import BaseModel, Field

from codebase_qa.generation.grounding import snippet_for
from codebase_qa.indexing.indexer import ReindexReport
from codebase_qa.indexing.jobs import Job
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


class JobOut(BaseModel):
    job_id: str
    kind: str
    repo_id: str
    status: str
    progress: str
    result: dict[str, Any] | None
    error: str | None
    created_at: str
    finished_at: str | None

    @classmethod
    def from_job(cls, job: Job) -> "JobOut":
        return cls(
            job_id=job.job_id,
            kind=job.kind,
            repo_id=job.repo_id,
            status=job.status,
            progress=job.progress,
            result=job.result,
            error=job.error,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )


class HealthOut(BaseModel):
    status: str
    repos: int
    active_jobs: int
    reindex_password_required: bool
    index_per_visitor_per_day: int
    ask_per_visitor_per_day: int
    repo_ttl_hours: float


class ReindexOut(BaseModel):
    repo_id: str
    old_sha: str
    new_sha: str
    method: str
    files_changed: int
    files_added: int
    files_modified: int
    files_deleted: int
    files_renamed: int
    chunks_added: int
    chunks_removed: int
    seconds: float
    stage_ms: dict[str, float]

    @classmethod
    def from_report(cls, report: ReindexReport) -> "ReindexOut":
        return cls(
            repo_id=report.repo_id,
            old_sha=report.old_sha,
            new_sha=report.new_sha,
            method=report.method,
            files_changed=report.files_changed,
            files_added=report.files_added,
            files_modified=report.files_modified,
            files_deleted=report.files_deleted,
            files_renamed=report.files_renamed,
            chunks_added=report.chunks_added,
            chunks_removed=report.chunks_removed,
            seconds=report.seconds,
            stage_ms=report.stage_ms,
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
    route: str

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
            route=result.route,
        )
