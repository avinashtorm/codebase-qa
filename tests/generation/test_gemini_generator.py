from types import SimpleNamespace

import pytest
from google.genai import errors

from codebase_qa.generation.gemini_generator import GeminiGenerator, GenerationError
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
