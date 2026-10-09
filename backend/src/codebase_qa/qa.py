import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from codebase_qa.interfaces import Generator, Retriever
from codebase_qa.models import GeneratedAnswer, RetrievedChunk

T = TypeVar("T")


@dataclass(frozen=True)
class AskResult:
    answer: GeneratedAnswer
    context: list[RetrievedChunk]
    timings_ms: dict[str, float] = field(default_factory=dict)


class QAPipeline:
    def __init__(self, retriever: Retriever, generator: Generator, top_k: int = 8) -> None:
        self.retriever = retriever
        self.generator = generator
        self.top_k = top_k

    def ask(self, question: str) -> AskResult:
        timings: dict[str, float] = {}
        context = timed(timings, "retrieval", lambda: self.retriever.retrieve(question, self.top_k))
        answer = timed(timings, "generation", lambda: self.generator.generate(question, context))
        return AskResult(answer=answer, context=context, timings_ms=timings)


def timed(timings: dict[str, float], stage: str, action: Callable[[], T]) -> T:
    started = time.perf_counter()
    result = action()
    timings[stage] = round((time.perf_counter() - started) * 1000, 1)
    return result
