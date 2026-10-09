import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any


def make_writable_and_retry(function: Callable[[str], Any], path: str, _: object) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, onerror=make_writable_and_retry)
