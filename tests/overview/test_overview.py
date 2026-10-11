from collections.abc import Callable
from pathlib import Path

from codebase_qa.container import Container
from codebase_qa.indexing.registry import FileRecord
from codebase_qa.models import is_overview_path
from codebase_qa.overview.builder import OverviewBuilder
from codebase_qa.overview.selection import is_test_path, select_files, select_folders
from codebase_qa.overview.summarizer import LLMSummarizer, SummaryItem, heuristic_summary
from codebase_qa.overview.tree import folder_tree
from tests.conftest import commit_all, git, write_files
from tests.fakes import FakeLLM, fake_embedder, fake_generator, make_settings

RepoFactory = Callable[..., Path]

FILES: dict[str, str | bytes] = {
    "README.md": "# Shop\n\nA small shop backend with an API and a web client.\n",
    "app/main.py": "from app.api import router\n\n\ndef create_app():\n    return router\n",
    "app/api/routes.py": "def list_items():\n    return []\n\n\ndef create_item(name):\n    return name\n",
    "app/models.py": "class Item:\n    name: str\n",
    "app/tests/test_routes.py": "def test_list():\n    assert True\n",
    "web/src/client.gen.ts": "export function generated() {}\n",
    "web/src/App.tsx": "export function App() {\n  return null;\n}\n",
}


def build_container(tmp_path: Path, llm: FakeLLM, **overrides: object) -> Container:
    return Container(
        make_settings(tmp_path / "data", **overrides),
        embedder_factory=fake_embedder,
        generator_factory=fake_generator,
        llm_factory=lambda _: llm,
    )


def test_folder_tree_shows_counts_and_collapses_deep_folders() -> None:
    tree = folder_tree(["a/b/c/d/e.py", "a/x.py", "top.md"], max_depth=2)
    assert tree.splitlines() == ["a/ (2 files)", "  b/ (1 files)", "  x.py", "top.md"]


def test_selection_skips_tests_and_generated_code_and_prefers_entrypoints() -> None:
    sizes = {"app/main.py": 1, "app/util.py": 1, "app/tests/test_x.py": 9, "web/client.gen.ts": 9, "README.md": 3}
    assert is_test_path("app/tests/test_x.py") and is_test_path("src/a.spec.ts")
    assert select_files(sizes, 1) == ["app/main.py"]
    assert select_folders(list(sizes), 5) == ["app"]


def test_heuristic_summary_lists_definitions() -> None:
    item = SummaryItem("a.py", "file", "def alpha():\n    pass\nclass Beta:\n    pass\n")
    assert heuristic_summary(item) == "Defines alpha, Beta."


def test_summarizer_respects_call_cap_and_falls_back() -> None:
    llm = FakeLLM()
    items = [SummaryItem(f"f{n}.py", "file", "def f(): pass") for n in range(5)]
    result = LLMSummarizer(llm, batch_size=2, max_calls=1).summarize(items)
    assert result.llm_calls == 1 and len(llm.calls) == 1
    assert [result.sources[f"f{n}.py"] for n in range(5)] == ["llm", "llm", "heuristic", "heuristic", "heuristic"]


def test_builder_creates_tagged_overview_chunks() -> None:
    llm = FakeLLM()
    files = {path: FileRecord(content_hash=path, chunk_ids=["x"]) for path in FILES}
    contents = {path: value for path, value in FILES.items() if isinstance(value, str)}
    build = OverviewBuilder(LLMSummarizer(llm)).build("shop", files, contents.get, {})
    paths = [chunk.path for chunk in build.chunks]
    assert all(chunk.kind == "overview" for chunk in build.chunks)
    assert paths[:3] == ["@overview/repository", "@overview/structure", "README.md"]
    assert "@overview/folder/app/api" in paths
    assert "app/tests/test_routes.py" not in build.entries
    repository = build.chunks[0].content
    assert "Summary of ." in repository and "Top-level contents: app/, web/, README.md" in repository
    api = next(chunk for chunk in build.chunks if chunk.path == "@overview/folder/app/api")
    assert "- app/api/routes.py: Summary of app/api/routes.py" in api.content
    assert build.llm_calls == 1


def test_index_stores_searchable_overview(tmp_path: Path, make_repo: RepoFactory) -> None:
    container = build_container(tmp_path, FakeLLM())
    record = container.indexer.index(make_repo(FILES).as_uri())
    overview = container.overview_store.load(record.collection)
    assert overview is not None and record.overview_count == len(overview.chunks)
    results = overview.search(container.embedder.embed_query("repository structure folders"), 3)
    assert results and all(is_overview_path(item.chunk.path) or item.chunk.path == "README.md" for item in results)
    code_paths = {chunk.path for chunk in container.store.collection(record.collection).all_chunks()}
    assert not any(is_overview_path(path) for path in code_paths)


def test_reindex_resummarizes_only_changed_items(tmp_path: Path, make_repo: RepoFactory) -> None:
    llm = FakeLLM()
    container = build_container(tmp_path, llm)
    origin = make_repo(FILES)
    record = container.indexer.index(origin.as_uri())
    llm.calls.clear()
    record, _ = container.indexer.reindex(record)
    assert llm.calls == []

    write_files(origin, {"app/api/routes.py": "def list_items():\n    return [1]\n"})
    (origin / "app" / "models.py").unlink()
    commit_all(origin, "change")
    record, report = container.indexer.reindex(record)
    prompts = llm.calls_for("SummariesSchema")
    assert len(prompts) == 1
    assert "### file: app/api/routes.py" in prompts[0] and "### folder: app\n" in prompts[0]
    assert "### file: app/main.py" not in prompts[0] and "### repository" not in prompts[0]
    overview = container.overview_store.load(record.collection)
    assert overview is not None
    assert "app/models.py" not in overview.entries
    assert "overview" in report.stage_ms


def test_janitor_deletes_overview(tmp_path: Path, make_repo: RepoFactory) -> None:
    container = build_container(tmp_path, FakeLLM())
    record = container.indexer.index(make_repo(FILES).as_uri())
    assert container.overview_store.path(record.collection).exists()
    container.janitor.delete(record.repo_id)
    assert not container.overview_store.path(record.collection).exists()


def test_overview_can_be_disabled(tmp_path: Path, make_repo: RepoFactory) -> None:
    llm = FakeLLM()
    container = build_container(tmp_path, llm, overview=False)
    record = container.indexer.index(make_repo(FILES).as_uri())
    assert record.overview_count == 0 and llm.calls == []
    assert git(Path(record.local_path), "rev-parse", "HEAD").strip() == record.commit_sha
