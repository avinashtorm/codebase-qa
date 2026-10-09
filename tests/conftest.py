import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def write_files(root: Path, files: dict[str, str | bytes]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="\n")


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


FIXTURE_FILES: dict[str, str | bytes] = {
    "app/main.py": "from app.auth import login\n\n\ndef create_app() -> str:\n    return login('admin')\n",
    "app/auth.py": (
        "class AuthService:\n"
        "    def login(self, user: str) -> str:\n"
        "        return f'token-{user}'\n\n\n"
        "def login(user: str) -> str:\n"
        "    return AuthService().login(user)\n"
    ),
    "web/index.ts": "export function greet(name: string): string {\n  return `hi ${name}`;\n}\n",
    "README.md": "# Fixture\n\nA tiny repo for tests.\n",
    "node_modules/lib/index.js": "module.exports = 1;\n",
    "dist/bundle.js": "console.log(1);\n",
    "package-lock.json": "{}\n",
    "static/app.min.js": "var a=1;\n",
    "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00binary",
    "notes.unknownext": "ignored\n",
}


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[[dict[str, str | bytes]], Path]:
    def factory(files: dict[str, str | bytes] | None = None) -> Path:
        repo = tmp_path / "origin"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        git(repo, "config", "core.autocrlf", "false")
        write_files(repo, FIXTURE_FILES if files is None else files)
        commit_all(repo, "initial")
        return repo

    return factory
