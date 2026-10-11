import json
import re
from collections.abc import Callable

ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}

Delta = Callable[[str], None]


def partial_string_field(raw: str, key: str) -> str | None:
    match = re.search(r'"' + re.escape(key) + r'"\s*:\s*"', raw)
    if match is None:
        return None
    out: list[str] = []
    index = match.end()
    while index < len(raw):
        char = raw[index]
        if char == '"':
            break
        if char != "\\":
            out.append(char)
            index += 1
            continue
        if index + 1 >= len(raw):
            break
        code = raw[index + 1]
        if code == "u":
            digits = raw[index + 2 : index + 6]
            if len(digits) < 4:
                break
            try:
                out.append(json.loads(f'"\\u{digits}"'))
            except json.JSONDecodeError:
                break
            index += 6
            continue
        out.append(ESCAPES.get(code, code))
        index += 2
    return "".join(out)


class AnswerDeltas:
    def __init__(self, on_delta: Delta, key: str = "answer") -> None:
        self.on_delta = on_delta
        self.key = key
        self.raw = ""
        self.sent = ""

    def feed(self, chunk: str) -> None:
        self.raw += chunk
        text = partial_string_field(self.raw, self.key)
        if text is None or len(text) <= len(self.sent) or not text.startswith(self.sent):
            return
        self.on_delta(text[len(self.sent) :])
        self.sent = text
