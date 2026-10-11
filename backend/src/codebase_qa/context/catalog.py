import re
from dataclasses import dataclass, field
from pathlib import Path

from codebase_qa.models import Chunk

SIGNATURE_NAME = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:def|function\*?|class|interface|type|func|const|let|var|enum|struct)\s+(?:\([^)]*\)\s*)?([A-Za-z_$][\w$]*)"
)
METHOD_NAME = re.compile(
    r"^(?:async\s+|static\s+|public\s+|private\s+|protected\s+|get\s+|set\s+)*([A-Za-z_$][\w$]*)\s*[(<]"
)
DEFINING_KINDS = ("Function", "Method", "Class", "Definition")


def header_fields(chunk: Chunk) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in chunk.header.split("\n"):
        if line.startswith("# ") and ": " in line:
            key, value = line[2:].split(": ", 1)
            fields[key] = value.strip()
    return fields


def defined_name(chunk: Chunk) -> str | None:
    fields = header_fields(chunk)
    for kind in DEFINING_KINDS:
        signature = fields.get(kind)
        if not signature:
            continue
        match = SIGNATURE_NAME.match(signature) or METHOD_NAME.match(signature)
        if match:
            return match.group(1)
    return None


@dataclass
class ChunkCatalog:
    by_path: dict[str, list[Chunk]] = field(default_factory=dict)
    definitions: dict[str, list[Chunk]] = field(default_factory=dict)

    @classmethod
    def build(cls, chunks: list[Chunk]) -> "ChunkCatalog":
        catalog = cls()
        for chunk in sorted(chunks, key=lambda c: (c.path, c.start_line, c.end_line)):
            catalog.by_path.setdefault(chunk.path, []).append(chunk)
            name = defined_name(chunk)
            if name:
                catalog.definitions.setdefault(name, []).append(chunk)
        return catalog


class LineReader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.cache: dict[str, list[str] | None] = {}

    def lines(self, path: str) -> list[str] | None:
        if path not in self.cache:
            self.cache[path] = self.read(path)
        return self.cache[path]

    def read(self, path: str) -> list[str] | None:
        file = (self.root / path).resolve()
        if not file.is_relative_to(self.root.resolve()) or not file.is_file():
            return None
        try:
            text = file.read_text(encoding="utf-8").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError):
            return None
        lines = text.split("\n")
        return lines[:-1] if lines and lines[-1] == "" else lines
