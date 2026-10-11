import re
from typing import Literal

Route = Literal["tool", "overview", "code"]

SUBJECT = r"(this|the|your|that) (repo|repository|project|codebase|code base|code|app|application|system)"

TOOL_PATTERNS = [
    r"^\s*(hi|hello|hey|thanks|thank you|ok|okay)\b[\s!.?]*$",
    r"\b(who|what) are you\b",
    r"\bwhat can (you|i) do\b",
    r"\bwhat (can|should) i ask\b",
    r"\bhow (do|can|should) (i|we) use (you|this (tool|app|assistant|site|chatbot|bot))\b",
    r"\bhow do you (work|answer|find|search|know|decide|cite)\b",
    r"\bthis (tool|assistant|chatbot|bot)\b",
    r"\b(which|what) (llm|language model|ai model|model) (do|are) you\b",
    r"\bare you (an? )?(ai|bot|gpt|llm|human)\b",
    r"\b(your|you) (limits?|privacy|sources|capabilit(y|ies))\b",
    r"\bhow (are|were) (the )?(answers|citations) (made|generated|checked)\b",
]

OVERVIEW_PATTERNS = [
    rf"^\s*what('s| is| does)? {SUBJECT}( (do|about|for|used for))?\s*\??\s*$",
    rf"\b(explain|describe|summari[sz]e|walk me through) {SUBJECT}\b",
    r"\b(overview|summary|high[- ]level|big picture|architecture|tech(nology)? stack|bird'?s[- ]eye)\b",
    r"\b(folder|directory|project|repo|repository|codebase|code) (structure|layout|organi[sz]ation)\b",
    r"\bhow is (the|this) (repo|repository|project|codebase|code|app|application) (organi[sz]ed|structured|laid out)\b",
    r"\bmain (components|parts|modules|pieces|features|folders)\b",
    r"\bwhat (languages?|frameworks?|libraries|technologies|dependencies) (does|is|are)\b",
    r"\bwhere (do|should) i (start|begin)\b",
    r"\bwhat (is|are) the (purpose|goal)s? of (this|the) (repo|repository|project|codebase|app)\b",
]

IDENTIFIER_PATTERNS = [
    r"`[^`]+`",
    r"\b\w+\.(py|pyi|ts|tsx|js|jsx|go|java|json|ya?ml|toml|md|sql|sh|env)\b",
    r"\b[a-z]+_[a-z0-9_]+\b",
    r"\b[a-z]+[A-Z][A-Za-z0-9]*\b",
    r"\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b",
    r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b",
]

CODE_PATTERNS = [
    r"^\s*(where|which|what happens|how (does|do|is|are|long|many|much|can)|when|why|can|does|is there|are there)\b",
    r"\b(function|method|class|endpoint|route|handler|middleware|variable|constant|line|module|component|hook|"
    r"schema|model|table|query|migration|config|setting|environment variable|test)s?\b",
]


def matches(patterns: list[str], text: str, flags: re.RegexFlag = re.IGNORECASE) -> bool:
    return any(re.search(pattern, text, flags) for pattern in patterns)


def rule_route(question: str) -> Route | None:
    text = question.strip()
    if matches(TOOL_PATTERNS, text):
        return "tool"
    if matches(OVERVIEW_PATTERNS, text):
        return "overview"
    if matches(IDENTIFIER_PATTERNS, text, re.NOFLAG) or matches(CODE_PATTERNS, text):
        return "code"
    return None
