import json
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.container import Container
from codebase_qa.generation.llm import LLMResponse
from codebase_qa.observability.store import QuestionLog, StatsStore, percentile
from codebase_qa.observability.usage import CURRENT_METER, MeteredLLM, Pricing, UsageMeter
from tests.fakes import VISITOR_A, FakeLLM, fake_embedder, make_settings, wait_for_job

RepoFactory = Callable[..., Path]


def test_pricing_and_meter_skip_cached_calls_in_cost() -> None:
    meter = UsageMeter()
    meter.record(LLMResponse("a", 1_000_000, 0), "AnswerSchema")
    meter.record(LLMResponse("b", 1_000_000, 1_000_000, cached=True), "AnswerSchema")
    assert (meter.calls, meter.cached_calls, meter.input_tokens) == (2, 1, 2_000_000)
    assert meter.cost(Pricing(0.10, 0.40)) == 0.10


def test_metered_llm_records_complete_and_stream_into_current_meter() -> None:
    llm = MeteredLLM(FakeLLM({"text": lambda _: "hello world"}))
    meter = UsageMeter()
    token = CURRENT_METER.set(meter)
    try:
        llm.complete("s", "prompt")
        assert "".join(llm.stream("s", "prompt")) == "hello world"
    finally:
        CURRENT_METER.reset(token)
    assert meter.calls == 2 and meter.purposes == ["text", "text"]
    llm.complete("s", "outside a request")
    assert meter.calls == 2


def test_stats_store_aggregates_latency_cost_and_refusals(tmp_path: Path) -> None:
    store = StatsStore(tmp_path / "stats.sqlite3")
    for ms, refused in ((100.0, False), (200.0, True), (300.0, False), (1000.0, False)):
        store.record(QuestionLog("r", "code", refused, "high", ms, {"generation": ms / 2}, 2, 0, 100, 20, 0.001))
    store.record(QuestionLog("r", "error", False, "none", 50.0, error="GenerationError"))
    stats = store.stats()
    assert (stats.questions, stats.errors) == (5, 1)
    assert stats.avg_latency_ms == 400.0 and stats.p95_latency_ms == 1000.0
    assert stats.refusal_rate == 0.25 and stats.total_cost_usd == 0.004
    assert stats.avg_stage_ms == {"generation": 200.0}
    assert percentile([], 0.95) == 0.0


def test_api_records_each_question_and_serves_stats(tmp_path: Path, make_repo: RepoFactory) -> None:
    answer = json.dumps(
        {"answer": "AuthService.login", "citations": [{"path": "app/auth.py", "start_line": 2, "end_line": 3}]}
    )
    llm = FakeLLM({"AnswerSchema": lambda _: answer})
    container = Container(make_settings(tmp_path / "data"), embedder_factory=fake_embedder, llm_factory=lambda _: llm)
    headers = {"X-Visitor-Id": VISITOR_A}
    with TestClient(create_app(container)) as client:
        job = client.post("/repos", json={"url": make_repo().as_uri()}, headers=headers).json()
        wait_for_job(client, job["job_id"], headers)
        client.post("/ask", json={"repo_id": "origin", "question": "AuthService login token"}, headers=headers)
        client.post("/ask/stream", json={"repo_id": "origin", "question": "AuthService login token"}, headers=headers)
        stats = client.get("/stats").json()
    assert stats["questions"] == 2 and stats["errors"] == 0
    assert stats["llm_calls"] >= 2 and stats["input_tokens"] > 0
    assert "generation" in stats["avg_stage_ms"] and stats["model"]
