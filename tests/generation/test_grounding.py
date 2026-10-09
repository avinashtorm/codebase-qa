from codebase_qa.generation.grounding import is_low_relevance, snippet_for, validate_citations
from codebase_qa.models import Chunk, Citation, GeneratedAnswer, RetrievedChunk
from codebase_qa.qa import NOT_FOUND_ANSWER, QAPipeline


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
    retriever = ListRetriever([item("a.py", 1, 2, {"vector": 0.2})])
    pipeline = QAPipeline(retriever, generator, refusal_thresholds={"vector": 0.5})
    result = pipeline.ask("what is the weather?")
    assert result.answer.answer == NOT_FOUND_ANSWER
    assert result.answer.used_llm is False
    assert generator.calls == 0


def test_pipeline_drops_and_counts_invalid_citations() -> None:
    generator = CountingGenerator([Citation("app/db.py", 2, 3), Citation("app/db.py", 40, 41)])
    result = QAPipeline(ListRetriever(CONTEXT), generator).ask("db?")
    assert result.answer.citations == [Citation("app/db.py", 2, 3)]
    assert result.answer.invalid_citations == 1
