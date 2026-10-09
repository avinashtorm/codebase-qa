from pathlib import Path

from codebase_qa.models import Chunk, RetrievedChunk
from codebase_qa.retrieval.bm25 import BM25Index, BM25Retriever
from codebase_qa.retrieval.hybrid import HybridRetriever, reciprocal_rank_fusion
from codebase_qa.retrieval.tokenizer import code_tokenize, identifier_parts


def make_chunk(chunk_id: str, content: str, path: str = "a.py") -> Chunk:
    return Chunk(chunk_id, "repo", path, "python", 1, 2, content, f"# File: {path}")


def test_identifier_parts_split_camel_and_snake_case() -> None:
    assert identifier_parts("get_password_hash") == ["get", "password", "hash"]
    assert identifier_parts("createAccessToken") == ["create", "access", "token"]
    assert identifier_parts("HTTPServerError") == ["http", "server", "error"]
    assert identifier_parts("OAuth2PasswordBearer") == ["o", "auth", "2", "password", "bearer"]


def test_code_tokenize_keeps_full_identifier_and_drops_stopwords() -> None:
    tokens = code_tokenize("Where is get_password_hash used by createUser?")
    assert tokens == ["get_password_hash", "get", "password", "hash", "used", "createuser", "create", "user"]


def test_bm25_ranks_identifier_matches_and_round_trips(tmp_path: Path) -> None:
    chunks = [
        make_chunk("1", "def get_password_hash(password):\n    return hasher.hash(password)", "security.py"),
        make_chunk("2", "def read_items(session):\n    return session.exec(select(Item))", "items.py"),
        make_chunk("3", "class Settings:\n    SECRET_KEY: str", "config.py"),
    ]
    index = BM25Index.build(chunks)
    index.save(tmp_path / "idx")
    loaded = BM25Index.load(tmp_path / "idx")
    results = BM25Retriever(loaded).retrieve("how is the password hashed", 2)
    assert results[0].chunk.path == "security.py"
    assert results[0].scores["bm25"] > 0
    assert BM25Retriever(loaded).retrieve("completely unknown words zzz", 5) == []


def test_empty_bm25_index(tmp_path: Path) -> None:
    index = BM25Index.build([])
    index.save(tmp_path / "empty")
    assert BM25Index.load(tmp_path / "empty").search("anything", 3) == []


def ranked(*ids: str) -> list[RetrievedChunk]:
    return [RetrievedChunk(make_chunk(i, i), 1.0 / n) for n, i in enumerate(ids, start=1)]


def test_reciprocal_rank_fusion_rewards_agreement() -> None:
    fused = reciprocal_rank_fusion({"vector": ranked("a", "b", "c"), "bm25": ranked("c", "b", "d")}, k=60)
    assert [item.chunk.chunk_id for item in fused] == ["c", "b", "a", "d"]
    top = fused[0]
    assert top.score == 1 / 63 + 1 / 61
    assert top.scores["vector_rank"] == 3.0 and top.scores["bm25_rank"] == 1.0


class StaticRetriever:
    def __init__(self, name: str, results: list[RetrievedChunk]) -> None:
        self.name = name
        self.results = results
        self.requested: list[int] = []

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        self.requested.append(k)
        return self.results[:k]


def test_hybrid_requests_candidates_from_both_and_truncates() -> None:
    vector = StaticRetriever("vector", ranked("a", "b"))
    keyword = StaticRetriever("bm25", ranked("b", "c"))
    results = HybridRetriever(vector, keyword, candidates=50).retrieve("q", 2)
    assert [item.chunk.chunk_id for item in results] == ["b", "a"]
    assert vector.requested == [50] and keyword.requested == [50]
