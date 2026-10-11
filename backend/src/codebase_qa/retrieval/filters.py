from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from codebase_qa.ingestion.languages import detect_language


@dataclass(frozen=True)
class SearchFilter:
    folder: str = ""
    languages: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.folder.strip("/")) or bool(self.languages)

    def allows(self, path: str) -> bool:
        folder = self.folder.strip("/")
        if folder and not path.startswith(folder + "/"):
            return False
        return not self.languages or detect_language(path) in self.languages

    def allowed_paths(self, paths: Iterable[str]) -> list[str]:
        return sorted(path for path in paths if self.allows(path))


NO_FILTER = SearchFilter()


def folder_counts(paths: Iterable[str], depth: int = 2) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for path in paths:
        parts = path.split("/")[:-1]
        for end in range(1, min(depth, len(parts)) + 1):
            counts["/".join(parts[:end])] += 1
    return dict(sorted(counts.items()))


def language_counts(paths: Iterable[str]) -> dict[str, int]:
    counts = Counter(language for path in paths if (language := detect_language(path)) is not None)
    return dict(counts.most_common())
