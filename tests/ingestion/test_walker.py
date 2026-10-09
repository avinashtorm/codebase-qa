from collections.abc import Callable
from pathlib import Path

from codebase_qa.ingestion.walker import content_hash, walk_repo
from tests.conftest import write_files

RepoFactory = Callable[..., Path]


def test_walk_repo_keeps_source_and_skips_noise(make_repo: RepoFactory) -> None:
    repo = make_repo()
    files = {source.path: source for source in walk_repo(repo, "fixture")}
    assert set(files) == {"app/main.py", "app/auth.py", "web/index.ts", "README.md"}
    auth = files["app/auth.py"]
    assert auth.repo_id == "fixture"
    assert auth.language == "python"
    assert auth.content_hash == content_hash(auth.content)
    assert files["web/index.ts"].language == "typescript"


def test_walk_repo_skips_oversized_and_minified(tmp_path: Path) -> None:
    write_files(
        tmp_path,
        {
            "big.py": "x = 1\n" * 1000,
            "packed.js": "var a=1;" * 2000,
            "ok.py": "y = 2\n",
            "venv/lib/site.py": "z = 3\n",
        },
    )
    paths = [source.path for source in walk_repo(tmp_path, "r", max_bytes=1000)]
    assert paths == ["ok.py"]


def test_walk_repo_normalises_crlf(tmp_path: Path) -> None:
    (tmp_path / "win.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    [source] = walk_repo(tmp_path, "r")
    assert source.content == "a = 1\nb = 2\n"
