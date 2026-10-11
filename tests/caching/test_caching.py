import json
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.caching.answers import AnswerCache, answer_key, normalize_question
from codebase_qa.container import Container
from codebase_qa.embedding.cache import CachingEmbedder, EmbeddingStore
from tests.fakes import VISITOR_A, FakeLLM, HashingEmbedder, fake_embedder, make_settings, wait_for_job

RepoFactory = Callable[..., Path]


class CountingEmbedder(HashingEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.documents = 0
        self.queries = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents += len(texts)
        return super().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        self.queries += 1
        return super().embed_query(text)


def test_embedding_cache_reuses_vectors_by_content(tmp_path: Path) -> None:
    inner = CountingEmbedder()
    embedder = CachingEmbedder(inner, EmbeddingStore(tmp_path / "e.sqlite3"), "model-a")
    first = embedder.embed_documents(["alpha", "beta", "alpha"])
    second = embedder.embed_documents(["beta", "gamma"])
    assert inner.documents == 3 and (embedder.hits, embedder.misses) == (2, 3)
    assert first[0] == first[2] and second[0] == first[1]
    other_model = CachingEmbedder(inner, EmbeddingStore(tmp_path / "e.sqlite3"), "model-b")
    other_model.embed_documents(["alpha"])
    assert inner.documents == 4


def test_query_embeddings_use_a_small_lru(tmp_path: Path) -> None:
    inner = CountingEmbedder()
    embedder = CachingEmbedder(inner, EmbeddingStore(tmp_path / "e.sqlite3"), "m", query_cache_size=2)
    for text in ["a", "a", "b", "c", "a"]:
        embedder.embed_query(text)
    assert inner.queries == 4


def test_answer_cache_keys_and_invalidation(tmp_path: Path) -> None:
    assert normalize_question("  Where is   LOGIN? ") == "where is login"
    key = answer_key("repo", "sha1", "Where is login?", {"folder": ""}, "fp")
    assert key == answer_key("repo", "sha1", "where is login", {"folder": ""}, "fp")
    assert key != answer_key("repo", "sha2", "where is login", {"folder": ""}, "fp")
    assert key != answer_key("repo", "sha1", "where is login", {"folder": "app"}, "fp")
    cache = AnswerCache(tmp_path / "a.sqlite3")
    cache.put(key, "repo", "sha1", {"answer": "x"})
    assert cache.get(key) == {"answer": "x"} and cache.count("repo") == 1
    assert cache.invalidate("repo") == 1 and cache.get(key) is None


def build(tmp_path: Path, llm: FakeLLM) -> Container:
    return Container(make_settings(tmp_path / "data"), embedder_factory=fake_embedder, llm_factory=lambda _: llm)


def test_identical_question_is_served_from_the_answer_cache(tmp_path: Path, make_repo: RepoFactory) -> None:
    answer = json.dumps({"answer": "In login.", "citations": [{"path": "app/auth.py", "start_line": 2, "end_line": 3}]})
    llm = FakeLLM({"AnswerSchema": lambda _: answer})
    container = build(tmp_path, llm)
    headers = {"X-Visitor-Id": VISITOR_A}
    question = {"repo_id": "origin", "question": "AuthService login token?"}
    with TestClient(create_app(container)) as client:
        job = client.post("/repos", json={"url": make_repo().as_uri()}, headers=headers).json()
        wait_for_job(client, job["job_id"], headers)
        first = client.post("/ask", json=question, headers=headers).json()
        calls = len(llm.calls_for("AnswerSchema"))
        second = client.post("/ask", json=question | {"question": "authservice LOGIN token"}, headers=headers).json()
        streamed = client.post("/ask/stream", json=question, headers=headers).text
        with_history = question | {"history": [{"role": "user", "content": "hi"}]}
        client.post("/ask", json=with_history, headers=headers)
        after_history = len(llm.calls_for("AnswerSchema"))
        container.janitor.delete("origin")
    assert not first["cached"] and second["cached"] and second["answer"] == first["answer"]
    assert "answer_cache" in second["timings_ms"] and '"cached": true' in streamed
    assert after_history == calls + 1
    assert container.answer_cache.count("origin") == 0


def test_rebuild_reuses_cached_embeddings(tmp_path: Path, make_repo: RepoFactory) -> None:
    inner = CountingEmbedder()
    container = Container(
        make_settings(tmp_path / "data"), embedder_factory=lambda _: inner, llm_factory=lambda _: FakeLLM()
    )
    origin = make_repo()
    container.indexer.index(origin.as_uri())
    first = inner.documents
    container.indexer.index(origin.as_uri())
    assert first > 0 and inner.documents == first
