import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from codebase_qa.chunking.ids import chunk_id
from codebase_qa.indexing.registry import FileRecord
from codebase_qa.models import OVERVIEW_PREFIX, Chunk
from codebase_qa.overview.selection import find_readme, select_files, select_folders
from codebase_qa.overview.summarizer import ItemKind, LLMSummarizer, SummaryItem
from codebase_qa.overview.tree import Folder, build_folders, folder_tree

OVERVIEW_LANGUAGE = "overview"
REPOSITORY_KEY = "."
README_CHARS = 2500
MAX_CHUNK_LINES = 60

Reader = Callable[[str], str | None]


@dataclass
class OverviewEntry:
    kind: str
    fingerprint: str
    summary: str
    source: str


@dataclass(frozen=True)
class OverviewBuild:
    entries: dict[str, OverviewEntry]
    chunks: list[Chunk]
    llm_calls: int
    summarized: int


@dataclass(frozen=True)
class Candidate:
    path: str
    kind: ItemKind
    fingerprint: str


def digest(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


def folder_listing(paths: list[str], folder: str, limit: int = 40) -> list[str]:
    node = build_folders(paths)
    if folder != REPOSITORY_KEY:
        for part in folder.split("/"):
            node = node.folders.get(part, Folder())
    names = [f"{name}/" for name in sorted(node.folders)] + node.files
    return names[:limit] + ([f"... {len(names) - limit} more"] if len(names) > limit else [])


def nearest_folder(path: str, folders: set[str]) -> str:
    parts = path.split("/")[:-1]
    for end in range(len(parts), 0, -1):
        candidate = "/".join(parts[:end])
        if candidate in folders:
            return candidate
    return REPOSITORY_KEY


def overview_chunk(repo_id: str, name: str, lines: list[str], start: int, title: str) -> Chunk:
    text = "\n".join(lines)
    path = OVERVIEW_PREFIX + name
    end = start + len(lines) - 1
    return Chunk(
        chunk_id=chunk_id(repo_id, path, start, end, text),
        repo_id=repo_id,
        path=path,
        language=OVERVIEW_LANGUAGE,
        start_line=start,
        end_line=end,
        content=text,
        header=f"# Overview: {title}",
        kind="overview",
    )


def split_chunks(repo_id: str, name: str, lines: list[str], title: str) -> list[Chunk]:
    return [
        overview_chunk(repo_id, name, lines[start : start + MAX_CHUNK_LINES], start + 1, title)
        for start in range(0, len(lines), MAX_CHUNK_LINES)
    ]


class OverviewBuilder:
    def __init__(
        self,
        summarizer: LLMSummarizer,
        max_files: int = 60,
        max_folders: int = 25,
        file_chars: int = 1200,
        readme_lines: int = 80,
    ) -> None:
        self.summarizer = summarizer
        self.max_files = max_files
        self.max_folders = max_folders
        self.file_chars = file_chars
        self.readme_lines = readme_lines

    def build(
        self,
        repo_id: str,
        files: Mapping[str, FileRecord],
        read: Reader,
        previous: Mapping[str, OverviewEntry],
    ) -> OverviewBuild:
        paths = sorted(files)
        readme = find_readme(paths)
        readme_text = (read(readme) or "") if readme else ""
        selected_files = select_files({path: len(files[path].chunk_ids) for path in paths}, self.max_files)
        selected_folders = select_folders(paths, self.max_folders)
        candidates = self.candidates(paths, readme_text, selected_folders, selected_files, files)
        reused = {
            c.path: previous[c.path]
            for c in candidates
            if c.path in previous
            and previous[c.path].fingerprint == c.fingerprint
            and previous[c.path].source == "llm"
        }
        pending = [c for c in candidates if c.path not in reused]
        items = [SummaryItem(c.path, c.kind, self.item_text(c, paths, readme_text, read)) for c in pending]
        result = self.summarizer.summarize(items)
        entries = dict(reused)
        for candidate in pending:
            entries[candidate.path] = OverviewEntry(
                kind=candidate.kind,
                fingerprint=candidate.fingerprint,
                summary=result.summaries[candidate.path],
                source=result.sources[candidate.path],
            )
        chunks = self.chunks(repo_id, paths, readme, readme_text, entries, selected_folders, selected_files)
        return OverviewBuild(entries=entries, chunks=chunks, llm_calls=result.llm_calls, summarized=len(items))

    def candidates(
        self,
        paths: list[str],
        readme_text: str,
        folders: list[str],
        selected: list[str],
        files: Mapping[str, FileRecord],
    ) -> list[Candidate]:
        top_level = ",".join(folder_listing(paths, REPOSITORY_KEY))
        repository = Candidate(REPOSITORY_KEY, "repository", digest(readme_text[:README_CHARS], top_level))
        folder_items = [
            Candidate(folder, "folder", digest(",".join(folder_listing(paths, folder))))
            for folder in sorted(folders, key=lambda folder: (folder.count("/"), folder))
        ]
        file_items = [Candidate(path, "file", files[path].content_hash) for path in selected]
        return [repository, *folder_items, *file_items]

    def item_text(self, candidate: Candidate, paths: list[str], readme_text: str, read: Reader) -> str:
        if candidate.kind == "repository":
            listing = "\n".join(folder_listing(paths, REPOSITORY_KEY))
            return f"{readme_text[:README_CHARS]}\n\nTop-level contents:\n{listing}"
        if candidate.kind == "folder":
            listing = folder_listing(paths, candidate.path)
            return f"{len(listing)} entries: " + ", ".join(listing)
        return (read(candidate.path) or "")[: self.file_chars]

    def chunks(
        self,
        repo_id: str,
        paths: list[str],
        readme: str | None,
        readme_text: str,
        entries: Mapping[str, OverviewEntry],
        folders: list[str],
        selected: list[str],
    ) -> list[Chunk]:
        summary = entries[REPOSITORY_KEY].summary
        top_level = ", ".join(folder_listing(paths, REPOSITORY_KEY))
        chunks = [
            overview_chunk(
                repo_id,
                "repository",
                [f"Repository {repo_id}", summary, f"Top-level contents: {top_level}"],
                1,
                "repository summary",
            )
        ]
        tree_lines = ["Repository structure (folders with file counts):", *folder_tree(paths).split("\n")]
        chunks.extend(split_chunks(repo_id, "structure", tree_lines, "repository structure"))
        if readme and readme_text.strip():
            chunks.append(self.readme_chunk(repo_id, readme, readme_text))
        folder_set = set(folders)
        grouped: dict[str, list[str]] = {}
        for path in selected:
            grouped.setdefault(nearest_folder(path, folder_set), []).append(path)
        for folder in [REPOSITORY_KEY, *folders]:
            members = grouped.get(folder, [])
            if folder == REPOSITORY_KEY and not members:
                continue
            title = "top-level files" if folder == REPOSITORY_KEY else f"folder {folder}/"
            lines = [] if folder == REPOSITORY_KEY else [f"Folder {folder}/: {entries[folder].summary}"]
            lines += [f"- {path}: {entries[path].summary}" for path in members]
            name = "folder/" + ("root" if folder == REPOSITORY_KEY else folder)
            chunks.extend(split_chunks(repo_id, name, lines, title))
        return chunks

    def readme_chunk(self, repo_id: str, readme: str, readme_text: str) -> Chunk:
        lines = readme_text.split("\n")[: self.readme_lines]
        text = "\n".join(lines)
        return Chunk(
            chunk_id=chunk_id(repo_id, readme, 1, len(lines), text),
            repo_id=repo_id,
            path=readme,
            language="markdown",
            start_line=1,
            end_line=len(lines),
            content=text,
            header="# Overview: README",
            kind="overview",
        )
