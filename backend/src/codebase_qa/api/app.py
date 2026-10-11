import hmac
import json
import logging
import queue
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from codebase_qa.api.answers import answer_request
from codebase_qa.api.rate_limit import DailyLimiter, SlidingWindowLimiter, client_ip, enforce, enforce_daily
from codebase_qa.api.schemas import (
    AskRequest,
    AskResponse,
    FeedbackIn,
    HealthOut,
    IndexRepoRequest,
    JobOut,
    ReindexOut,
    RepoOut,
    ScopeOut,
    StatsOut,
)
from codebase_qa.config import get_settings
from codebase_qa.container import Container
from codebase_qa.generation.llm import GenerationError, QuotaExhaustedError
from codebase_qa.indexing.access import is_valid_visitor
from codebase_qa.indexing.jobs import Job, JobManager, Progress
from codebase_qa.indexing.registry import RepoRecord
from codebase_qa.ingestion.git import repo_id_from_url
from codebase_qa.ingestion.github import InvalidRepoUrl, RepoTooLarge, check_remote_size, parse_github_url
from codebase_qa.logging_config import configure_logging
from codebase_qa.retrieval.filters import folder_counts, language_counts

logger = logging.getLogger("codebase_qa.api")
CLEANUP_INTERVAL_SECONDS = 600
QUOTA_MESSAGE = "The AI model's free daily quota is used up. Please try again tomorrow."


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def get_visitor(request: Request) -> str | None:
    visitor = request.headers.get("x-visitor-id", "").strip().lower()
    return visitor if is_valid_visitor(visitor) else None


Services = Annotated[Container, Depends(get_container)]
Jobs = Annotated[JobManager, Depends(get_jobs)]
Visitor = Annotated[str | None, Depends(get_visitor)]


def require_owner_password(request: Request) -> None:
    expected = request.app.state.container.settings.demo_password
    if not expected:
        return
    supplied = request.headers.get("x-demo-password", "")
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="re-indexing requires the owner password")


def visitor_ip(request: Request) -> str:
    return client_ip(request, request.app.state.container.settings.trust_proxy)


def limit_ask(request: Request) -> None:
    settings = request.app.state.container.settings
    enforce(request.app.state.ask_limiter, request, settings.trust_proxy)
    enforce_daily(
        request.app.state.ask_per_visitor,
        visitor_ip(request),
        f"You have used your {settings.ask_per_visitor_per_day} questions for today. Please come back tomorrow.",
    )
    enforce_daily(request.app.state.ask_site_wide, "all", "The demo has reached its daily question limit.")


def validate_repo_url(url: str, services: Container) -> tuple[str, str]:
    settings = services.settings
    if settings.allow_local_repos and url.startswith("file://"):
        return url, repo_id_from_url(url)
    repo = parse_github_url(url)
    headers = {"Authorization": f"Bearer {settings.github_token}"} if settings.github_token else {}
    with httpx.Client(headers=headers) as client:
        check_remote_size(repo, settings.max_repo_size_mb, client)
    return repo.url, repo.repo_id


def index_action(services: Container, url: str) -> Callable[[Progress], dict[str, Any]]:
    def action(progress: Progress) -> dict[str, Any]:
        record = services.indexer.index(url, progress=progress)
        services.answer_cache.invalidate(record.repo_id)
        return RepoOut.from_record(record).model_dump()

    return action


def reindex_action(services: Container, repo_id: str) -> Callable[[Progress], dict[str, Any]]:
    def action(progress: Progress) -> dict[str, Any]:
        record = services.repo_record(repo_id)
        if record is None:
            raise ValueError(f"repo {repo_id} is not indexed")
        _, report = services.indexer.reindex(record, progress=progress)
        services.answer_cache.invalidate(repo_id)
        return ReindexOut.from_report(report).model_dump()

    return action


def finished_index(jobs: JobManager, record: RepoRecord) -> JobOut:
    return JobOut.from_job(jobs.completed("index", record.repo_id, RepoOut.from_record(record).model_dump()))


