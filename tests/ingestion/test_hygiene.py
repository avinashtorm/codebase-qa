from pathlib import Path

import pytest

from codebase_qa.ingestion.hygiene import NO_HYGIENE, HygieneRules
from codebase_qa.ingestion.walker import walk_repo
from codebase_qa.models import Chunk, RetrievedChunk
from codebase_qa.retrieval.weighting import DownweightingRetriever, reweight
from tests.conftest import write_files
from tests.fakes import make_settings

RULES = HygieneRules()


@pytest.mark.parametrize(
    "path",
    [
        "yarn.lock",
        "web/app.js.map",
        "src/__snapshots__/App.test.tsx.snap",
        "tests/fixtures/users.json",
        "app/data/cities.json",
        "src/locales/en.json",
        "pkg/testdata/input.go",
    ],
)
def test_skipped_paths(path: str) -> None:
    assert RULES.skips(path, 100)


@pytest.mark.parametrize("path", ["package.json", "tsconfig.base.json", "app/config.json", "src/main.py"])
def test_kept_paths(path: str) -> None:
    assert not RULES.skips(path, 100)


def test_large_json_data_is_skipped_but_manifests_are_kept() -> None:
    assert RULES.skips("app/catalog.json", 60 * 1024)
    assert not RULES.skips("package.json", 600 * 1024)


def test_weights_for_generated_code_and_optional_tests() -> None:
    assert RULES.weight("frontend/src/client/sdk.gen.ts") == 0.9
    assert RULES.weight("api/user_pb2.py") == 0.9
    assert RULES.weight("backend/app/main.py") == 1.0
    assert RULES.weight("backend/tests/test_main.py") == 1.0
    assert HygieneRules(downweight_tests=True).weight("backend/tests/test_main.py") == 0.9
    assert NO_HYGIENE.weight("a.gen.ts") == 1.0 and not NO_HYGIENE.skips("yarn.lock", 1)


def test_walker_applies_skip_rules(tmp_path: Path) -> None:
    write_files(tmp_path, {"app/main.py": "x = 1\n", "app/data/rows.json": "[1]\n", "app/settings.json": "{}\n"})
    assert sorted(source.path for source in walk_repo(tmp_path, "r")) == ["app/main.py", "app/settings.json"]
    assert len(walk_repo(tmp_path, "r", rules=NO_HYGIENE)) == 3


def item(path: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(Chunk(path, "r", path, "ts", 1, 2, "x"), score, {"vector": score})


class ListRetriever:
    name = "vector"

    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.timings: dict[str, float] = {"vector_search": 1.0}
        self.requested = 0

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        self.requested = k
        return self.results[:k]


def test_reweight_moves_generated_code_down_and_keeps_raw_scores() -> None:
    ranked = reweight([item("client/sdk.gen.ts", 0.80), item("app/items.ts", 0.75)], RULES)
    assert [entry.chunk.path for entry in ranked] == ["app/items.ts", "client/sdk.gen.ts"]
    assert ranked[1].scores == {"vector": 0.80, "weight": 0.9}
    assert abs(ranked[1].score - 0.72) < 1e-9


def test_downweighting_retriever_fetches_extra_candidates() -> None:
    base = ListRetriever([item("a.gen.ts", 0.9), item("b.ts", 0.85), item("c.ts", 0.5)])
    retriever = DownweightingRetriever(base, RULES, candidates=30)
    assert [entry.chunk.path for entry in retriever.retrieve("q", 2)] == ["b.ts", "a.gen.ts"]
    assert base.requested == 30 and "downweight" in retriever.timings and "vector_search" in retriever.timings


def test_settings_extend_rules(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, hygiene_extra_skip=["*/vendor_data/*"], downweight_factor=0.8)
    rules = settings.hygiene_rules
    assert rules.skips("x/vendor_data/a.py", 1) and rules.weight("a.gen.ts") == 0.8
