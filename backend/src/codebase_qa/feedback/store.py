import json
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Rating = Literal["up", "down"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    answer_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    rating TEXT NOT NULL,
    comment TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    route TEXT NOT NULL,
    confidence TEXT NOT NULL,
    citations TEXT NOT NULL,
    retrieved TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class AnswerRecord:
    answer_id: str
    repo_id: str
    commit_sha: str
    question: str
    answer: str
    route: str
    confidence: str
    citations: list[str] = field(default_factory=list)
    retrieved: list[dict[str, Any]] = field(default_factory=list)


class RecentAnswers:
    def __init__(self, capacity: int = 2000) -> None:
        self.capacity = capacity
        self.items: OrderedDict[str, AnswerRecord] = OrderedDict()
        self.lock = threading.Lock()

    def remember(self, record: AnswerRecord) -> None:
        with self.lock:
            self.items[record.answer_id] = record
            self.items.move_to_end(record.answer_id)
            while len(self.items) > self.capacity:
                self.items.popitem(last=False)

    def get(self, answer_id: str) -> AnswerRecord | None:
        with self.lock:
            return self.items.get(answer_id)


class FeedbackStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def add(self, record: AnswerRecord, rating: Rating, comment: str = "") -> None:
        row = (
            datetime.now(UTC).isoformat(timespec="seconds"),
            record.answer_id,
            record.repo_id,
            record.commit_sha,
            rating,
            comment,
            record.question,
            record.answer,
            record.route,
            record.confidence,
            json.dumps(record.citations),
            json.dumps(record.retrieved),
        )
        with self.lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO feedback (created_at, answer_id, repo_id, commit_sha, rating, comment, question, answer,"
                " route, confidence, citations, retrieved) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )

    def rows(self) -> Iterator[dict[str, Any]]:
        with self.connect() as connection:
            connection.row_factory = sqlite3.Row
            for row in connection.execute("SELECT * FROM feedback ORDER BY id"):
                item = dict(row)
                item["citations"] = json.loads(item["citations"])
                item["retrieved"] = json.loads(item["retrieved"])
                yield item

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute("SELECT rating, COUNT(*) FROM feedback GROUP BY rating").fetchall()
        return {"up": 0, "down": 0} | {rating: int(count) for rating, count in rows}


def export_jsonl(store: FeedbackStore, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        for row in store.rows():
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


