from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.config import Settings
from codebase_qa.container import Container
from codebase_qa.generation.openai_generator import GenerationError
from tests.fakes import fake_embedder, fake_generator

RepoFactory = Callable[..., Path]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
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
    assert set(body["timings_ms"]) == {"retrieval", "generation"}


def test_ask_unknown_repo_returns_404(client: TestClient) -> None:
    response = client.post("/ask", json={"repo_id": "nope", "question": "hi"})
    assert response.status_code == 404


def test_index_bad_url_returns_400(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/repos", json={"url": (tmp_path / "missing").as_uri()})
    assert response.status_code == 400


class FailingGenerator:
    def generate(self, question: str, context: list) -> None:
        raise GenerationError("language model request failed: RateLimitError")


def test_generation_failure_returns_503(tmp_path: Path, make_repo: RepoFactory) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    container = Container(
        settings, embedder_factory=fake_embedder, generator_factory=lambda _: FailingGenerator()
    )
    client = TestClient(create_app(container))
    client.post("/repos", json={"url": make_repo().as_uri()})
    response = client.post("/ask", json={"repo_id": "origin", "question": "login"})
    assert response.status_code == 503
    assert response.json() == {"detail": "language model request failed: RateLimitError"}
