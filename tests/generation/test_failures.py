from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from codebase_qa.generation.fallback import RATE_LIMIT_LEAD, UNAVAILABLE_LEAD, fallback_answer
from codebase_qa.generation.gemini_llm import GeminiLLM
from codebase_qa.generation.llm import GenerationError, LLMUnavailableError, QuotaExhaustedError, RateLimitedError
from codebase_qa.models import Chunk, Citation, RetrievedChunk
from codebase_qa.qa import QAPipeline


class Outcomes:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes

    def next(self) -> object:
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def generate_content(self, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(text=self.next(), usage_metadata=None)

    def generate_content_stream(self, **kwargs: object) -> list[SimpleNamespace]:
        return [SimpleNamespace(text=self.next(), usage_metadata=None)]


def llm(outcomes: list[object]) -> tuple[GeminiLLM, list[float]]:
    sleeps: list[float] = []
    client = SimpleNamespace(models=Outcomes(outcomes))
    return GeminiLLM(client, "m", backoff_seconds=1.0, sleep=sleeps.append, max_attempts=3), sleeps


def api_error(code: int, message: str = "error") -> errors.APIError:
    return (
        errors.ClientError(code, {"error": {"message": message}})
        if code < 500
        else errors.ServerError(code, {"error": {"message": message}})
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [(api_error(429), RateLimitedError), (api_error(503), LLMUnavailableError), (api_error(400), GenerationError)],
)
def test_final_failures_are_classified(failure: Exception, expected: type) -> None:
    model, _ = llm([failure, failure, failure])
    with pytest.raises(expected):
        model.complete("s", "p")


def test_network_errors_are_retried_with_exponential_backoff() -> None:
    model, sleeps = llm([httpx.ConnectError("down"), httpx.ReadTimeout("slow"), "ok"])
    assert model.complete("s", "p").text == "ok" and sleeps == [1.0, 2.0]
    failing, _ = llm([httpx.ConnectError("down")] * 3)
    with pytest.raises(LLMUnavailableError, match="unreachable"):
        failing.complete("s", "p")


def test_stream_retries_before_the_first_chunk() -> None:
    model, sleeps = llm([api_error(503), "hello"])
    assert list(model.stream("s", "p")) == ["hello"] and sleeps == [1.0]


CONTEXT = [
    RetrievedChunk(Chunk("o", "r", "@overview/repository", "overview", 1, 2, "x", kind="overview"), 0.9),
    RetrievedChunk(Chunk("a", "r", "app/auth.py", "python", 1, 9, "def login(): ..."), 0.8, {"vector": 0.8}),
    RetrievedChunk(Chunk("b", "r", "app/db.py", "python", 3, 5, "db"), 0.7, {"vector": 0.7}),
]


def test_fallback_lists_best_code_locations_as_valid_citations() -> None:
    answer = fallback_answer(RateLimitedError("busy"), CONTEXT)
    assert answer.answer.startswith(RATE_LIMIT_LEAD) and "`app/auth.py:1-9`" in answer.answer
    assert answer.citations == [Citation("app/auth.py", 1, 9), Citation("app/db.py", 3, 5)] and not answer.used_llm


class Retriever:
    name = "vector"
    timings: dict[str, float] = {}

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        return CONTEXT[1:]


@pytest.mark.parametrize("error", [LLMUnavailableError("down"), QuotaExhaustedError("quota")])
def test_pipeline_degrades_instead_of_failing(error: GenerationError) -> None:
    class Generator:
        def generate(self, question: str, context: list[RetrievedChunk]) -> object:
            raise error

    result = QAPipeline(Retriever(), Generator()).ask("Where is login?")
    assert result.degraded == type(error).__name__ and result.confidence.level == "low"
    assert result.answer.citations and result.answer.used_llm is False
    if isinstance(error, LLMUnavailableError):
        assert result.answer.answer.startswith(UNAVAILABLE_LEAD)
