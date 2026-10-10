from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.container import Container
from codebase_qa.generation.gemini_generator import GenerationError, QuotaExhaustedError
from tests.conftest import FIXTURE_FILES
from tests.fakes import VISITOR_A, fake_embedder, fake_generator, make_settings, wait_for_job

RepoFactory = Callable[..., Path]


def build_client(tmp_path: Path, generator_factory: Callable = fake_generator, **overrides: object) -> TestClient:
    settings = make_settings(tmp_path / "data", **overrides)
    container = Container(settings, embedder_factory=fake_embedder, generator_factory=generator_factory)
    return TestClient(create_app(container), headers={"X-Visitor-Id": VISITOR_A})


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with build_client(tmp_path) as test_client:
        yield test_client


def index(client: TestClient, url: str) -> dict:
    response = client.post("/repos", json={"url": url})
    assert response.status_code == 202
    job = wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded", job
    return job


def test_index_list_and_ask(client: TestClient, make_repo: RepoFactory) -> None:
    job = index(client, make_repo().as_uri())
    assert job["kind"] == "index"
    assert job["result"]["repo_id"] == "origin"
    assert job["result"]["file_count"] == 4

    listed = client.get("/repos").json()
    assert [r["repo_id"] for r in listed] == ["origin"]

    answer = client.post("/ask", json={"repo_id": "origin", "question": "AuthService login token"})
    assert answer.status_code == 200
    body = answer.json()
    assert body["context"][0]["path"] == "app/auth.py"
    assert body["citations"][0]["path"] == "app/auth.py"
    assert {"retrieval", "embed_query", "vector_search", "generation"} <= set(body["timings_ms"])


def test_ask_unknown_repo_returns_404(client: TestClient) -> None:
    response = client.post("/ask", json={"repo_id": "nope", "question": "hi"})
    assert response.status_code == 404


def test_failed_clone_is_reported_on_the_job(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/repos", json={"url": (tmp_path / "missing").as_uri()})
    job = wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "failed"
    assert job["error"].startswith("git clone failed")
    assert str(tmp_path) not in job["error"] and "Users" not in job["error"]


class FailingGenerator:
    def generate(self, question: str, context: list) -> None:
        raise GenerationError("language model request failed with status 429")


def test_generation_failure_returns_503(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path, generator_factory=lambda _: FailingGenerator()) as client:
        index(client, make_repo().as_uri())
        response = client.post("/ask", json={"repo_id": "origin", "question": "login"})
    assert response.status_code == 503
    assert response.json() == {"detail": "language model request failed with status 429"}


def test_low_relevance_question_is_refused_without_llm(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path, min_vector_score=0.99) as client:
        index(client, make_repo().as_uri())
        body = client.post("/ask", json={"repo_id": "origin", "question": "banana bread recipe"}).json()
    assert body["used_llm"] is False
    assert body["citations"] == []
    assert "generation" not in body["timings_ms"]


def test_ask_returns_snippets_with_original_line_numbers(client: TestClient, make_repo: RepoFactory) -> None:
    index(client, make_repo().as_uri())
    body = client.post("/ask", json={"repo_id": "origin", "question": "AuthService login token"}).json()
    citation = body["citations"][0]
    source_lines = str(FIXTURE_FILES[citation["path"]]).splitlines()
    expected = source_lines[citation["start_line"] - 1 : citation["end_line"]]
    assert citation["snippet"].splitlines() == expected
    assert citation["language"] == "python"
    assert len(body["commit_sha"]) == 40


class QuotaGenerator:
    def generate(self, question: str, context: list) -> None:
        raise QuotaExhaustedError("daily quota exhausted for gemini")


def test_exhausted_llm_quota_gives_a_friendly_message(tmp_path: Path, make_repo: RepoFactory) -> None:
    with build_client(tmp_path, generator_factory=lambda _: QuotaGenerator()) as client:
        index(client, make_repo().as_uri())
        response = client.post("/ask", json={"repo_id": "origin", "question": "login"})
    assert response.status_code == 503
    assert "try again tomorrow" in response.json()["detail"]
