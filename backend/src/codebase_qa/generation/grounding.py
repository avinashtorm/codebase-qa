from codebase_qa.models import Citation, RetrievedChunk

Interval = tuple[int, int]


def context_intervals(context: list[RetrievedChunk]) -> dict[str, list[Interval]]:
    spans: dict[str, list[Interval]] = {}
    for item in context:
        spans.setdefault(item.chunk.path, []).append((item.chunk.start_line, item.chunk.end_line))
    merged: dict[str, list[Interval]] = {}
    for path, intervals in spans.items():
        result: list[Interval] = []
        for start, end in sorted(intervals):
            if result and start <= result[-1][1] + 1:
                result[-1] = (result[-1][0], max(result[-1][1], end))
            else:
                result.append((start, end))
        merged[path] = result
    return merged


def is_grounded(citation: Citation, intervals: dict[str, list[Interval]]) -> bool:
    if citation.start_line < 1 or citation.end_line < citation.start_line:
        return False
    return any(
        start <= citation.start_line and citation.end_line <= end for start, end in intervals.get(citation.path, [])
    )


def validate_citations(citations: list[Citation], context: list[RetrievedChunk]) -> tuple[list[Citation], int]:
    intervals = context_intervals(context)
    valid: list[Citation] = []
    for citation in citations:
        if is_grounded(citation, intervals) and citation not in valid:
            valid.append(citation)
    return valid, len(citations) - len(valid)


def relevance(item: RetrievedChunk) -> float | None:
    for key in ("rerank", "vector"):
        if key in item.scores:
            return item.scores[key]
    return None


def is_low_relevance(context: list[RetrievedChunk], threshold_by_signal: dict[str, float]) -> bool:
    if not context:
        return True
    signal = "rerank" if "rerank" in context[0].scores else "vector"
    threshold = threshold_by_signal.get(signal)
    values = [value for value in (relevance(item) for item in context) if value is not None]
    if threshold is None or not values:
        return False
    return max(values) < threshold


def snippet_for(citation: Citation, context: list[RetrievedChunk]) -> str:
    lines: dict[int, str] = {}
    for item in context:
        if item.chunk.path != citation.path:
            continue
        for offset, text in enumerate(item.chunk.content.split("\n")):
            lines.setdefault(item.chunk.start_line + offset, text)
    return "\n".join(lines.get(number, "") for number in range(citation.start_line, citation.end_line + 1))
