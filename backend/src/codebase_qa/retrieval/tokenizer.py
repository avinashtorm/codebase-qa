import re

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
CAMEL_PARTS = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|[A-Z]+|\d+")

STOPWORDS = frozenset(
    """
    a an and are as at be by does do did for from how i in is it of on or that the this to was what when
    where which who why with will would can could should there their them they you your we our me my
    happens happen
    """.split()
)


def identifier_parts(identifier: str) -> list[str]:
    parts: list[str] = []
    for piece in identifier.split("_"):
        parts.extend(match.group(0).lower() for match in CAMEL_PARTS.finditer(piece))
    return [part for part in parts if part]


def code_tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in IDENTIFIER.finditer(text):
        identifier = match.group(0)
        full = identifier.lower().strip("_")
        if not full or full in STOPWORDS:
            continue
        tokens.append(full)
        parts = identifier_parts(identifier)
        if len(parts) > 1:
            tokens.extend(part for part in parts if part not in STOPWORDS)
    return tokens
