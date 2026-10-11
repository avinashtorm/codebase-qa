from codebase_qa.models import Chunk, RetrievedChunk
from codebase_qa.retrieval.expansion import ExpandingRetriever, QueryExpander, fuse
from tests.fakes import FakeLLM


def item(name: str, vector: float) -> RetrievedChunk:
    return RetrievedChunk(Chunk(name, "r", f"{name}.py", "python", 1, 2, name), vector, {"vector": vector})


class TableRetriever:
    name = "vector"

    def __init__(self, table: dict[str, list[RetrievedChunk]]) -> None:
        self.table = table
        self.timings: dict[str, float] = {}
        self.queries: list[str] = []

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        self.queries.append(query)
        self.timings = {"vector_search": 1.0}
        return self.table.get(query, [])[:k]


def expander(queries: list[str] | str) -> QueryExpander:
    payload = queries if isinstance(queries, str) else {"queries": queries}
    return QueryExpander(FakeLLM({"ExpansionSchema": lambda _: payload}))


def test_expander_cleans_and_caps_variants() -> None:
    assert expander(["a", " a ", "q", "b", "c", "d"]).expand("q") == ["a", "b", "c"]
    assert expander("not json").expand("q") == []


def test_fuse_keeps_best_vector_score() -> None:
    fused = fuse({"q0": [item("a", 0.6), item("b", 0.5)], "q1": [item("b", 0.9)]}, 60)
    assert fused[0].chunk.chunk_id == "b" and fused[0].scores["vector"] == 0.9


def test_expanding_retriever_fuses_variants() -> None:
    table = {"q": [item("a", 0.7), item("b", 0.6)], "x": [item("b", 0.8)], "y": [item("b", 0.8)], "z": [item("c", 0.5)]}
    base = TableRetriever(table)
    retriever = ExpandingRetriever(base, expander(["x", "y", "z"]))
    assert [entry.chunk.chunk_id for entry in retriever.retrieve("q", 3)] == ["b", "a", "c"]
    assert base.queries == ["q", "x", "y", "z"] and retriever.timings["vector_search"] == 4.0


def test_original_weight_favours_the_original_query() -> None:
    table = {"q": [item("z", 0.7)], "x": [item("b", 0.8)]}
    equal = ExpandingRetriever(TableRetriever(table), expander(["x"]))
    weighted = ExpandingRetriever(TableRetriever(table), expander(["x"]), original_weight=4)
    assert [entry.chunk.chunk_id for entry in equal.retrieve("q", 2)] == ["b", "z"]
    assert [entry.chunk.chunk_id for entry in weighted.retrieve("q", 2)] == ["z", "b"]


def test_confident_results_skip_expansion() -> None:
    llm_expander = expander(["x"])
    retriever = ExpandingRetriever(TableRetriever({"q": [item("a", 0.9)]}), llm_expander, skip_above=0.8)
    assert [entry.chunk.chunk_id for entry in retriever.retrieve("q", 1)] == ["a"]
    assert retriever.queries == ["q"] and llm_expander.llm.calls == []
