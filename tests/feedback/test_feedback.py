import json
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.container import Container
from codebase_qa.feedback.export import main as export_main
from codebase_qa.feedback.store import AnswerRecord, FeedbackStore, RecentAnswers
from tests.fakes import VISITOR_A, fake_embedder, fake_generator, make_settings, wait_for_job

RepoFactory = Callable[..., Path]


def record(answer_id: str = "a" * 32) -> AnswerRecord:
    return AnswerRecord(answer_id, "repo", "sha", "Where is login?", "In auth.py", "code", "high", ["app/auth.py:1-2"])


def test_recent_answers_are_bounded() -> None:
    recent = RecentAnswers(capacity=2)
    for answer_id in ("a" * 32, "b" * 32, "c" * 32):
        recent.remember(record(answer_id))
    assert recent.get("a" * 32) is None and recent.get("c" * 32) is not None


def test_store_and_export_jsonl(tmp_path: Path) -> None:
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    store.add(record(), "up")
    store.add(record("b" * 32), "down", "wrong file")
    assert store.counts() == {"up": 1, "down": 1}
    out = tmp_path / "out" / "feedback.jsonl"
    export_main(["--db", str(tmp_path / "feedback.sqlite3"), "--out", str(out)])
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [row["rating"] for row in rows] == ["up", "down"] and rows[1]["comment"] == "wrong file"
    assert rows[0]["citations"] == ["app/auth.py:1-2"] and rows[0]["question"] == "Where is login?"


def test_feedback_endpoint_stores_server_side_answer(tmp_path: Path, make_repo: RepoFactory) -> None:
    container = Container(
        make_settings(tmp_path / "data"), embedder_factory=fake_embedder, generator_factory=fake_generator
    )
    headers = {"X-Visitor-Id": VISITOR_A}
    with TestClient(create_app(container)) as client:
        job = client.post("/repos", json={"url": make_repo().as_uri()}, headers=headers).json()
        wait_for_job(client, job["job_id"], headers)
        answer = client.post(
            "/ask", json={"repo_id": "origin", "question": "AuthService login"}, headers=headers
        ).json()
        saved = client.post("/feedback", json={"answer_id": answer["answer_id"], "rating": "down", "comment": "meh"})
        unknown = client.post("/feedback", json={"answer_id": "f" * 32, "rating": "up"})
        invalid = client.post("/feedback", json={"answer_id": answer["answer_id"], "rating": "maybe"})
    assert saved.status_code == 201 and unknown.status_code == 404 and invalid.status_code == 422
    [row] = list(container.feedback.rows())
    assert row["question"] == "AuthService login" and row["answer"] == answer["answer"] and row["rating"] == "down"
    assert row["retrieved"] and row["retrieved"][0]["location"].startswith("app/auth.py")
