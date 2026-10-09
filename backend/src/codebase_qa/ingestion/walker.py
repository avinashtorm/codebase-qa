import hashlib
from collections.abc import Iterator
from pathlib import Path

from codebase_qa.ingestion.languages import detect_language
from codebase_qa.models import SourceFile

SKIPPED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "vendor",
        "venv",
        ".venv",
        "env",
        "build",
        "dist",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".next",
        "target",
        "coverage",
        "site-packages",
    }
)

LOCKFILES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "pipfile.lock",
        "uv.lock",
        "cargo.lock",
        "composer.lock",
        "gemfile.lock",
        "go.sum",
        "bun.lockb",
    }
)

MINIFIED_SUFFIXES: tuple[str, ...] = (".min.js", ".min.css", ".bundle.js", ".map")
MAX_FILE_BYTES = 500_000
MAX_AVERAGE_LINE_LENGTH = 300


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def is_skipped_path(relative_path: str) -> bool:
    parts = relative_path.split("/")
    if any(part in SKIPPED_DIRS for part in parts[:-1]):
        return True
    name = parts[-1].lower()
    return name in LOCKFILES or name.endswith(MINIFIED_SUFFIXES)


def looks_minified(content: str) -> bool:
    lines = content.splitlines() or [""]
    return len(content) > 2_000 and len(content) / len(lines) > MAX_AVERAGE_LINE_LENGTH


def read_text(path: Path, max_bytes: int) -> str | None:
    if path.stat().st_size > max_bytes:
        return None
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def iter_candidate_paths(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            yield path


def load_source_file(root: Path, relative_path: str, repo_id: str, max_bytes: int) -> SourceFile | None:
    if is_skipped_path(relative_path):
        return None
    language = detect_language(relative_path)
    if language is None:
        return None
    path = root / relative_path
    if not path.is_file() or path.is_symlink():
        return None
    content = read_text(path, max_bytes)
    if content is None or not content.strip() or looks_minified(content):
        return None
    content = content.replace("\r\n", "\n")
    return SourceFile(
        repo_id=repo_id,
        path=relative_path,
        language=language,
        content=content,
        content_hash=content_hash(content),
    )


def walk_repo(root: Path, repo_id: str, max_bytes: int = MAX_FILE_BYTES) -> list[SourceFile]:
    files: list[SourceFile] = []
    for path in iter_candidate_paths(root):
        relative_path = path.relative_to(root).as_posix()
        if relative_path.split("/")[0] == ".git":
            continue
        source = load_source_file(root, relative_path, repo_id, max_bytes)
        if source is not None:
            files.append(source)
    return files
