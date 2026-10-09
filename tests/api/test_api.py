from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.config import Settings
from codebase_qa.container import Container
from codebase_qa.generation.gemini_generator import GenerationError
from tests.conftest import FIXTURE_FILES
from tests.fakes import fake_embedder, fake_generator

RepoFactory = Callable[..., Path]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", min_vector_score=0.0)
    container = Container(settings, embedder_factory=fake_embedder, generator_factory=fake_generator)
    return TestClient(create_app(container))


def test_index_list_and_ask(client: TestClient, make_repo: RepoFactory) -> None:
    origin = make_repo()
    indexed = client.post("/repos", json={"url": origin.as_uri()})
    assert indexed.status_code == 200
    repo = indexed.json()
    assert repo["repo_id"] == "origin"
    assert repo["file_count"] == 4
    assert repo["chunk_count"] >= 4

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


def test_index_bad_url_returns_400(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/repos", json={"url": (tmp_path / "missing").as_uri()})
    assert response.status_code == 400


class FailingGenerator:
    def generate(self, question: str, context: list) -> None:
        raise GenerationError("language model request failed with status 429")


def test_generation_failure_returns_503(tmp_path: Path, make_repo: RepoFactory) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", min_vector_score=0.0)
    container = Container(
        settings, embedder_factory=fake_embedder, generator_factory=lambda _: FailingGenerator()
    )
    client = TestClient(create_app(container))
    client.post("/repos", json={"url": make_repo().as_uri()})
    response = client.post("/ask", json={"repo_id": "origin", "question": "login"})
    assert response.status_code == 503
    assert response.json() == {"detail": "language model request failed with status 429"}


def test_low_relevance_question_is_refused_without_llm(tmp_path: Path, make_repo: RepoFactory) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", min_vector_score=0.99)
    container = Container(settings, embedder_factory=fake_embedder, generator_factory=fake_generator)
    client = TestClient(create_app(container))
    client.post("/repos", json={"url": make_repo().as_uri()})
    body = client.post("/ask", json={"repo_id": "origin", "question": "banana bread recipe"}).json()
    assert body["used_llm"] is False
    assert body["citations"] == []
    assert "generation" not in body["timings_ms"]


def test_ask_returns_snippets_with_original_line_numbers(client: TestClient, make_repo: RepoFactory) -> None:
    client.post("/repos", json={"url": make_repo().as_uri()})
    body = client.post("/ask", json={"repo_id": "origin", "question": "AuthService login token"}).json()
    citation = body["citations"][0]
    source_lines = str(FIXTURE_FILES[citation["path"]]).splitlines()
    expected = source_lines[citation["start_line"] - 1 : citation["end_line"]]
    assert citation["snippet"].splitlines() == expected
    assert citation["language"] == "python"
    assert len(body["commit_sha"]) == 40