def submit_index(services: Container, jobs: JobManager, url: str, repo_id: str) -> Job:
    active = jobs.active_for(repo_id)
    if active is not None:
        return active
    services.janitor.cleanup(keep=jobs.active_repo_ids() | {repo_id}, reserve=1)
    return jobs.submit("index", repo_id, index_action(services, url))


def auto_index_demo(services: Container, jobs: JobManager) -> None:
    url = services.settings.demo_repo_url
    if not url:
        return
    try:
        canonical, repo_id = validate_repo_url(url, services)
    except (InvalidRepoUrl, RepoTooLarge) as exc:
        logger.warning("demo repo not indexed", extra={"reason": str(exc)})
        return
    services.access.pin(repo_id)
    if services.repo_record(repo_id) is None:
        logger.info("auto-indexing demo repo", extra={"repo_id": repo_id})
        jobs.submit("index", repo_id, index_action(services, canonical))


def cleanup_loop(services: Container, jobs: JobManager, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            services.janitor.cleanup(keep=jobs.active_repo_ids())
        except Exception:
            logger.exception("repo cleanup failed")
        stop.wait(CLEANUP_INTERVAL_SECONDS)


def create_app(container: Container | None = None) -> FastAPI:
    services = container or Container(get_settings())
    settings = services.settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        auto_index_demo(services, app.state.jobs)
        stop = threading.Event()
        cleaner = threading.Thread(target=cleanup_loop, args=(services, app.state.jobs, stop), daemon=True)
        cleaner.start()
        yield
        stop.set()
        app.state.jobs.shutdown()

    app = FastAPI(title="Codebase Q&A", version="0.1.0", lifespan=lifespan)
    app.state.container = services
    app.state.jobs = JobManager()
    app.state.ask_limiter = SlidingWindowLimiter(settings.ask_rate_limit_per_minute, 60)
    app.state.ask_per_visitor = DailyLimiter(settings.ask_per_visitor_per_day)
    app.state.ask_site_wide = DailyLimiter(settings.ask_daily_limit)
    app.state.index_per_visitor = DailyLimiter(settings.index_per_visitor_per_day)
    app.state.feedback_limiter = SlidingWindowLimiter(30, 60)
    owner_only = [Depends(require_owner_password)]

    @app.middleware("http")
    async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error", extra={"request_id": request_id, "path": request.url.path})
            response = JSONResponse(status_code=500, content={"detail": "internal error", "request_id": request_id})
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    @app.get("/health", response_model=HealthOut)
    def health(services: Services, jobs: Jobs) -> HealthOut:
        return HealthOut(
            status="ok",
            repos=len(services.repo_records()),
            active_jobs=jobs.running_count(),
            reindex_password_required=bool(services.settings.demo_password),
            index_per_visitor_per_day=services.settings.index_per_visitor_per_day,
            ask_per_visitor_per_day=services.settings.ask_per_visitor_per_day,
            repo_ttl_hours=services.settings.repo_ttl_hours,
        )

    @app.post("/repos", response_model=JobOut, status_code=202)
    def index_repo(
        body: IndexRepoRequest, request: Request, services: Services, jobs: Jobs, visitor: Visitor
    ) -> JobOut:
        if visitor is None:
            raise HTTPException(status_code=400, detail="missing or invalid X-Visitor-Id header")
        try:
            url, repo_id = validate_repo_url(body.url, services)
        except InvalidRepoUrl as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RepoTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        existing = services.repo_record(repo_id)
        if existing is not None and services.access.can_see(repo_id, visitor):
            services.access.touch(repo_id)
            return finished_index(jobs, existing)
        enforce_daily(
            request.app.state.index_per_visitor,
            visitor_ip(request),
            f"You can add {services.settings.index_per_visitor_per_day} repositories per day. Please come back later.",
        )
        services.access.grant(repo_id, visitor)
        if existing is not None:
            return finished_index(jobs, existing)
        return JobOut.from_job(submit_index(services, jobs, url, repo_id))

    @app.get("/repos", response_model=list[RepoOut])
    def list_repos(services: Services, visitor: Visitor) -> list[RepoOut]:
        return [RepoOut.from_record(record) for record in services.visible_records(visitor)]

    @app.post("/feedback", status_code=201)
    def feedback(body: FeedbackIn, request: Request, services: Services) -> dict[str, str]:
        enforce(request.app.state.feedback_limiter, request, services.settings.trust_proxy)
        record = services.recent_answers.get(body.answer_id)
        if record is None:
            raise HTTPException(status_code=404, detail="this answer is too old to rate; ask again to rate it")
        services.feedback.add(record, body.rating, body.comment.strip())
        return {"status": "recorded"}

    @app.get("/stats", response_model=StatsOut)
    def stats(services: Services) -> StatsOut:
        return StatsOut.from_stats(services.stats.stats(), services.settings.gemini_model)

    @app.get("/repos/{repo_id}/scope", response_model=ScopeOut)
    def repo_scope(repo_id: str, services: Services, visitor: Visitor) -> ScopeOut:
        record = services.repo_record(repo_id)
        if record is None or not services.access.can_see(repo_id, visitor):
            raise HTTPException(status_code=404, detail=f"repo {repo_id} is not indexed")
        return ScopeOut(folders=folder_counts(record.files), languages=language_counts(record.files))

    @app.post("/repos/{repo_id}/reindex", response_model=JobOut, status_code=202, dependencies=owner_only)
    def reindex_repo(repo_id: str, services: Services, jobs: Jobs) -> JobOut:
        if services.repo_record(repo_id) is None:
            raise HTTPException(status_code=404, detail=f"repo {repo_id} is not indexed")
        services.access.touch(repo_id)
        job = jobs.active_for(repo_id) or jobs.submit("reindex", repo_id, reindex_action(services, repo_id))
        return JobOut.from_job(job)

    @app.get("/jobs/{job_id}", response_model=JobOut)
    def get_job(job_id: str, jobs: Jobs) -> JobOut:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return JobOut.from_job(job)

    @app.post("/ask", response_model=AskResponse)
    def ask(body: AskRequest, request: Request, services: Services, visitor: Visitor) -> AskResponse:
        record = authorize_ask(body, request, services, visitor)
        try:
            return answer_request(services, record, body)
        except QuotaExhaustedError as exc:
            raise HTTPException(status_code=503, detail=QUOTA_MESSAGE) from exc
        except GenerationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/ask/stream")
    def ask_stream(body: AskRequest, request: Request, services: Services, visitor: Visitor) -> StreamingResponse:
        record = authorize_ask(body, request, services, visitor)
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        worker = threading.Thread(target=stream_answer, args=(services, record, body, events), daemon=True)
        worker.start()

        def lines() -> Iterator[str]:
            while (event := events.get()) is not None:
                yield json.dumps(event) + "\n"

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    return app


def authorize_ask(body: AskRequest, request: Request, services: Container, visitor: str | None) -> RepoRecord:
    record = services.repo_record(body.repo_id)
    if record is None or not services.access.can_see(body.repo_id, visitor):
        raise HTTPException(status_code=404, detail=f"repo {body.repo_id} is not indexed")
    limit_ask(request)
    services.access.touch(body.repo_id)
    return record


def stream_answer(
    services: Container, record: RepoRecord, body: AskRequest, events: "queue.Queue[dict[str, Any] | None]"
) -> None:
    try:
        response = answer_request(services, record, body, lambda text: events.put({"type": "delta", "text": text}))
        events.put({"type": "final", "response": response.model_dump()})
    except QuotaExhaustedError:
        events.put({"type": "error", "detail": QUOTA_MESSAGE})
    except GenerationError as exc:
        events.put({"type": "error", "detail": str(exc)})
    except Exception:
        logger.exception("streamed answer failed", extra={"repo_id": record.repo_id})
        events.put({"type": "error", "detail": "internal error"})
    finally:
        events.put(None)


app = create_app()
