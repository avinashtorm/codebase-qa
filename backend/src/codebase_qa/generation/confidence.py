from dataclasses import dataclass, field
from typing import Literal

from codebase_qa.generation.selfcheck import SelfCheck
from codebase_qa.models import Citation, GeneratedAnswer, RetrievedChunk, is_overview_path

Level = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class Confidence:
    level: Level
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConfidencePolicy:
    high_score: float = 0.70
    low_score: float = 0.63
    top_ranks: int = 3


DEFAULT_POLICY = ConfidencePolicy()


def top_vector_score(context: list[RetrievedChunk]) -> float | None:
    values = [item.scores["vector"] for item in context if "vector" in item.scores]
    return max(values) if values else None


def cited_rank(citations: list[Citation], context: list[RetrievedChunk]) -> int | None:
    ranked = [item.chunk for item in context if "callee" not in item.scores and not is_overview_path(item.chunk.path)]
    for rank, chunk in enumerate(ranked, start=1):
        for citation in citations:
            if (
                chunk.path == citation.path
                and chunk.start_line <= citation.end_line
                and citation.start_line <= chunk.end_line
            ):
                return rank
    return None


def assess(
    answer: GeneratedAnswer,
    context: list[RetrievedChunk],
    refused: bool,
    check: SelfCheck,
    policy: ConfidencePolicy = DEFAULT_POLICY,
) -> Confidence:
    if refused:
        return Confidence("low", ["no matching code was found"])
    if not answer.citations:
        return Confidence("low", ["the answer has no verified citation"])
    score = top_vector_score(context)
    if score is not None and score < policy.low_score:
        return Confidence("low", [f"weak search match ({score:.2f})"])
    reasons: list[str] = []
    rank = cited_rank(answer.citations, context)
    if rank is None or rank > policy.top_ranks:
        reasons.append("cited code was not among the top search results")
    if answer.invalid_citations:
        reasons.append(f"{answer.invalid_citations} citation(s) outside the retrieved code were dropped")
    if not check.ran:
        reasons.append("claims were not self-checked")
    elif check.unsupported:
        reasons.append(f"self-check removed {len(check.unsupported)} unsupported claim(s)")
    if score is None or score < policy.high_score:
        reasons.append("moderate search match" if score is None else f"moderate search match ({score:.2f})")
    if reasons:
        return Confidence("medium", reasons)
    return Confidence("high", ["cited code ranks at the top of the search and every claim passed the self-check"])
