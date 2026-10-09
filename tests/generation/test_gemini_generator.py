import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors

from codebase_qa.generation.cache import ResponseCache
from codebase_qa.generation.gemini_generator import GeminiGenerator, GenerationError, QuotaExhaustedError
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
        return SimpleNamespace(text=outcome)


def make_generator(outcomes: list[object]) -> tuple[GeminiGenerator, FakeModels, list[float]]:
    models = FakeModels(outcomes)
    sleeps: list[float] = []
    client = SimpleNamespace(models=models)
    generator = GeminiGenerator(client, "gemini-test", backoff_seconds=1.0, sleep=sleeps.append)
    return generator, models, sleeps


CONTEXT = [RetrievedChunk(Chunk("id", "r", "app/auth.py", "python", 1, 7, "def login(): ..."), 0.9)]


def test_generate_returns_answer_and_citations() -> None:
    generator, models, _ = make_generator(["Login lives in app/auth.py:1-7."])
    answer = generator.generate("Where is login?", CONTEXT)
    assert answer.citations == [Citation("app/auth.py", 1, 7)]
    assert models.calls[0]["model"] == "gemini-test"
    assert "[app/auth.py:1-7]" in models.calls[0]["contents"]


def test_retries_rate_limits_with_backoff() -> None:
    rate_limited = errors.ClientError(429, {"error": {"message": "quota"}})
    generator, _, sleeps = make_generator([rate_limited, rate_limited, "ok app/auth.py:1-2"])
    assert generator.generate("q", CONTEXT).answer == "ok app/auth.py:1-2"
    assert sleeps == [1.0, 2.0]


def test_non_retryable_error_raises_generation_error() -> None:
    generator, _, sleeps = make_generator([errors.ClientError(400, {"error": {"message": "bad key"}})])
    with pytest.raises(GenerationError, match="status 400"):
        generator.generate("q", CONTEXT)
    assert sleeps == []


def test_daily_quota_is_not_retried() -> None:
    quota = errors.ClientError(429, {"error": {"message": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}})
    generator, _, sleeps = make_generator([quota])
    with pytest.raises(QuotaExhaustedError):
        generator.generate("q", CONTEXT)
    assert sleeps == []


def test_cache_avoids_repeat_requests(tmp_path: Path) -> None:
    models = FakeModels(["first app/auth.py:1-2"])
    generator = GeminiGenerator(SimpleNamespace(models=models), "m", cache=ResponseCache(tmp_path))
    assert generator.generate("q", CONTEXT).answer == generator.generate("q", CONTEXT).answer
    assert len(models.calls) == 1


def test_structured_json_response_is_parsed_into_citations() -> None:
    citation = {"path": "app/auth.py", "start_line": 2, "end_line": 4}
    payload = json.dumps({"answer": "Login is in AuthService.", "citations": [citation]})
    generator, models, _ = make_generator([payload])
    answer = generator.generate("Where is login?", CONTEXT)
    assert answer.answer == "Login is in AuthService."
    assert answer.citations == [Citation("app/auth.py", 2, 4)]
    config = models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
