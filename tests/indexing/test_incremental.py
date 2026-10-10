from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from codebase_qa.api.app import create_app
from codebase_qa.container import Container
from codebase_qa.indexing.changes import parse_name_status
from codebase_qa.indexing.registry import RepoRecord
from codebase_qa.retrieval.bm25 import BM25Index
from tests.conftest import commit_all, git, write_files
from tests.fakes import fake_embedder, fake_generator, make_settings, wait_for_job

RepoFactory = Callable[..., Path]


def make_container(data_dir: Path) -> Container:
    return Container(make_settings(data_dir), embedder_factory=fake_embedder, generator_factory=fake_generator)


def snapshot(container: Container, record: RepoRecord) -> tuple[list[tuple], list[str], dict[str, tuple]]:
    chunks = container.store.collection(record.collection).all_chunks()
    rows = sorted((c.chunk_id, c.path, c.start_line, c.end_line, c.content, c.header) for c in chunks)
    bm25 = BM25Index.load(container.indexer.bm25_path(record.collection))
    files = {path: (entry.content_hash, sorted(entry.chunk_ids)) for path, entry in record.files.items()}
    return rows, sorted(c.chunk_id for c in bm25.chunks), files


def change_origin(origin: Path) -> None:
    write_files(
        origin,
        {
            "app/auth.py": "class AuthService:\n    def login(self, user: str) -> str:\n        return f'jwt-{user}'\n",
            "app/new.py": "def added() -> int:\n    return 42\n",
            "assets/blob.bin": b"\x00\x01binary",
        },
    )
    (origin / "web" / "index.ts").unlink()
    git(origin, "mv", "app/main.py", "app/entry.py")
    commit_all(origin, "change files")


def test_parse_name_status_handles_all_change_kinds() -> None:
    rows = [["A", "a.py"], ["M", "m.py"], ["D", "d.py"], ["R097", "old.py", "new.py"], ["T", "t.py"]]
    changes = parse_name_status(rows)
    assert (changes.added, changes.modified, changes.deleted) == (["a.py"], ["m.py", "t.py"], ["d.py"])
    assert changes.renamed == [("old.py", "new.py")]
    assert changes.removed_paths == ["a.py", "d.py", "m.py", "old.py", "t.py"]
    assert changes.changed_paths == ["a.py", "m.py", "new.py", "t.py"]


def test_incremental_reindex_matches_full_rebuild(tmp_path: Path, make_repo: RepoFactory) -> None:
    origin = make_repo()
    incremental = make_container(tmp_path / "incremental")
    record = incremental.indexer.index(origin.as_uri())

    change_origin(origin)
    updated, report = incremental.indexer.reindex(record)

    assert report.method == "git-diff"
    assert (report.files_added, report.files_modified, report.files_deleted, report.files_renamed) == (2, 1, 1, 1)
    assert report.chunks_removed > 0 and report.chunks_added > 0
    assert updated.commit_sha == git(origin, "rev-parse", "HEAD").strip()

    full = make_container(tmp_path / "full")
    rebuilt = full.indexer.index(origin.as_uri())
    assert snapshot(incremental, updated) == snapshot(full, rebuilt)
    assert incremental.repo_record(record.repo_id) == updated


def test_reindex_without_new_commits_changes_nothing(tmp_path: Path, make_repo: RepoFactory) -> None:
    container = make_container(tmp_path / "data")
    record = container.indexer.index(make_repo().as_uri())
    before = snapshot(container, record)
    updated, report = container.indexer.reindex(record)
    assert report.method == "unchanged"
    assert report.files_changed == 0 and report.chunks_added == 0 and report.chunks_removed == 0
    assert snapshot(container, updated) == before


def test_hash_fallback_when_old_commit_is_unknown(tmp_path: Path, make_repo: RepoFactory) -> None:
    origin = make_repo()
    container = make_container(tmp_path / "incremental")
    record = container.indexer.index(origin.as_uri())
    change_origin(origin)

    unknown = replace(record, commit_sha="0" * 40)
    updated, report = container.indexer.reindex(unknown)

    assert report.method == "hash"
    assert report.files_deleted == 2 and report.files_added == 2 and report.files_modified == 1
    full = make_container(tmp_path / "full")
    assert snapshot(container, updated) == snapshot(full, full.indexer.index(origin.as_uri()))


def test_reindex_endpoint_runs_as_job_and_reports_changes(tmp_path: Path, make_repo: RepoFactory) -> None:
    origin = make_repo()
    container = make_container(tmp_path / "data")
    with TestClient(create_app(container), headers={"X-Visitor-Id": "a" * 32}) as client:
        indexed = client.post("/repos", json={"url": origin.as_uri()}).json()
        wait_for_job(client, indexed["job_id"])
        change_origin(origin)
        response = client.post("/repos/origin/reindex")
        assert response.status_code == 202
        job = wait_for_job(client, response.json()["job_id"])
        assert client.post("/repos/missing/reindex").status_code == 404
    assert job["kind"] == "reindex" and job["status"] == "succeeded"
    report = job["result"]
    assert report["files_changed"] == 5
    assert report["method"] == "git-diff"
    assert report["seconds"] >= 0
    assert {"pull", "detect_changes", "delete_chunks", "chunk_embed_add", "bm25_rebuild"} <= set(report["stage_ms"])
