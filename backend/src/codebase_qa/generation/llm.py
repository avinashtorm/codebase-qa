from collections.abc import Iterator
from dataclasses import dataclass

from pydantic import BaseModel


class GenerationError(RuntimeError):
    pass


class QuotaExhaustedError(GenerationError):
    pass


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False


class OfflineLLM:
    model = "offline"

    def complete(self, system: str, prompt: str, schema: type[BaseModel] | None = None) -> LLMResponse:
        raise GenerationError("no language model is configured")

    def stream(self, system: str, prompt: str, schema: type[BaseModel] | None = None) -> Iterator[str]:
        raise GenerationError("no language model is configured")
