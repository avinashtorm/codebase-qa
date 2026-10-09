import json
import re
from pathlib import Path

import httpx
import pytest
from backend_client import BackendClient, BackendError
from code_view import CodeBlock, citation_block, github_link, lexer_for, render_code
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[2] / "frontend" / "app.py")

CONTEXT = [
    {"path": "app/auth.py", "start_line": 10, "end_line": 14, "content": "a\nb\nc\nd\ne"},
    {"path": "app/auth.py", "start_line": 1, "end_line": 40, "content": "\n".join(["x"] * 40)},
]


def test_citation_block_uses_smallest_containing_chunk_and_relative_highlights() -> None:
    citation = {"path": "app/auth.py", "start_line": 11, "end_line": 12, "snippet": "b\nc"}
    block = citation_block(citation, CONTEXT)
    assert block == CodeBlock("a\nb\nc\nd\ne", 10, [2, 3])


def test_citation_block_falls_back_to_snippet() -> None:
    citation = {"path": "other.py", "start_line": 5, "end_line": 6, "snippet": "p\nq"}
    assert citation_block(citation, CONTEXT) == CodeBlock("p\nq", 5, [])


def test_rendered_code_shows_original_line_numbers_and_highlights() -> None:
    html = render_code(CodeBlock("def f():\n    return 1\n", 120, [2]), "python", "a.py")
    numbers = [int(n) for n in re.findall(r">\s*(\d+)\s*<", html.split("</td>")[0])]
    assert numbers[:2] == [120, 121]
    assert "background-color" in html


def test_lexer_selection_handles_aliases_and_unknown_languages() -> None:
    assert lexer_for("python", "x.py").name == "Python"
    assert lexer_for("tsx", "x.tsx").name == "TSX"
    assert lexer_for("dotenv", ".env").name.lower().startswith("bash")
    assert lexer_for("nonsense", "file.unknownext").name == "Text only"


def test_github_link_points_at_commit_and_lines() -> None:
    link = github_link("https://github.com/o/r/", "abc123", "src/a.py", 3, 9)
    assert link == "https://github.com/o/r/blob/abc123/src/a.py#L3-L9"


def mock_backend(handler: callable) -> BackendClient:
    return BackendClient("http://backend", password="pw", transport=httpx.MockTransport(handler))


def test_client_sends_password_and_parses_json() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["password"] = request.headers.get("x-demo-password")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"answer": "ok"})

    assert mock_backend(handler).ask("repo", "q?") == {"answer": "ok"}
    assert seen == {"password": "pw", "body": {"repo_id": "repo", "question": "q?"}}


def test_client_raises_backend_error_with_detail() -> None:
    client = mock_backend(lambda request: httpx.Response(429, json={"detail": "rate limit exceeded"}))
    with pytest.raises(BackendError, match="rate limit exceeded") as error:
        client.repos()
    assert error.value.status_code == 429


def test_client_reports_unreachable_backend() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(BackendError, match="not reachable"):
        mock_backend(handler).health()


def test_app_shows_error_when_backend_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:9")
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert not app.exception
    assert any("Cannot reach the backend" in error.value for error in app.error)
