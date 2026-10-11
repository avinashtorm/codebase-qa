import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

CATEGORIES = ("where-is", "how-does", "what-happens-when", "config", "follow-up")
Split = Literal["dev", "held_out", "all"]


@dataclass(frozen=True)
class Location:
    path: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    question: str
    category: str
    expected_locations: list[Location]
    held_out: bool = False
    history: list[dict[str, str]] = field(default_factory=list)


def parse_question(data: dict) -> EvalQuestion:
    if data["category"] not in CATEGORIES:
        raise ValueError(f"{data['id']}: unknown category {data['category']}")
    locations = [Location(**location) for location in data["expected_locations"]]
    if not locations:
        raise ValueError(f"{data['id']}: expected_locations is empty")
    for location in locations:
        if location.start_line < 1 or location.end_line < location.start_line:
            raise ValueError(f"{data['id']}: invalid line range in {location}")
    return EvalQuestion(
        id=data["id"],
        question=data["question"],
        category=data["category"],
        expected_locations=locations,
        held_out=bool(data.get("held_out", False)),
        history=list(data.get("history", [])),
    )


def load_questions(path: Path, split: Split = "dev", limit: int | None = None) -> list[EvalQuestion]:
    questions = [
        parse_question(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [question.id for question in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question ids")
    if split == "dev":
        questions = [question for question in questions if not question.held_out]
    elif split == "held_out":
        questions = [question for question in questions if question.held_out]
    return questions[:limit] if limit else questions
