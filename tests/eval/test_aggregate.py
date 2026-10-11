import pytest

from codebase_qa.generation.llm import QuotaExhaustedError
from codebase_qa.models import Chunk, RetrievedChunk
from eval.aggregate import aggregate, judge_metrics, refusal_metrics
from eval.dataset import parse_question
from eval.judge import judge, judge_prompt
from tests.fakes import FakeLLM


def row(category: str, declined: bool, faithfulness: int = 5, relevance: int = 5) -> dict:
    return {
        "category": category,
        "declined": declined,
        "answer": "text",
        "invalid_citations": 0,
        "judge": {"faithfulness": faithfulness, "relevance": relevance},
        "latency_ms": {},
    }


def test_refusal_metrics_reward_refusing_only_unanswerable_questions() -> None:
    rows = [row("where-is", False), row("where-is", True), row("unanswerable", True), row("unanswerable", False)]
    metrics = refusal_metrics(rows)
    assert metrics == {
        "refused": 2,
        "refusal_accuracy": 0.5,
        "answered_when_answerable": 0.5,
        "refused_when_unanswerable": 0.5,
    }


def test_judge_metrics_split_faithfulness_and_relevance_populations() -> None:
    rows = [row("where-is", False, 4, 5), row("where-is", True, 5, 1), row("unanswerable", True, 5, 1)]
    metrics = judge_metrics(rows)
    assert metrics["faithfulness_mean"] == 4.0 and metrics["relevance_mean"] == 3.0
    assert metrics["relevant_rate"] == 0.5 and metrics["judged"] == 3


def test_aggregate_skips_retrieval_for_questions_without_locations() -> None:
    scored = row("where-is", False) | {"retrieval": {"hit_at_1": 1.0, "hit_at_5": 1.0, "recall_at_10": 1.0, "mrr": 1.0}}
    metrics = aggregate([scored, row("overview", False) | {"retrieval": None}])
    assert metrics["hit_at_1"] == 1.0 and metrics["refusal_accuracy"] == 1.0


def test_dataset_accepts_open_categories_without_locations() -> None:
    assert parse_question({"id": "o1", "question": "q", "category": "overview", "expected_locations": []})
    with pytest.raises(ValueError):
        parse_question({"id": "c1", "question": "q", "category": "where-is", "expected_locations": []})
    location = {"path": "a.py", "start_line": 1, "end_line": 2}
    with pytest.raises(ValueError):
        parse_question({"id": "u1", "question": "q", "category": "unanswerable", "expected_locations": [location]})


def test_judge_parses_verdict_and_sees_context() -> None:
    verdict = {
        "unsupported_statements": ["It sends SMS"],
        "answers_question": "partially",
        "faithfulness": 3,
        "relevance": 4,
        "reason": "SMS is not shown",
    }
    llm = FakeLLM({"JudgeSchema": lambda _: verdict})
    context = [RetrievedChunk(Chunk("c", "r", "a.py", "python", 1, 2, "def login(): ..."), 0.9)]
    result = judge(llm, "How does login work?", "It checks and sends SMS.", context)
    assert result is not None and (result.faithfulness, result.relevance) == (3, 4)
    assert result.unsupported == ["It sends SMS"]
    assert 'source="a.py:1-2"' in llm.calls[0][2] and "It checks and sends SMS." in llm.calls[0][2]
    assert judge(FakeLLM({"JudgeSchema": lambda _: "bad"}), "q", "a", context) is None
    assert "(no code context was retrieved)" in judge_prompt("q", "a", [])


def raise_quota(_: str) -> object:
    raise QuotaExhaustedError("quota")


def test_judge_lets_quota_errors_stop_the_run() -> None:
    with pytest.raises(QuotaExhaustedError):
        judge(FakeLLM({"JudgeSchema": raise_quota}), "q", "a", [])
