import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from codebase_qa.generation.prompt import OVERVIEW_SYSTEM_PROMPT, SYSTEM_PROMPT
from codebase_qa.models import GeneratedAnswer

REDACTED = "[redacted]"
KEY_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
PROMPT_WINDOW = 60
PROMPT_LEAK_ANSWER = "I can't share my instructions. Ask me about the code in this repository instead."


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def prompt_windows(prompts: tuple[str, ...], size: int = PROMPT_WINDOW) -> set[str]:
    windows: set[str] = set()
    for prompt in prompts:
        text = squash(prompt)
        windows.update(text[start : start + size] for start in range(0, max(1, len(text) - size + 1), size // 2))
    return windows


@dataclass
class OutputGuard:
    secrets: list[str] = field(default_factory=list)
    prompts: tuple[str, ...] = (SYSTEM_PROMPT, OVERVIEW_SYSTEM_PROMPT)

    def __post_init__(self) -> None:
        self.secrets = [secret for secret in self.secrets if len(secret) >= 6]
        self.windows = prompt_windows(self.prompts)

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, REDACTED)
        for pattern in KEY_PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text

    def leaks_prompt(self, text: str) -> bool:
        squashed = squash(text)
        return any(window in squashed for window in self.windows)

    def check(self, answer: GeneratedAnswer) -> tuple[GeneratedAnswer, list[str]]:
        if self.leaks_prompt(answer.answer):
            return replace(answer, answer=PROMPT_LEAK_ANSWER, citations=[]), ["system prompt"]
        redacted = self.redact(answer.answer)
        if redacted != answer.answer:
            return replace(answer, answer=redacted), ["secret"]
        return answer, []


class GuardedDeltas:
    def __init__(self, on_delta: Callable[[str], None], guard: OutputGuard, hold: int = 64) -> None:
        self.on_delta = on_delta
        self.guard = guard
        self.hold = hold
        self.raw = ""
        self.sent = ""

    def __call__(self, text: str) -> None:
        self.raw += text
        safe = self.guard.redact(self.raw)[: max(0, len(self.raw) - self.hold)]
        if self.guard.leaks_prompt(self.raw) or not safe.startswith(self.sent) or len(safe) <= len(self.sent):
            return
        self.on_delta(safe[len(self.sent) :])
        self.sent = safe

    def flush(self) -> None:
        if self.guard.leaks_prompt(self.raw):
            return
        safe = self.guard.redact(self.raw)
        if safe.startswith(self.sent) and len(safe) > len(self.sent):
            self.on_delta(safe[len(self.sent) :])
            self.sent = safe


