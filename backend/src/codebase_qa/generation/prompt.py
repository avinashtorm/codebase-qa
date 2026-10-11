from codebase_qa.models import Chunk, RetrievedChunk, is_overview_path

SYSTEM_PROMPT = """You answer questions about a software repository using only the code context provided.
Each context block starts with a label of the form [path:start-end] giving the file path and line range.
Rules:
- Base every statement on the context. Do not invent files, functions or line numbers.
- Respond as JSON with two fields: "answer" (concise markdown) and "citations" (a list of
  {"path", "start_line", "end_line"} objects).
- Every citation must copy a path exactly from a label and lie entirely inside that block's line range.
  Narrow the range to the specific lines that support the answer.
- Prefer the most specific location (the function or class that does the work) over imports or call sites.
- If the context does not contain enough information, say "I don't know based on the indexed code",
  briefly say what is missing, and return an empty citations list. Do not guess."""

OVERVIEW_SYSTEM_PROMPT = (
    SYSTEM_PROMPT
    + """
- Some blocks are labelled [overview: ...]. They are summaries written from the repository when it was indexed.
  Use them for big-picture answers (purpose, architecture, structure, main parts), but never cite them;
  cite code or README blocks when they support a statement."""
)


def context_label(chunk: Chunk) -> str:
    if is_overview_path(chunk.path):
        return f"[overview: {chunk.header.removeprefix('# Overview: ')}]"
    return f"[{chunk.location}]"


def system_prompt_for(context: list[RetrievedChunk]) -> str:
    if any(is_overview_path(item.chunk.path) for item in context):
        return OVERVIEW_SYSTEM_PROMPT
    return SYSTEM_PROMPT


def format_context(context: list[RetrievedChunk]) -> str:
    blocks = []
    for item in context:
        chunk = item.chunk
        blocks.append(f"{context_label(chunk)}\n```{chunk.language}\n{chunk.content}\n```")
    return "\n\n".join(blocks)


def build_user_prompt(question: str, context: list[RetrievedChunk]) -> str:
    return f"Context:\n\n{format_context(context)}\n\nQuestion: {question}"
