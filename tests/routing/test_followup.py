from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.container import Container
from codebase_qa.routing.followup import FollowUpRewriter, Turn, format_history, needs_rewrite
from tests.fakes import VISITOR_A, FakeLLM, fake_embedder, fake_generator, make_settings, wait_for_job

RepoFactory = Callable[..., Path]
HISTORY = [Turn("user", "Where is login?"), Turn("assistant", "In `login` in app/auth.py.")]


def test_needs_rewrite_only_with_history_and_references() -> None:
    assert not needs_rewrite("How long is it valid?", [])
    assert needs_rewrite("How long is it valid?", HISTORY)
    assert needs_rewrite("And the tests?", HISTORY)
    assert needs_rewrite("What about this function?", HISTORY)
    assert not needs_rewrite("Where is the database session created for each request?", HISTORY)


def test_rewriter_uses_llm_and_history() -> None:
    llm = FakeLLM({"RewriteSchema": lambda _: {"question": "How long is the login token valid?"}})
    rewrite = FollowUpRewriter(llm).rewrite("How long is it valid?", HISTORY)
    assert (rewrite.question, rewrite.method) == ("How long is the login token valid?", "llm")
    assert "User: Where is login?" in llm.calls[0][2] and "Follow-up question: How long is it valid?" in llm.calls[0][2]


def test_rewriter_keeps_question_on_failure_or_standalone() -> None:
    llm = FakeLLM({"RewriteSchema": lambda _: "broken"})
    assert FollowUpRewriter(llm).rewrite("And it?", HISTORY).method == "unchanged"
    assert FollowUpRewriter(llm).rewrite("Where is the database session created for each request?", HISTORY).method == (
        "unchanged"
    )
    assert len(llm.calls) == 1


def test_history_is_truncated() -> None:
    long = [Turn("assistant", "x " * 1000)] * 10
    text = format_history(long)
    assert text.count("Assistant:") == 6 and all(len(line) < 620 for line in text.splitlines())


def test_api_rewrites_follow_up_before_retrieval(tmp_path: Path, make_repo: RepoFactory) -> None:
    llm = FakeLLM({"RewriteSchema": lambda _: {"question": "How does AuthService login work?"}})
    container = Container(
        make_settings(tmp_path / "data"),
        embedder_factory=fake_embedder,
        generator_factory=fake_generator,
        llm_factory=lambda _: llm,
    )
    headers = {"X-Visitor-Id": VISITOR_A}
    with TestClient(create_app(container)) as client:
        job = client.post("/repos", json={"url": make_repo().as_uri()}, headers=headers).json()
        wait_for_job(client, job["job_id"], headers)
        history = [{"role": "user", "content": "Where is login?"}, {"role": "assistant", "content": "auth.py"}]
        body = client.post(
            "/ask", json={"repo_id": "origin", "question": "How does it work?", "history": history}, headers=headers
        ).json()
        plain = client.post("/ask", json={"repo_id": "origin", "question": "How does it work?"}, headers=headers)
    assert body["standalone_question"] == "How does AuthService login work?"
    assert body["context"][0]["path"] == "app/auth.py"
    assert plain.json()["standalone_question"] == "How does it work?"
