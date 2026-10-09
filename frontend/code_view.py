from dataclasses import dataclass
from typing import Any

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name, get_lexer_for_filename
from pygments.lexers.special import TextLexer
from pygments.styles import get_style_by_name
from pygments.token import Token
from pygments.util import ClassNotFound

BASE_STYLE = get_style_by_name("github-dark")
CodeStyle = type("CodeStyle", (BASE_STYLE,), {"highlight_color": "#3b3410"})
LEXER_ALIASES = {"dotenv": "bash", "make": "makefile", "mako": "html", "hcl": "terraform", "markdown": "md"}


@dataclass(frozen=True)
class CodeBlock:
    code: str
    start_line: int
    highlighted: list[int]


def lexer_for(language: str, path: str) -> Lexer:
    attempts = (lambda: get_lexer_by_name(LEXER_ALIASES.get(language, language)), lambda: get_lexer_for_filename(path))
    for attempt in attempts:
        try:
            return attempt()
        except ClassNotFound:
            continue
    return TextLexer()


def citation_block(citation: dict[str, Any], context: list[dict[str, Any]]) -> CodeBlock:
    start, end = citation["start_line"], citation["end_line"]
    containing = [
        chunk
        for chunk in context
        if chunk["path"] == citation["path"] and chunk["start_line"] <= start and end <= chunk["end_line"]
    ]
    if not containing:
        return CodeBlock(citation["snippet"], start, [])
    chunk = min(containing, key=lambda item: item["end_line"] - item["start_line"])
    offset = chunk["start_line"]
    return CodeBlock(chunk["content"], offset, list(range(start - offset + 1, end - offset + 2)))


def render_code(block: CodeBlock, language: str, path: str) -> str:
    text_color = CodeStyle.styles.get(Token) or "#e6edf3"
    formatter = HtmlFormatter(
        linenos="table",
        linenostart=block.start_line,
        hl_lines=block.highlighted,
        noclasses=True,
        style=CodeStyle,
        wrapcode=True,
        prestyles=f"color: {text_color}; background: {CodeStyle.background_color}; margin: 0",
    )
    html = highlight(block.code, lexer_for(language, path), formatter)
    container = f"background: {CodeStyle.background_color}; border-radius: 6px; overflow-x: auto; font-size: 13px"
    return f'<div style="{container}">{html}</div>'


def github_link(repo_url: str, commit_sha: str, path: str, start_line: int, end_line: int) -> str:
    return f"{repo_url.rstrip('/')}/blob/{commit_sha}/{path}#L{start_line}-L{end_line}"
