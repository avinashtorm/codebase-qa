from codebase_qa.generation.llm import GenerationError, LLMUnavailableError, QuotaExhaustedError, RateLimitedError
from codebase_qa.models import Citation, GeneratedAnswer, RetrievedChunk, is_overview_path

QUOTA_LEAD = "The AI model's free daily quota is used up, so I can't write an answer right now (it resets daily)."
RATE_LIMIT_LEAD = "The AI model is busy right now (rate limit). Please try again in a minute."
UNAVAILABLE_LEAD = "The AI model is unavailable right now, so I can't write an answer. Please try again shortly."
LOCATIONS_LEAD = "These are the code locations that best match your question:"
DEGRADING_ERRORS = (QuotaExhaustedError, RateLimitedError, LLMUnavailableError)


def lead_for(error: GenerationError) -> str:
    if isinstance(error, QuotaExhaustedError):
        return QUOTA_LEAD
    if isinstance(error, RateLimitedError):
        return RATE_LIMIT_LEAD
    return UNAVAILABLE_LEAD


def fallback_answer(error: GenerationError, context: list[RetrievedChunk], limit: int = 3) -> GeneratedAnswer:
    code = [item.chunk for item in context if not is_overview_path(item.chunk.path)][:limit]
    citations = [Citation(chunk.path, chunk.start_line, chunk.end_line) for chunk in code]
    lines = [lead_for(error)]
    if citations:
        lines.append(LOCATIONS_LEAD + "\n" + "\n".join(f"- `{citation.location}`" for citation in citations))
    return GeneratedAnswer(answer="\n\n".join(lines), citations=citations, used_llm=False)
