import json
import logging
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.api.rate_limit import SlidingWindowLimiter
from codebase_qa.container import Container
from codebase_qa.indexing.jobs import JobManager
from codebase_qa.ingestion.github import (
    GitHubRepo,
    InvalidRepoUrl,
    RepoTooLarge,
    check_remote_size,
    parse_github_url,
)
from codebase_qa.logging_config import JsonFormatter
from tests.fakes import fake_embedder, fake_generator, make_settings, wait_for_job

RepoFactory = Callable[..., Path]


def build_client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = make_settings(tmp_path / "data", **overrides)
    container = Container(settings, embedder_factory=fake_embedder, generator_factory=fake_generator)
    return TestClient(create_app(container))


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/fastapi/full-stack-fastapi-template",
        "https://github.com/fastapi/full-stack-fastapi-template/",
        "https://github.com/a-b/c.d_e.git",
    ],
)
def test_accepts_github_repo_urls(url: str) -> None:
    repo = parse_github_url(url)
    assert repo.url.startswith("https://github.com/")
    assert not repo.url.endswith((".git", "/"))


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://gitlab.com/a/b",
        "https://github.com/a",
        "https://github.com/a/b/tree/main",
        "https://github.com/a/b?x=1",
        "https://github.com.evil.com/a/b",
        "git@github.com:a/b.git",
        "file:///etc/passwd",
        "https://github.com/-a/b",
        "https://github.com/a/..",
        "https://github.com/a/b c",
    ],
)
def test_rejects_other_urls(url: str) -> None:
    with pytest.raises(InvalidRepoUrl):
        parse_github_url(url)


def github_api(status: int, payload: dict) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)))


def test_remote_size_limit() -> None:
    repo = GitHubRepo("a", "b")
    check_remote_size(repo, 10, github_api(200, {"size": 5 * 1024}))
    with pytest.raises(RepoTooLarge):
        check_remote_size(repo, 10, github_api(200, {"size": 50 * 1024}))
    with pytest.raises(InvalidRepoUrl):
        check_remote_size(repo, 10, github_api(404, {}))
    check_remote_size(repo, 10, github_api(403, {"message": "rate limited"}))


def test_api_rejects_non_github_urls_and_file_urls_in_production(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path, allow_local_repos=False) as client:
        assert client.post("/repos", json={"url": "https://gitlab.com/a/b"}).status_code == 400
        assert client.post("/repos", json={"url": make_repo().as_uri()}).status_code == 400


def test_checkout_over_size_limit_fails_job_and_is_deleted(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path, max_repo_size_mb=0) as client:
        job_id = client.post("/repos", json={"url": make_repo().as_uri()}).json()["job_id"]
        job = wait_for_job(client, job_id)
    assert job["status"] == "failed"
    assert "limit is 0 MB" in job["error"]
    assert not (tmp_path / "data" / "repos" / "origin").exists()


def test_repo_count_is_capped(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path, max_repos=1) as client:
        first = client.post("/repos", json={"url": make_repo().as_uri()}).json()
        assert wait_for_job(client, first["job_id"])["status"] == "succeeded"
        other = tmp_path / "other"
        other.mkdir()
        response = client.post("/repos", json={"url": other.as_uri()})
        assert response.status_code == 409
        again = client.post("/repos", json={"url": (tmp_path / "origin").as_uri()})
        assert again.status_code == 202
        assert wait_for_job(client, again.json()["job_id"])["status"] == "succeeded"


def test_sliding_window_limiter() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    assert limiter.check("ip") is None
    assert limiter.check("ip") is None
    assert limiter.check("ip") == pytest.approx(60.0)
    assert limiter.check("other") is None
    now[0] = 60.0
    assert limiter.check("ip") is None


