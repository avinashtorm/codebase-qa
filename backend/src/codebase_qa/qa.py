from dataclasses import dataclass, field, replace

from codebase_qa.generation.grounding import is_low_relevance, validate_citations
from codebase_qa.interfaces import Generator, Retriever
from codebase_qa.models import GeneratedAnswer, RetrievedChunk
from codebase_qa.timing import timed

NOT_FOUND_ANSWER = (
    "The indexed repository doesn't seem to contain code related to this question, "
    "so I did not generate an answer."
)


@dataclass(frozen=True)
class AskResult:
    answer: GeneratedAnswer
    context: list[RetrievedChunk]
    timings_ms: dict[str, float] = field(default_factory=dict)


class QAPipeline:
    def __init__(
        self,
        retriever: Retriever,
        generator: Generator,
        top_k: int = 8,
        refusal_thresholds: dict[str, float] | None = None,
    ) -> None:
        self.retriever = retriever
        self.generator = generator
        self.top_k = top_k
        self.refusal_thresholds = refusal_thresholds or {}

    def ask(self, question: str) -> AskResult:
        timings: dict[str, float] = {}
        context = timed(timings, "retrieval", lambda: self.retriever.retrieve(question, self.top_k))
        timings.update(self.retriever.timings)
        return self.answer(question, context, timings)

    def answer(self, question: str, context: list[RetrievedChunk], timings: dict[str, float]) -> AskResult:
        if is_low_relevance(context, self.refusal_thresholds):
            refusal = GeneratedAnswer(answer=NOT_FOUND_ANSWER, citations=[], used_llm=False)
            return AskResult(answer=refusal, context=context, timings_ms=timings)
        generated = timed(timings, "generation", lambda: self.generator.generate(question, context))
        valid, invalid = validate_citations(generated.citations, context)
        grounded = replace(generated, citations=valid, invalid_citations=generated.invalid_citations + invalid)
        return AskResult(answer=grounded, context=context, timings_ms=timings)
