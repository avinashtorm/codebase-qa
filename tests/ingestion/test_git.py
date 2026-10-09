from collections.abc import Callable
from pathlib import Path

import pytest

from codebase_qa.ingestion.git import GitError, clone_repo, diff_name_status, repo_id_from_url
from tests.conftest import commit_all, git, write_files

RepoFactory = Callable[..., Path]


def test_repo_id_from_github_url() -> None:
    assert repo_id_from_url("https://github.com/FastAPI/full-stack-fastapi-template") == (
        "fastapi__full-stack-fastapi-template"
    )
    assert repo_id_from_url("https://github.com/a/b.git") == "a__b"


def test_clone_records_sha_and_reuses_checkout(make_repo: RepoFactory, tmp_path: Path) -> None:
    origin = make_repo()
    expected_sha = git(origin, "rev-parse", "HEAD").strip()
    repos_dir = tmp_path / "repos"

    cloned = clone_repo(origin.as_uri(), repos_dir, repo_id="fixture")
    assert cloned.commit_sha == expected_sha
    assert (Path(cloned.local_path) / "app" / "auth.py").exists()

    write_files(origin, {"app/new.py": "x = 1\n"})
    commit_all(origin, "second")
    reused = clone_repo(origin.as_uri(), repos_dir, repo_id="fixture")
    assert reused.commit_sha == expected_sha
    assert reused.local_path == cloned.local_path


def test_clone_failure_raises_git_error(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        clone_repo((tmp_path / "missing").as_uri(), tmp_path / "repos", repo_id="missing")


def test_diff_handles_non_ascii_file_names(make_repo: RepoFactory) -> None:
    origin = make_repo({"a.py": "x = 1\n"})
    old = git(origin, "rev-parse", "HEAD").strip()
    write_files(origin, {"docs/café_notes.md": "# Café\n\nNotes “quoted”.\n"})
    new = commit_all(origin, "add non-ascii file")
    assert diff_name_status(origin, old, new) == [["A", "docs/café_notes.md"]]
