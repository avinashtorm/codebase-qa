from collections.abc import Callable
from pathlib import Path

from codebase_qa.chunking.treesitter.chunker import TreeSitterChunker
from codebase_qa.context.builder import ContextBuilder
from codebase_qa.context.calls import called_names, callee_chunks
from codebase_qa.context.catalog import ChunkCatalog, LineReader, defined_name
from codebase_qa.context.parent import parent_span
from codebase_qa.ingestion.walker import walk_repo
from codebase_qa.models import Chunk, RetrievedChunk
from tests.conftest import write_files
from tests.fakes import FakeLLM, fake_embedder, fake_generator, make_settings

RepoFactory = Callable[..., Path]

SERVICE = (
    "import os\n"
    "\n"
    "\n"
    "class Service:\n"
    "    name = 'svc'\n"
    "\n"
    "    def start(self) -> str:\n"
    "        return load_config()\n"
    "\n"
    "    def stop(self) -> None:\n"
    "        cleanup(self.name)\n"
    "\n"
    "\n"
    "def load_config() -> str:\n"
    "    return os.environ.get('CFG', '')\n"
    "\n"
    "\n"
    "def cleanup(name: str) -> None:\n"
    "    print(name)\n"
)
FILES: dict[str, str | bytes] = {
    "app/service.py": SERVICE,
    "app/settings.yml": "".join(f"key{n}: {n}\n" for n in range(1, 61)),
}


def catalog_for(root: Path) -> tuple[ChunkCatalog, list[Chunk]]:
    chunker = TreeSitterChunker()
    chunks = [chunk for source in walk_repo(root, "r") for chunk in chunker.chunk(source)]
    return ChunkCatalog.build(chunks), chunks


def find(chunks: list[Chunk], path: str, needle: str) -> Chunk:
    return next(chunk for chunk in chunks if chunk.path == path and needle in chunk.header + chunk.content)


def test_defined_names_come_from_headers(tmp_path: Path) -> None:
    write_files(tmp_path, FILES)
    catalog, chunks = catalog_for(tmp_path)
    assert {"Service", "start", "stop", "load_config", "cleanup"} <= set(catalog.definitions)
    assert defined_name(find(chunks, "app/service.py", "def load_config")) == "load_config"


def test_method_parent_is_its_class(tmp_path: Path) -> None:
    write_files(tmp_path, FILES)
    catalog, chunks = catalog_for(tmp_path)
    method = find(chunks, "app/service.py", "def stop")
    assert parent_span(method, catalog, 19, 100, 10) == (4, 11)
    assert parent_span(method, catalog, 19, 5, 10)[1] - parent_span(method, catalog, 19, 5, 10)[0] < 8


def test_window_chunks_grow_and_are_capped(tmp_path: Path) -> None:
    write_files(tmp_path, FILES)
    catalog, chunks = catalog_for(tmp_path)
    window = find(chunks, "app/settings.yml", "key50")
    start, end = parent_span(window, catalog, 60, 30, 10)
    assert end - start + 1 <= max(30, window.end_line - window.start_line + 1)
    assert start <= window.start_line and window.end_line <= end


def test_called_names_skip_builtins() -> None:
    chunk = Chunk("c", "r", "a.py", "python", 1, 2, "x = len(items)\nreturn load_config() + obj.cleanup(name)")
    assert called_names(chunk) == ["load_config", "cleanup"]


def test_callees_are_found_and_capped(tmp_path: Path) -> None:
    write_files(tmp_path, FILES)
    catalog, chunks = catalog_for(tmp_path)
    start = find(chunks, "app/service.py", "def start")
    stop = find(chunks, "app/service.py", "def stop")
    found = callee_chunks([start, stop], catalog, max_functions=4, max_lines=100)
    assert [defined_name(chunk) for chunk in found] == ["load_config", "cleanup"]
    assert len(callee_chunks([start, stop], catalog, max_functions=1, max_lines=100)) == 1
    assert callee_chunks([start, stop], catalog, max_functions=4, max_lines=1) == []


def test_builder_reads_real_lines_and_appends_callees(tmp_path: Path) -> None:
    write_files(tmp_path, FILES)
    catalog, chunks = catalog_for(tmp_path)
    stop = find(chunks, "app/service.py", "def stop")
    builder = ContextBuilder(catalog, LineReader(tmp_path), parent=True, calls=True)
    built = builder.build([RetrievedChunk(stop, 0.8, {"vector": 0.8})])
    assert (built[0].chunk.start_line, built[0].chunk.end_line) == (4, 11)
    assert built[0].chunk.content.split("\n")[0] == "class Service:" and built[0].scores["vector"] == 0.8
    assert [item.chunk.path for item in built[1:]] == ["app/service.py"]
    assert "def cleanup" in built[1].chunk.content and built[1].scores == {"callee": 1.0}


def test_builder_drops_chunks_inside_an_expanded_parent(tmp_path: Path) -> None:
    write_files(tmp_path, FILES)
    catalog, chunks = catalog_for(tmp_path)
    start, stop = find(chunks, "app/service.py", "def start"), find(chunks, "app/service.py", "def stop")
    builder = ContextBuilder(catalog, LineReader(tmp_path), parent=True, calls=False)
    built = builder.build([RetrievedChunk(start, 0.9), RetrievedChunk(stop, 0.8)])
    assert len(built) == 1


def test_line_reader_stays_inside_root(tmp_path: Path) -> None:
    write_files(tmp_path, {"inside.py": "a\nb\n"})
    reader = LineReader(tmp_path / "")
    assert reader.lines("inside.py") == ["a", "b"]
    assert reader.lines("../outside.py") is None


def test_pipeline_uses_call_context_and_keeps_citations_valid(tmp_path: Path, make_repo: RepoFactory) -> None:
    from codebase_qa.container import Container

    container = Container(
        make_settings(tmp_path / "data", call_context=True, parent_context=True),
        embedder_factory=fake_embedder,
        generator_factory=fake_generator,
        llm_factory=lambda _: FakeLLM(),
    )
    record = container.indexer.index(make_repo(FILES).as_uri())
    result = container.pipeline(record).ask("Where does Service stop and clean up?")
    paths = [(item.chunk.path, item.chunk.start_line) for item in result.context]
    assert ("app/service.py", 4) in paths
    assert result.answer.citations and result.answer.invalid_citations == 0
