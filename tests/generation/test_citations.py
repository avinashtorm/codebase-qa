from codebase_qa.generation.citations import extract_citations
from codebase_qa.generation.prompt import build_user_prompt
from codebase_qa.models import Chunk, Citation, RetrievedChunk


def test_extract_citations_from_markdown_answer() -> None:
    text = (
        "Login is in `backend/app/api/routes/login.py:20-45` and tokens in "
        "[backend/app/core/security.py:10-18]. Also backend/app/core/security.py:10-18 again, "
        "and a single line Dockerfile:3."
    )
    assert extract_citations(text) == [
        Citation("backend/app/api/routes/login.py", 20, 45),
        Citation("backend/app/core/security.py", 10, 18),
        Citation("Dockerfile", 3, 3),
    ]


def test_extract_ignores_plain_numbers_and_times() -> None:
    assert extract_citations("Runs at 10:30 on port 8000:8000") == []


def test_prompt_labels_each_chunk_with_location() -> None:
    chunk = Chunk("id", "repo", "app/x.py", "python", 3, 9, "def f():\n    pass")
    prompt = build_user_prompt("What is f?", [RetrievedChunk(chunk, 0.9)])
    assert '<context_block source="app/x.py:3-9" language="python">\ndef f():' in prompt
    assert prompt.endswith("<question>What is f?</question>")
