import stat
from pathlib import Path

from codebase_qa.fs import remove_tree


def test_remove_tree_deletes_read_only_files(tmp_path: Path) -> None:
    target = tmp_path / "repo" / ".git" / "objects"
    target.mkdir(parents=True)
    pack = target / "pack.idx"
    pack.write_text("x")
    pack.chmod(stat.S_IREAD)
    remove_tree(tmp_path / "repo")
    assert not (tmp_path / "repo").exists()
    remove_tree(tmp_path / "missing")
