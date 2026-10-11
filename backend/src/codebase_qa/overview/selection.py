import math
import re
from collections import Counter
from pathlib import PurePosixPath

from codebase_qa.overview.tree import ancestors

TEST_DIRS = frozenset({"test", "tests", "__tests__", "spec", "specs", "e2e", "fixtures", "__mocks__", "testdata"})
TEST_FILE = re.compile(r"(^test_.*|.*_test\.\w+$|.*\.(test|spec)\.\w+$|^conftest\.py$)")
GENERATED = re.compile(r"(\.gen\.|generated|/migrations?/|/versions/|\.d\.ts$)")
ENTRYPOINTS = frozenset(
    {
        "main.py",
        "app.py",
        "server.py",
        "manage.py",
        "wsgi.py",
        "asgi.py",
        "index.js",
        "index.ts",
        "server.js",
        "server.ts",
        "app.js",
        "app.ts",
        "main.ts",
        "main.tsx",
        "app.tsx",
        "main.go",
        "router.py",
        "routes.py",
        "models.py",
        "config.py",
        "settings.py",
    }
)
MANIFESTS = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "docker-compose.yml",
        "compose.yml",
        "dockerfile",
        "go.mod",
        "cargo.toml",
        "pom.xml",
        "build.gradle",
        "makefile",
    }
)
CODE_LANGUAGES = frozenset(
    {"python", "javascript", "typescript", "tsx", "go", "java", "kotlin", "rust", "ruby", "php", "c", "cpp", "csharp"}
)
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".java": "java",
}


def is_test_path(path: str) -> bool:
    parts = path.lower().split("/")
    return any(part in TEST_DIRS for part in parts[:-1]) or bool(TEST_FILE.match(parts[-1]))


def is_generated_path(path: str) -> bool:
    return bool(GENERATED.search("/" + path.lower()))


def is_overview_candidate(path: str) -> bool:
    return not is_test_path(path) and not is_generated_path(path)


def file_score(path: str, size: int) -> float:
    pure = PurePosixPath(path.lower())
    depth = len(pure.parts) - 1
    score = math.log1p(size)
    if pure.name in ENTRYPOINTS:
        score += 2.0
    if pure.name in MANIFESTS:
        score += 1.5
    if LANGUAGE_BY_SUFFIX.get(pure.suffix) in CODE_LANGUAGES:
        score += 1.0
    return score - 0.25 * depth


def select_files(sizes: dict[str, int], limit: int) -> list[str]:
    candidates = [path for path in sizes if is_overview_candidate(path) and not is_readme(path)]
    ranked = sorted(candidates, key=lambda path: (-file_score(path, sizes[path]), path))
    return sorted(ranked[:limit])


def select_folders(paths: list[str], limit: int, max_depth: int = 4) -> list[str]:
    counts: Counter[str] = Counter()
    for path in paths:
        if not is_overview_candidate(path):
            continue
        for folder in ancestors(path):
            if folder.count("/") < max_depth:
                counts[folder] += 1
    ranked = sorted(counts, key=lambda folder: (is_hidden(folder), folder.count("/"), -counts[folder], folder))
    return sorted(ranked[:limit])


def is_hidden(path: str) -> bool:
    return any(part.startswith(".") and part != ".github" for part in path.split("/"))


def is_readme(path: str) -> bool:
    return PurePosixPath(path).name.lower() in {"readme.md", "readme.rst", "readme.txt", "readme"}


def find_readme(paths: list[str]) -> str | None:
    root = sorted((path for path in paths if "/" not in path and is_readme(path)), key=len)
    return root[0] if root else None