def test_ask_is_rate_limited_per_ip(tmp_path: Path) -> None:
    with build_client(tmp_path, ask_rate_limit_per_minute=2) as client:
        statuses = [client.post("/ask", json={"repo_id": "x", "question": "q"}).status_code for _ in range(3)]
        assert statuses == [404, 404, 429]
        limited = client.post("/ask", json={"repo_id": "x", "question": "q"})
        assert int(limited.headers["Retry-After"]) >= 1
        other_ip = client.post(
            "/ask", json={"repo_id": "x", "question": "q"}, headers={"X-Forwarded-For": "10.0.0.9"}
        )
        assert other_ip.status_code == 429


def test_forwarded_ip_is_used_only_when_proxy_is_trusted(tmp_path: Path) -> None:
    with build_client(tmp_path, ask_rate_limit_per_minute=1, trust_proxy=True) as client:
        body = {"repo_id": "x", "question": "q"}
        first = client.post("/ask", json=body, headers={"X-Forwarded-For": "1.1.1.1"})
        second = client.post("/ask", json=body, headers={"X-Forwarded-For": "2.2.2.2"})
        third = client.post("/ask", json=body, headers={"X-Forwarded-For": "1.1.1.1"})
        assert (first.status_code, second.status_code, third.status_code) == (404, 404, 429)


def test_index_endpoint_is_rate_limited(tmp_path: Path) -> None:
    with build_client(tmp_path, index_rate_limit_per_hour=1) as client:
        client.post("/repos", json={"url": "https://gitlab.com/a/b"})
        assert client.post("/repos", json={"url": "https://gitlab.com/a/b"}).status_code == 429


def test_demo_password_protects_everything_but_health(tmp_path: Path) -> None:
    with build_client(tmp_path, demo_password="s3cret") as client:
        assert client.get("/health").json()["password_required"] is True
        assert client.get("/repos").status_code == 401
        assert client.get("/repos", headers={"X-Demo-Password": "wrong"}).status_code == 401
        assert client.get("/repos", headers={"X-Demo-Password": "s3cret"}).status_code == 200


def test_jobs_track_status_and_unknown_jobs_404(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path) as client:
        accepted = client.post("/repos", json={"url": make_repo().as_uri()})
        assert accepted.status_code == 202
        body = accepted.json()
        assert body["status"] in ("queued", "running", "succeeded")
        assert body["repo_id"] == "origin"
        job = wait_for_job(client, body["job_id"])
        assert job["status"] == "succeeded" and job["progress"] == "done" and job["finished_at"]
        assert client.get("/jobs/does-not-exist").status_code == 404
        assert client.get("/health").json()["repos"] == 1


def test_job_manager_hides_unexpected_error_details() -> None:
    manager = JobManager()

    def explode(_: Callable[[str], None]) -> dict:
        raise KeyError("secret internal detail")

    job = manager.submit("index", "r", explode)
    manager.executor.shutdown(wait=True)
    assert job.status == "failed"
    assert job.error == "internal error"


def test_unhandled_errors_return_generic_500_without_traceback(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "data")
    container = Container(settings, embedder_factory=fake_embedder, generator_factory=fake_generator)

    def broken(repo_id: str) -> None:
        raise RuntimeError("database exploded at /secret/path")

    container.repo_record = broken
    with TestClient(create_app(container), raise_server_exceptions=False) as client:
        response = client.post("/ask", json={"repo_id": "x", "question": "q"})
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "internal error"
    assert "secret" not in response.text and "Traceback" not in response.text
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_demo_repo_is_auto_indexed_on_startup(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path, demo_repo_url=make_repo().as_uri()) as client:
        jobs = client.app.state.jobs
        [job] = list(jobs.jobs.values())
        assert wait_for_job(client, job.job_id)["status"] == "succeeded"
    with build_client(tmp_path, demo_repo_url=(tmp_path / "origin").as_uri()) as client:
        assert client.app.state.jobs.jobs == {}


def test_json_log_formatter_includes_extra_fields() -> None:
    record = logging.LogRecord("api", logging.INFO, __file__, 1, "request", None, None)
    record.request_id = "abc"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "request" and payload["request_id"] == "abc" and payload["level"] == "INFO"
