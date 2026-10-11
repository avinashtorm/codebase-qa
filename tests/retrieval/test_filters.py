from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.container import Container
from codebase_qa.retrieval.filters import NO_FILTER, SearchFilter, folder_counts, language_counts
from tests.fakes import VISITOR_A, VISITOR_B, FakeLLM, fake_embedder, fake_generator, make_settings, wait_for_job

RepoFactory = Callable[..., Path]
PATHS = ["app/main.py", "app/auth.py", "app/api/routes.py", "web/index.ts", "README.md"]


def test_filter_matches_folder_and_language() -> None:
    assert not NO_FILTER.active
    assert SearchFilter(folder="app/").allowed_paths(PATHS) == ["app/api/routes.py", "app/auth.py", "app/main.py"]
    assert SearchFilter(languages=("typescript",)).allowed_paths(PATHS) == ["web/index.ts"]
    assert SearchFilter(folder="app/api", languages=("python",)).allowed_paths(PATHS) == ["app/api/routes.py"]
    assert not SearchFilter(folder="ap").allows("app/main.py")


def test_scope_counts() -> None:
    assert folder_counts(PATHS) == {"app": 3, "app/api": 1, "web": 1}
    assert language_counts(PATHS) == {"python": 3, "typescript": 1, "markdown": 1}


def build(tmp_path: Path, mode: str = "vector") -> Container:
    return Container(
        make_settings(tmp_path / "data", retrieval_mode=mode),
        embedder_factory=fake_embedder,
        generator_factory=fake_generator,
        llm_factory=lambda _: FakeLLM(),
    )


def test_vector_and_bm25_respect_filters(tmp_path: Path, make_repo: RepoFactory) -> None:
    origin = make_repo()
    for mode in ("vector", "bm25", "hybrid"):
        container = build(tmp_path / mode, mode)
        record = container.indexer.index(origin.as_uri())
        web_only = container.retriever(record, SearchFilter(folder="web")).retrieve("login token greet", 5)
        assert web_only and {item.chunk.path for item in web_only} == {"web/index.ts"}
        nothing = container.retriever(record, SearchFilter(folder="missing")).retrieve("login", 5)
        assert nothing == []


def test_api_scope_and_filtered_ask(tmp_path: Path, make_repo: RepoFactory) -> None:
    headers = {"X-Visitor-Id": VISITOR_A}
    with TestClient(create_app(build(tmp_path))) as client:
        job = client.post("/repos", json={"url": make_repo().as_uri()}, headers=headers).json()
        wait_for_job(client, job["job_id"], headers)
        scope = client.get("/repos/origin/scope", headers=headers).json()
        hidden = client.get("/repos/origin/scope", headers={"X-Visitor-Id": VISITOR_B})
        body = {"repo_id": "origin", "question": "AuthService login", "filters": {"folder": "web", "languages": []}}
        filtered = client.post("/ask", json=body, headers=headers).json()
    assert scope["folders"] == {"app": 2, "web": 1} and scope["languages"]["python"] == 2
    assert hidden.status_code == 404
    assert {chunk["path"] for chunk in filtered["context"]} == {"web/index.ts"}
