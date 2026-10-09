import re

from codebase_qa.models import Citation

CITATION_PATTERN = re.compile(r"(?P<path>[\w.\-/\[\]@+$]+):(?P<start>\d+)(?:\s*[-–]\s*(?P<end>\d+))?")


def extract_citations(text: str) -> list[Citation]:
    seen: set[tuple[str, int, int]] = set()
    citations: list[Citation] = []
    for match in CITATION_PATTERN.finditer(text):
        path = match["path"].strip("`'\"[],.")
        if not re.search(r"[A-Za-z]", path):
            continue
        start = int(match["start"])
        end = int(match["end"] or start)
        key = (path, min(start, end), max(start, end))
        if key not in seen:
            seen.add(key)
            citations.append(Citation(path=key[0], start_line=key[1], end_line=key[2]))
    return citations
