import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors

from codebase_qa.generation.cache import ResponseCache
from codebase_qa.generation.gemini_llm import GeminiLLM
from codebase_qa.generation.generator import AnswerSchema, LLMGenerator
from codebase_qa.generation.llm import GenerationError, OfflineLLM, QuotaExhaustedError
from codebase_qa.models import Chunk, Citation, RetrievedChunk


class FakeModels:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict] = []

    def generate_content(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        usage = SimpleNamespace(prompt_token_count=120, candidates_token_count=30)
        return SimpleNamespace(text=outcome, usage_metadata=usage)


def make_llm(outcomes: list[object], cache: ResponseCache | None = None) -> tuple[GeminiLLM, FakeModels, list[float]]:
    models = FakeModels(outcomes)
    sleeps: list[float] = []
    client = SimpleNamespace(models=models)
    llm = GeminiLLM(client, "gemini-test", backoff_seconds=1.0, sleep=sleeps.append, cache=cache)
    return llm, models, sleeps


CONTEXT = [RetrievedChunk(Chunk("id", "r", "app/auth.py", "python", 1, 7, "def login(): ..."), 0.9)]


def test_generate_returns_answer_and_citations() -> None:
    llm, models, _ = make_llm(["Login lives in app/auth.py:1-7."])
    answer = LLMGenerator(llm).generate("Where is login?", CONTEXT)
    assert answer.citations == [Citation("app/auth.py", 1, 7)]
    assert models.calls[0]["model"] == "gemini-test"
    assert "[app/auth.py:1-7]" in models.calls[0]["contents"]


def test_complete_reports_token_usage() -> None:
    llm, _, _ = make_llm(["hello"])
    response = llm.complete("system", "prompt")
    assert (response.text, response.input_tokens, response.output_tokens, response.cached) == ("hello", 120, 30, False)


def test_retries_rate_limits_with_backoff() -> None:
    rate_limited = errors.ClientError(429, {"error": {"message": "quota"}})
    llm, _, sleeps = make_llm([rate_limited, rate_limited, "ok app/auth.py:1-2"])
    assert LLMGenerator(llm).generate("q", CONTEXT).answer == "ok app/auth.py:1-2"
    assert sleeps == [1.0, 2.0]


def test_non_retryable_error_raises_generation_error() -> None:
    llm, _, sleeps = make_llm([errors.ClientError(400, {"error": {"message": "bad key"}})])
    with pytest.raises(GenerationError, match="status 400"):
        llm.complete("s", "p")
    assert sleeps == []


def test_daily_quota_is_not_retried() -> None:
    quota = errors.ClientError(429, {"error": {"message": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}})
    llm, _, sleeps = make_llm([quota])
    with pytest.raises(QuotaExhaustedError):
        llm.complete("s", "p")
    assert sleeps == []


def test_cache_avoids_repeat_requests_and_keeps_usage(tmp_path: Path) -> None:
    llm, models, _ = make_llm(["first"], cache=ResponseCache(tmp_path))
    first = llm.complete("s", "p")
    second = llm.complete("s", "p")
    assert first.text == second.text == "first"
    assert second.cached and second.input_tokens == 120
    assert len(models.calls) == 1


def test_cache_key_depends_on_schema(tmp_path: Path) -> None:
    llm, models, _ = make_llm(["plain", json.dumps({"answer": "a", "citations": []})], cache=ResponseCache(tmp_path))
    llm.complete("s", "p")
    llm.complete("s", "p", AnswerSchema)
    assert len(models.calls) == 2


def test_structured_json_response_is_parsed_into_citations() -> None:
    citation = {"path": "app/auth.py", "start_line": 2, "end_line": 4}
    payload = json.dumps({"answer": "Login is in AuthService.", "citations": [citation]})
    llm, models, _ = make_llm([payload])
    answer = LLMGenerator(llm).generate("Where is login?", CONTEXT)
    assert answer.answer == "Login is in AuthService."
    assert answer.citations == [Citation("app/auth.py", 2, 4)]
    assert models.calls[0]["config"].response_mime_type == "application/json"


def test_offline_llm_raises_generation_error() -> None:
    with pytest.raises(GenerationError):
        OfflineLLM().complete("s", "p")
