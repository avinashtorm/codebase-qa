import json
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.api.rate_limit import DailyLimiter, SlidingWindowLimiter
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
from tests.conftest import commit_all, git, write_files
from tests.fakes import VISITOR_A, VISITOR_B, fake_embedder, fake_generator, make_settings, wait_for_job

RepoFactory = Callable[..., Path]


def build_client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = make_settings(tmp_path / "data", **overrides)
    container = Container(settings, embedder_factory=fake_embedder, generator_factory=fake_generator)
    return TestClient(create_app(container), headers={"X-Visitor-Id": VISITOR_A})


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




def test_sliding_window_limiter() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    assert limiter.check("ip") is None
    assert limiter.check("ip") is None
    assert limiter.check("ip") == pytest.approx(60.0)
    assert limiter.check("other") is None
    now[0] = 60.0
    assert limiter.check("ip") is None










def test_daily_limiter_resets_on_a_new_day() -> None:
    days = iter([date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 2)])
    limiter = DailyLimiter(limit=2, today=lambda: next(days))
    assert [limiter.allow(), limiter.allow(), limiter.allow(), limiter.allow()] == [True, True, False, True]




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




def test_json_log_formatter_includes_extra_fields() -> None:
    record = logging.LogRecord("api", logging.INFO, __file__, 1, "request", None, None)
    record.request_id = "abc"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "request" and payload["request_id"] == "abc" and payload["level"] == "INFO"


def second_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "second"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    write_files(repo, {"lib/tool.py": "def tool() -> int:\n    return 1\n"})
    commit_all(repo, "initial")
    return repo


def add(client: TestClient, url: str, visitor: str = VISITOR_A, **headers: str) -> dict:
    response = client.post("/repos", json={"url": url}, headers={"X-Visitor-Id": visitor, **headers})
    assert response.status_code == 202, response.text
    return wait_for_job(client, response.json()["job_id"])


def visible(client: TestClient, visitor: str) -> list[str]:
    return [repo["repo_id"] for repo in client.get("/repos", headers={"X-Visitor-Id": visitor}).json()]


def test_repositories_are_private_to_the_visitor_who_added_them(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path) as client:
        url = make_repo().as_uri()
        assert add(client, url)["status"] == "succeeded"
        assert visible(client, VISITOR_A) == ["origin"]
        assert visible(client, VISITOR_B) == []
        question = {"repo_id": "origin", "question": "login"}
        assert client.post("/ask", json=question, headers={"X-Visitor-Id": VISITOR_B}).status_code == 404
        reused = client.post("/repos", json={"url": url}, headers={"X-Visitor-Id": VISITOR_B}).json()
        assert reused["status"] == "succeeded" and reused["result"]["repo_id"] == "origin"
        assert visible(client, VISITOR_B) == ["origin"]
        assert client.post("/ask", json=question, headers={"X-Visitor-Id": VISITOR_B}).status_code == 200


def test_adding_a_repository_needs_a_visitor_id(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path) as client:
        response = client.post("/repos", json={"url": make_repo().as_uri()}, headers={"X-Visitor-Id": "nope"})
        assert response.status_code == 400
        assert client.get("/repos", headers={"X-Visitor-Id": ""}).json() == []


def test_visitors_can_add_a_limited_number_of_repositories_per_day(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path, index_per_visitor_per_day=1) as client:
        url = make_repo().as_uri()
        assert add(client, url)["status"] == "succeeded"
        assert client.post("/repos", json={"url": url}).json()["status"] == "succeeded"
        limited = client.post("/repos", json={"url": second_repo(tmp_path).as_uri()})
        assert limited.status_code == 429
        assert "1 repositories per day" in limited.json()["detail"]


def test_reindexing_needs_the_owner_password(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path, demo_password="s3cret") as client:
        add(client, make_repo().as_uri())
        assert client.get("/health").json()["reindex_password_required"] is True
        assert client.post("/repos/origin/reindex").status_code == 401
        accepted = client.post("/repos/origin/reindex", headers={"X-Demo-Password": "s3cret"})
        assert accepted.status_code == 202


def test_questions_are_limited_per_minute_and_per_day_for_each_visitor(
    tmp_path: Path, make_repo: RepoFactory
) -> None:
    body = {"repo_id": "origin", "question": "login"}
    with build_client(tmp_path, ask_rate_limit_per_minute=2) as client:
        add(client, make_repo().as_uri())
        statuses = [client.post("/ask", json=body).status_code for _ in range(3)]
        assert statuses == [200, 200, 429]
        assert int(client.post("/ask", json=body).headers["Retry-After"]) >= 1
    with build_client(tmp_path / "daily", ask_per_visitor_per_day=2, trust_proxy=True) as client:
        add(client, (tmp_path / "origin").as_uri())
        first_ip = {"X-Forwarded-For": "1.1.1.1"}
        statuses = [client.post("/ask", json=body, headers=first_ip).status_code for _ in range(3)]
        assert statuses == [200, 200, 429]
        assert "questions for today" in client.post("/ask", json=body, headers=first_ip).json()["detail"]
        assert client.post("/ask", json=body, headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200


def test_optional_site_wide_daily_question_cap(tmp_path: Path, make_repo: RepoFactory) -> None:
    body = {"repo_id": "origin", "question": "login"}
    with build_client(tmp_path, ask_daily_limit=2, trust_proxy=True) as client:
        add(client, make_repo().as_uri())
        statuses = [
            client.post("/ask", json=body, headers={"X-Forwarded-For": f"10.0.0.{n}"}).status_code for n in range(3)
        ]
        assert statuses == [200, 200, 429]


def test_demo_repo_is_auto_indexed_pinned_and_visible_to_everyone(
    tmp_path: Path, make_repo: RepoFactory
) -> None:
    with build_client(tmp_path, demo_repo_url=make_repo().as_uri()) as client:
        [job] = list(client.app.state.jobs.jobs.values())
        assert wait_for_job(client, job.job_id)["status"] == "succeeded"
        assert visible(client, VISITOR_B) == ["origin"]
    with build_client(tmp_path, demo_repo_url=(tmp_path / "origin").as_uri()) as client:
        assert client.app.state.jobs.jobs == {}
        assert visible(client, VISITOR_A) == ["origin"]

