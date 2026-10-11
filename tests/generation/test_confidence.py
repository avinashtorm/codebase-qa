from codebase_qa.generation.confidence import ConfidencePolicy, assess, cited_rank
from codebase_qa.generation.selfcheck import SKIPPED, SelfCheck
from codebase_qa.models import Chunk, Citation, GeneratedAnswer, RetrievedChunk

CLEAN = SelfCheck(ran=True, supported=3)


def item(path: str, start: int, vector: float | None = 0.8, **extra: float) -> RetrievedChunk:
    scores = ({"vector": vector} if vector is not None else {}) | extra
    return RetrievedChunk(Chunk(path, "r", path, "python", start, start + 9, "x"), vector or 0.0, scores)


CONTEXT = [
    item("a.py", 1),
    item("b.py", 1, 0.7),
    item("c.py", 1, 0.6),
    item("d.py", 1, 0.5),
    item("e.py", 1, None, callee=1),
]


def answer(*paths: str, invalid: int = 0) -> GeneratedAnswer:
    return GeneratedAnswer("text", [Citation(path, 2, 3) for path in paths], invalid_citations=invalid)


def test_high_when_top_ranked_citation_and_clean_self_check() -> None:
    result = assess(answer("a.py"), CONTEXT, False, CLEAN)
    assert result.level == "high"


def test_low_for_refusals_missing_citations_and_weak_matches() -> None:
    assert assess(answer("a.py"), CONTEXT, True, CLEAN).level == "low"
    assert assess(answer(), CONTEXT, False, CLEAN).level == "low"
    assert assess(answer("a.py"), CONTEXT, False, SelfCheck(True, 0, ["x", "y"], "warn")).level == "low"
    weak = [item("a.py", 1, 0.61)]
    assert assess(answer("a.py"), weak, False, CLEAN, ConfidencePolicy(low_score=0.63)).level == "low"


def test_medium_reasons() -> None:
    cases = {
        "not among the top": assess(answer("d.py"), CONTEXT, False, CLEAN),
        "dropped": assess(answer("a.py", invalid=1), CONTEXT, False, CLEAN),
        "not self-checked": assess(answer("a.py"), CONTEXT, False, SKIPPED),
        "removed 1 unsupported": assess(answer("a.py"), CONTEXT, False, SelfCheck(True, 2, ["x"], "remove")),
        "moderate search match": assess(answer("a.py"), [item("a.py", 1, 0.66)], False, CLEAN),
    }
    for phrase, result in cases.items():
        assert result.level == "medium" and any(phrase in reason for reason in result.reasons), phrase


def test_cited_rank_ignores_callees() -> None:
    assert cited_rank([Citation("b.py", 2, 3)], CONTEXT) == 2
    assert cited_rank([Citation("e.py", 2, 3)], CONTEXT) is None
