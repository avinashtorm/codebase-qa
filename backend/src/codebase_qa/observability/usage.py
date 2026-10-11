from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field

from pydantic import BaseModel

from codebase_qa.generation.llm import LLMResponse
from codebase_qa.interfaces import LLM


@dataclass(frozen=True)
class Pricing:
    input_per_million: float = 0.10
    output_per_million: float = 0.40

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_million + output_tokens * self.output_per_million) / 1_000_000


@dataclass
class UsageMeter:
    calls: int = 0
    cached_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    billed_input: int = 0
    billed_output: int = 0
    purposes: list[str] = field(default_factory=list)

    def record(self, response: LLMResponse, purpose: str) -> None:
        self.calls += 1
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.purposes.append(purpose)
        if response.cached:
            self.cached_calls += 1
        else:
            self.billed_input += response.input_tokens
            self.billed_output += response.output_tokens

    def cost(self, pricing: Pricing) -> float:
        return pricing.cost(self.billed_input, self.billed_output)


CURRENT_METER: ContextVar[UsageMeter | None] = ContextVar("usage_meter", default=None)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class MeteredLLM:
    def __init__(self, inner: LLM) -> None:
        self.inner = inner
        self.model = inner.model

    def complete(self, system: str, prompt: str, schema: type[BaseModel] | None = None) -> LLMResponse:
        response = self.inner.complete(system, prompt, schema)
        meter = CURRENT_METER.get()
        if meter is not None:
            meter.record(response, schema.__name__ if schema else "text")
        return response

    def stream(self, system: str, prompt: str, schema: type[BaseModel] | None = None) -> Iterator[str]:
        parts: list[str] = []
        for chunk in self.inner.stream(system, prompt, schema):
            parts.append(chunk)
            yield chunk
        meter = CURRENT_METER.get()
        if meter is None:
            return
        usage = getattr(self.inner, "last_usage", None)
        text = "".join(parts)
        if not isinstance(usage, LLMResponse) or usage.text != text:
            usage = LLMResponse(text, estimate_tokens(system + prompt), estimate_tokens(text), cached=True)
        meter.record(usage, schema.__name__ if schema else "text")
