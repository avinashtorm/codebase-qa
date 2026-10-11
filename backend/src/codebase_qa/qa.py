from dataclasses import dataclass, field, replace

from codebase_qa.generation.grounding import is_low_relevance, validate_citations
from codebase_qa.generation.refusal import NOT_FOUND_LEAD, closest_files, helpful_text, is_unknown, pick_suggestions
from codebase_qa.interfaces import Generator, Retriever
from codebase_qa.models import GeneratedAnswer, RetrievedChunk
from codebase_qa.routing.router import QuestionRouter, RouteDecision
from codebase_qa.routing.rules import Route
from codebase_qa.routing.tool import ToolAnswerer
from codebase_qa.timing import timed


@dataclass(frozen=True)
class Retrieval:
    route: Route
    route_method: str
    code: list[RetrievedChunk]
    overview: list[RetrievedChunk] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AskResult:
    answer: GeneratedAnswer
    context: list[RetrievedChunk]
    timings_ms: dict[str, float] = field(default_factory=dict)
    route: Route = "code"
    refused: bool = False
    suggestions: list[str] = field(default_factory=list)


class QAPipeline:
    def __init__(
        self,
        retriever: Retriever,
        generator: Generator,
        top_k: int = 8,
        refusal_thresholds: dict[str, float] | None = None,
        router: QuestionRouter | None = None,
        overview: Retriever | None = None,
        tool: ToolAnswerer | None = None,
        overview_k: int = 3,
        suggestions: list[str] | None = None,
    ) -> None:
        self.retriever = retriever
        self.generator = generator
        self.top_k = top_k
        self.refusal_thresholds = refusal_thresholds or {}
        self.router = router
        self.overview = overview
        self.tool = tool or ToolAnswerer(None)
        self.overview_k = overview_k
        self.suggestions = suggestions or []

    def route(self, question: str) -> RouteDecision:
        if self.router is None:
            return RouteDecision("code", "disabled")
        return self.router.route(question)

    def retrieve(self, question: str, depth: int) -> Retrieval:
        timings: dict[str, float] = {}
        decision = timed(timings, "routing", lambda: self.route(question))
        if decision.route == "tool":
            return Retrieval("tool", decision.method, [], [], timings)
        code = timed(timings, "retrieval", lambda: self.retriever.retrieve(question, depth))
        timings.update(self.retriever.timings)
        overview: list[RetrievedChunk] = []
        overview_retriever = self.overview
        if decision.route == "overview" and overview_retriever is not None:
            overview = overview_retriever.retrieve(question, self.overview_k)
            timings.update(overview_retriever.timings)
        return Retrieval(decision.route, decision.method, code, overview, timings)

    def context_for(self, retrieval: Retrieval) -> list[RetrievedChunk]:
        if not retrieval.overview:
            return retrieval.code[: self.top_k]
        code_slots = max(self.top_k - len(retrieval.overview), 0)
        return retrieval.overview + retrieval.code[:code_slots]

    def ask(self, question: str) -> AskResult:
        return self.answer(question, self.retrieve(question, self.top_k))

    def answer(self, question: str, retrieval: Retrieval) -> AskResult:
        timings = dict(retrieval.timings_ms)
        if retrieval.route == "tool":
            answered = timed(timings, "generation", lambda: self.tool.answer(question))
            return AskResult(answer=answered, context=[], timings_ms=timings, route="tool")
        context = self.context_for(retrieval)
        if retrieval.route == "code" and is_low_relevance(context, self.refusal_thresholds):
            return self.helpful(NOT_FOUND_LEAD, context, timings, retrieval.route, used_llm=False)
        generated = timed(timings, "generation", lambda: self.generator.generate(question, context))
        valid, invalid = validate_citations(generated.citations, context)
        grounded = replace(generated, citations=valid, invalid_citations=generated.invalid_citations + invalid)
        if is_unknown(grounded):
            return self.helpful(grounded.answer, context, timings, retrieval.route, grounded.invalid_citations)
        return AskResult(answer=grounded, context=context, timings_ms=timings, route=retrieval.route)

    def helpful(
        self,
        lead: str,
        context: list[RetrievedChunk],
        timings: dict[str, float],
        route: Route,
        invalid_citations: int = 0,
        used_llm: bool = True,
    ) -> AskResult:
        suggestions = pick_suggestions(self.suggestions)
        text = helpful_text(lead, closest_files(context), suggestions)
        answer = GeneratedAnswer(answer=text, citations=[], used_llm=used_llm, invalid_citations=invalid_citations)
        return AskResult(
            answer=answer, context=context, timings_ms=timings, route=route, refused=True, suggestions=suggestions
        )
