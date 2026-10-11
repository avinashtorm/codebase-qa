from codebase_qa.context.catalog import ChunkCatalog, header_fields
from codebase_qa.models import Chunk

Span = tuple[int, int]


def span_of(chunks: list[Chunk]) -> Span:
    return min(chunk.start_line for chunk in chunks), max(chunk.end_line for chunk in chunks)


def contiguous(chunks: list[Chunk], chunk: Chunk, gap: int = 2) -> list[Chunk]:
    ordered = sorted(chunks, key=lambda c: c.start_line)
    group = [chunk]
    start, end = chunk.start_line, chunk.end_line
    changed = True
    while changed:
        changed = False
        for other in ordered:
            if other in group:
                continue
            if other.start_line <= end + gap and other.end_line >= start - gap:
                group.append(other)
                start, end = min(start, other.start_line), max(end, other.end_line)
                changed = True
    return group


def family(chunk: Chunk, siblings: list[Chunk]) -> list[Chunk]:
    owner = class_owner(chunk) if "Method" in header_fields(chunk) else None
    if owner:
        return [other for other in siblings if class_owner(other) == owner] or [chunk]
    same_header = [other for other in siblings if other.header == chunk.header]
    return contiguous(same_header, chunk) if same_header else [chunk]


def class_owner(chunk: Chunk) -> str | None:
    fields = header_fields(chunk)
    if "Method" in fields:
        return fields.get("Class")
    signature = fields.get("Class", "")
    if signature.startswith("class "):
        return signature[len("class ") :].split("(")[0].split(":")[0].split("<")[0].split(" ")[0].strip()
    return None


def clamp(span: Span, center: Span, max_lines: int, file_length: int) -> Span:
    start, end = max(1, span[0]), min(file_length, span[1])
    if end - start + 1 <= max_lines:
        return start, end
    if center[1] - center[0] + 1 >= max_lines:
        return center
    middle = (center[0] + center[1]) // 2
    start = max(1, min(middle - max_lines // 2, file_length - max_lines + 1))
    start = min(max(start, center[1] - max_lines + 1), center[0])
    return start, min(file_length, start + max_lines - 1)


def parent_span(chunk: Chunk, catalog: ChunkCatalog, file_length: int, max_lines: int, window: int) -> Span:
    fields = header_fields(chunk)
    siblings = catalog.by_path.get(chunk.path, [])
    if "Definition" in fields or "# Top-level code" in chunk.header:
        span = (chunk.start_line - window, chunk.end_line + window)
    else:
        span = span_of(family(chunk, siblings))
    own = (chunk.start_line, chunk.end_line)
    start, end = clamp(span, own, max_lines, file_length)
    return min(start, own[0]), max(end, own[1])
