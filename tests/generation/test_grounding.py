from codebase_qa.generation.grounding import is_low_relevance, snippet_for, validate_citations
from codebase_qa.generation.refusal import FALLBACK_SUGGESTIONS, NOT_FOUND_LEAD, is_unknown, main_text
from codebase_qa.models import Chunk, Citation, GeneratedAnswer, RetrievedChunk
from codebase_qa.qa import QAPipeline


def item(path: str, start: int, end: int, scores: dict[str, float] | None = None) -> RetrievedChunk:
    content = "\n".join(f"line {n}" for n in range(start, end + 1))
    return RetrievedChunk(Chunk(f"{path}{start}", "r", path, "python", start, end, content), 0.5, scores or {})


CONTEXT = [item("app/auth.py", 10, 20), item("app/auth.py", 21, 30), item("app/db.py", 1, 5)]


def test_validate_citations_keeps_only_ranges_inside_given_context() -> None:
    citations = [
        Citation("app/auth.py", 12, 15),
        Citation("app/auth.py", 18, 25),
        Citation("app/auth.py", 5, 12),
        Citation("app/other.py", 1, 2),
        Citation("app/db.py", 4, 3),
        Citation("app/auth.py", 12, 15),
    ]
    valid, invalid = validate_citations(citations, CONTEXT)
    assert valid == [Citation("app/auth.py", 12, 15), Citation("app/auth.py", 18, 25)]
    assert invalid == 4


def test_snippet_uses_original_line_numbers_across_adjacent_chunks() -> None:
    assert snippet_for(Citation("app/auth.py", 20, 22), CONTEXT) == "line 20\nline 21\nline 22"


def test_low_relevance_uses_rerank_score_when_present_else_vector() -> None:
    thresholds = {"rerank": 0.0, "vector": 0.6}
    assert is_low_relevance([item("a.py", 1, 2, {"rerank": -3.0, "vector": 0.9})], thresholds)
    assert not is_low_relevance([item("a.py", 1, 2, {"rerank": 1.5})], thresholds)
    assert is_low_relevance([item("a.py", 1, 2, {"vector": 0.4})], thresholds)
    assert not is_low_relevance([item("a.py", 1, 2, {"bm25": 2.0})], thresholds)
    assert is_low_relevance([], thresholds)
    assert not is_low_relevance([item("a.py", 1, 2, {"vector": 0.1})], {})


class CountingGenerator:
    def __init__(self, citations: list[Citation]) -> None:
        self.citations = citations
        self.calls = 0

    def generate(self, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        self.calls += 1
        return GeneratedAnswer(answer="ok", citations=self.citations)


class ListRetriever:
    name = "list"

    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.timings: dict[str, float] = {}

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        return self.results[:k]


def test_pipeline_refuses_without_calling_llm_when_scores_are_low() -> None:
    generator = CountingGenerator([])
    retriever = ListRetriever([item("a.py", 1, 2, {"vector": 0.2}), item("b.py", 1, 2, {"vector": 0.1})])
    suggestions = ["Where is login?", "How are users stored?", "What does main do?", "Fourth?"]
    pipeline = QAPipeline(retriever, generator, refusal_thresholds={"vector": 0.5}, suggestions=suggestions)
    result = pipeline.ask("what is the weather?")
    assert result.answer.answer.startswith(NOT_FOUND_LEAD)
    assert "**Closest files I found:** `a.py`, `b.py`" in result.answer.answer
    assert "- Where is login?\n- How are users stored?\n- What does main do?" in result.answer.answer
    assert result.refused and result.suggestions == suggestions[:3]
    assert result.answer.used_llm is False
    assert generator.calls == 0


class UnknownGenerator:
    def generate(self, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        return GeneratedAnswer(answer="I don't know based on the indexed code; payments are not shown.", citations=[])


def test_llm_unknown_answer_becomes_helpful() -> None:
    result = QAPipeline(ListRetriever(CONTEXT), UnknownGenerator()).ask("How are payments refunded?")
    assert result.refused and result.answer.used_llm
    assert result.answer.answer.startswith("I don't know based on the indexed code")
    assert "`app/db.py`" in result.answer.answer and result.suggestions == list(FALLBACK_SUGGESTIONS)
    assert main_text(result.answer.answer).endswith("`app/db.py`")


def test_is_unknown_requires_no_citations() -> None:
    assert is_unknown(GeneratedAnswer("The context does not contain a refund handler.", []))
    assert not is_unknown(GeneratedAnswer("I don't know everything, but login is here.", [Citation("a.py", 1, 2)]))
    assert not is_unknown(GeneratedAnswer("Login hashes the password.", []))


def test_pipeline_drops_and_counts_invalid_citations() -> None:
    generator = CountingGenerator([Citation("app/db.py", 2, 3), Citation("app/db.py", 40, 41)])
    result = QAPipeline(ListRetriever(CONTEXT), generator).ask("db?")
    assert result.answer.citations == [Citation("app/db.py", 2, 3)]
    assert result.answer.invalid_citations == 1
