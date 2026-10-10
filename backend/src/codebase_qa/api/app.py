import hmac
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from codebase_qa.api.rate_limit import DailyLimiter, SlidingWindowLimiter, enforce
from codebase_qa.api.schemas import (
    AskRequest,
    AskResponse,
    HealthOut,
    IndexRepoRequest,
    JobOut,
    ReindexOut,
    RepoOut,
)
from codebase_qa.config import get_settings
from codebase_qa.container import Container
from codebase_qa.generation.gemini_generator import GenerationError
from codebase_qa.indexing.jobs import Job, JobManager, Progress
from codebase_qa.ingestion.git import repo_id_from_url
from codebase_qa.ingestion.github import InvalidRepoUrl, RepoTooLarge, check_remote_size, parse_github_url
from codebase_qa.logging_config import configure_logging

logger = logging.getLogger("codebase_qa.api")


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_jobs(request: Request) -> JobManager:
    return request.app.state.jobs


Services = Annotated[Container, Depends(get_container)]
Jobs = Annotated[JobManager, Depends(get_jobs)]


def require_owner_password(request: Request) -> None:
    expected = request.app.state.container.settings.demo_password
    if not expected:
        return
    supplied = request.headers.get("x-demo-password", "")
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="indexing requires the owner password")


def limit_ask(request: Request) -> None:
    enforce(request.app.state.ask_limiter, request, request.app.state.container.settings.trust_proxy)
    if not request.app.state.daily_ask_limiter.allow():
        raise HTTPException(
            status_code=429,
            detail="the demo has reached its daily question limit, please try again tomorrow",
        )


def limit_index(request: Request) -> None:
    enforce(request.app.state.index_limiter, request, request.app.state.container.settings.trust_proxy)


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
        return RepoOut.from_record(record).model_dump()

    return action


def reindex_action(services: Container, repo_id: str) -> Callable[[Progress], dict[str, Any]]:
    def action(progress: Progress) -> dict[str, Any]:
        record = services.repo_record(repo_id)
        if record is None:
            raise ValueError(f"repo {repo_id} is not indexed")
        _, report = services.indexer.reindex(record, progress=progress)
        return ReindexOut.from_report(report).model_dump()

    return action


def submit_index(services: Container, jobs: JobManager, url: str, repo_id: str) -> Job:
    return jobs.active_for(repo_id) or jobs.submit("index", repo_id, index_action(services, url))


def auto_index_demo(services: Container, jobs: JobManager) -> None:
    url = services.settings.demo_repo_url
    if not url:
        return
    try:
        canonical, repo_id = validate_repo_url(url, services)
    except (InvalidRepoUrl, RepoTooLarge) as exc:
        logger.warning("demo repo not indexed", extra={"reason": str(exc)})
        return
    if services.repo_record(repo_id) is None:
        logger.info("auto-indexing demo repo", extra={"repo_id": repo_id})
        submit_index(services, jobs, canonical, repo_id)


def create_app(container: Container | None = None) -> FastAPI:
    services = container or Container(get_settings())
    settings = services.settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        auto_index_demo(services, app.state.jobs)
        yield
        app.state.jobs.shutdown()

    app = FastAPI(title="Codebase Q&A", version="0.1.0", lifespan=lifespan)
    app.state.container = services
    app.state.jobs = JobManager()
    app.state.ask_limiter = SlidingWindowLimiter(settings.ask_rate_limit_per_minute, 60)
    app.state.index_limiter = SlidingWindowLimiter(settings.index_rate_limit_per_hour, 3600)
    app.state.daily_ask_limiter = DailyLimiter(settings.ask_daily_limit)
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
            indexing_password_required=bool(services.settings.demo_password),
        )

    @app.post("/repos", response_model=JobOut, status_code=202, dependencies=[*owner_only, Depends(limit_index)])
    def index_repo(body: IndexRepoRequest, services: Services, jobs: Jobs) -> JobOut:
        try:
            url, repo_id = validate_repo_url(body.url, services)
        except InvalidRepoUrl as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RepoTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        known = {record.repo_id for record in services.repo_records()}
        if repo_id not in known and len(known) >= services.settings.max_repos:
            raise HTTPException(status_code=409, detail=f"repository limit of {services.settings.max_repos} reached")
        return JobOut.from_job(submit_index(services, jobs, url, repo_id))

    @app.get("/repos", response_model=list[RepoOut])
    def list_repos(services: Services) -> list[RepoOut]:
        return [RepoOut.from_record(record) for record in services.repo_records()]

    @app.post("/repos/{repo_id}/reindex", response_model=JobOut, status_code=202, dependencies=owner_only)
    def reindex_repo(repo_id: str, services: Services, jobs: Jobs) -> JobOut:
        if services.repo_record(repo_id) is None:
            raise HTTPException(status_code=404, detail=f"repo {repo_id} is not indexed")
        job = jobs.active_for(repo_id) or jobs.submit("reindex", repo_id, reindex_action(services, repo_id))
        return JobOut.from_job(job)

    @app.get("/jobs/{job_id}", response_model=JobOut)
    def get_job(job_id: str, jobs: Jobs) -> JobOut:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return JobOut.from_job(job)

    @app.post("/ask", response_model=AskResponse, dependencies=[Depends(limit_ask)])
    def ask(body: AskRequest, services: Services) -> AskResponse:
        record = services.repo_record(body.repo_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"repo {body.repo_id} is not indexed")
        try:
            result = services.pipeline(record).ask(body.question)
        except GenerationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return AskResponse.from_result(result, record.commit_sha)

    return app


app = create_app()
