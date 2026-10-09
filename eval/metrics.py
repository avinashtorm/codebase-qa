from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean
from typing import Protocol

from eval.dataset import Location


class Span(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def start_line(self) -> int: ...

    @property
    def end_line(self) -> int: ...


def overlaps(span: Span, location: Span) -> bool:
    return (
        span.path == location.path
        and span.start_line <= location.end_line
        and location.start_line <= span.end_line
    )


def is_hit(span: Span, expected: Sequence[Location]) -> bool:
    return any(overlaps(span, location) for location in expected)


def hit_at_k(ranked: Sequence[Span], expected: Sequence[Location], k: int) -> float:
    return float(any(is_hit(span, expected) for span in ranked[:k]))


def recall_at_k(ranked: Sequence[Span], expected: Sequence[Location], k: int) -> float:
    found = [location for location in expected if any(overlaps(span, location) for span in ranked[:k])]
    return len(found) / len(expected)


def reciprocal_rank(ranked: Sequence[Span], expected: Sequence[Location]) -> float:
    for rank, span in enumerate(ranked, start=1):
        if is_hit(span, expected):
            return 1.0 / rank
    return 0.0


@dataclass(frozen=True)
class RetrievalScores:
    hit_at_1: float
    hit_at_5: float
    recall_at_10: float
    mrr: float


def score_retrieval(ranked: Sequence[Span], expected: Sequence[Location]) -> RetrievalScores:
    return RetrievalScores(
        hit_at_1=hit_at_k(ranked, expected, 1),
        hit_at_5=hit_at_k(ranked, expected, 5),
        recall_at_10=recall_at_k(ranked, expected, 10),
        mrr=reciprocal_rank(ranked[:10], expected),
    )


@dataclass(frozen=True)
class CitationScores:
    citation_count: int
    correct_citations: int
    precision: float
    any_correct: float


def score_citations(citations: Sequence[Span], expected: Sequence[Location]) -> CitationScores:
    correct = sum(1 for citation in citations if is_hit(citation, expected))
    return CitationScores(
        citation_count=len(citations),
        correct_citations=correct,
        precision=correct / len(citations) if citations else 0.0,
        any_correct=float(correct > 0),
    )


def average(values: Sequence[float]) -> float:
    return round(mean(values), 4) if values else 0.0
