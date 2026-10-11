import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    route TEXT NOT NULL,
    refused INTEGER NOT NULL,
    confidence TEXT NOT NULL,
    total_ms REAL NOT NULL,
    stages TEXT NOT NULL,
    llm_calls INTEGER NOT NULL,
    cached_calls INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    error TEXT
)
"""


@dataclass(frozen=True)
class QuestionLog:
    repo_id: str
    route: str
    refused: bool
    confidence: str
    total_ms: float
    stages: dict[str, float] = field(default_factory=dict)
    llm_calls: int = 0
    cached_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class Stats:
    questions: int
    errors: int
    avg_latency_ms: float
    p95_latency_ms: float
    total_cost_usd: float
    refusal_rate: float
    input_tokens: int
    output_tokens: int
    llm_calls: int
    cached_calls: int
    avg_stage_ms: dict[str, float]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


class StatsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def record(self, log: QuestionLog) -> None:
        row = (
            datetime.now(UTC).isoformat(timespec="seconds"),
            log.repo_id,
            log.route,
            int(log.refused),
            log.confidence,
            round(log.total_ms, 1),
            json.dumps({stage: round(ms, 1) for stage, ms in log.stages.items()}),
            log.llm_calls,
            log.cached_calls,
            log.input_tokens,
            log.output_tokens,
            log.cost_usd,
            log.error,
        )
        with self.lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO questions (created_at, repo_id, route, refused, confidence, total_ms, stages, llm_calls,"
                " cached_calls, input_tokens, output_tokens, cost_usd, error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )

    def stats(self) -> Stats:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT total_ms, refused, cost_usd, input_tokens, output_tokens, llm_calls, cached_calls,"
                " stages, error FROM questions"
            ).fetchall()
        answered = [row for row in rows if row[8] is None]
        latencies = [float(row[0]) for row in answered]
        stage_values: dict[str, list[float]] = {}
        for row in answered:
            for stage, ms in json.loads(row[7]).items():
                stage_values.setdefault(stage, []).append(float(ms))
        return Stats(
            questions=len(rows),
            errors=len(rows) - len(answered),
            avg_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
            p95_latency_ms=round(percentile(latencies, 0.95), 1),
            total_cost_usd=round(sum(float(row[2]) for row in rows), 6),
            refusal_rate=round(sum(row[1] for row in answered) / len(answered), 4) if answered else 0.0,
            input_tokens=sum(int(row[3]) for row in rows),
            output_tokens=sum(int(row[4]) for row in rows),
            llm_calls=sum(int(row[5]) for row in rows),
            cached_calls=sum(int(row[6]) for row in rows),
            avg_stage_ms={stage: round(sum(v) / len(v), 1) for stage, v in sorted(stage_values.items())},
        )
