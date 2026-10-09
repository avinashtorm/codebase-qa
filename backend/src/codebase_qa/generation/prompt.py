from codebase_qa.models import RetrievedChunk

SYSTEM_PROMPT = """You answer questions about a software repository using only the code context provided.
Each context block starts with a label of the form path:start-end giving the file path and line range.
Rules:
- Base every statement on the context. Do not invent files, functions or line numbers.
- Cite the code that supports each statement as path:start-end, copying the path exactly from a label.
  You may narrow a range to the specific lines inside a block, but never cite lines outside the blocks.
- Prefer the most specific location (the function or class that does the work) over imports or call sites.
- If the context does not contain enough information to answer, say "I don't know based on the indexed code"
  and briefly say what is missing. Do not guess.
- Be concise: a short explanation followed by the key locations."""


def format_context(context: list[RetrievedChunk]) -> str:
    blocks = []
    for item in context:
        chunk = item.chunk
        blocks.append(f"[{chunk.location}]\n```{chunk.language}\n{chunk.content}\n```")
    return "\n\n".join(blocks)


def build_user_prompt(question: str, context: list[RetrievedChunk]) -> str:
    return f"Context:\n\n{format_context(context)}\n\nQuestion: {question}"
