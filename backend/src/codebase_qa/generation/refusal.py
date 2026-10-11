import re

from codebase_qa.models import GeneratedAnswer, RetrievedChunk, is_overview_path

UNKNOWN = re.compile(
    r"\bI (don't|do not|cannot|can't) (know|find|determine|tell)\b"
    r"|\b(does not|doesn't|do not|don't) (contain|include|show|mention)\b"
    r"|\bnot (found|present|shown|included|available) in the (indexed|provided|given|retrieved)\b",
    re.IGNORECASE,
)
NOT_FOUND_LEAD = "I couldn't find code in this repository that answers that question."
FILES_HEADING = "**Closest files I found:**"
SUGGESTIONS_HEADING = "**Questions that work for this repository:**"
FALLBACK_SUGGESTIONS = (
    "What does this repository do and how is it organized?",
    "Where is the application's entry point?",
    "How is configuration loaded?",
)


def closest_files(context: list[RetrievedChunk], limit: int = 3) -> list[str]:
    paths = [item.chunk.path for item in context if not is_overview_path(item.chunk.path)]
    return list(dict.fromkeys(paths))[:limit]


def is_unknown(answer: GeneratedAnswer) -> bool:
    return not answer.citations and bool(UNKNOWN.search(answer.answer))


def pick_suggestions(suggestions: list[str], limit: int = 3) -> list[str]:
    return (list(suggestions) or list(FALLBACK_SUGGESTIONS))[:limit]


def helpful_text(lead: str, files: list[str], suggestions: list[str]) -> str:
    parts = [lead.strip()]
    if files:
        parts.append(FILES_HEADING + " " + ", ".join(f"`{path}`" for path in files))
    if suggestions:
        parts.append(SUGGESTIONS_HEADING + "\n" + "\n".join(f"- {question}" for question in suggestions))
    return "\n\n".join(parts)


def main_text(answer: str) -> str:
    return answer.split("\n\n" + SUGGESTIONS_HEADING, 1)[0]
