import hashlib
import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
    key TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""


def normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question).strip().rstrip("?").strip().casefold()


def answer_key(repo_id: str, commit_sha: str, question: str, scope: dict[str, Any], fingerprint: str) -> str:
    parts = [repo_id, commit_sha, normalize_question(question), json.dumps(scope, sort_keys=True), fingerprint]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class AnswerCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def get(self, key: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM answers WHERE key = ?", (key,)).fetchone()
        return None if row is None else dict(json.loads(row[0]))

    def put(self, key: str, repo_id: str, commit_sha: str, payload: dict[str, Any]) -> None:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        with self.lock, self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO answers (key, repo_id, commit_sha, created_at, payload) VALUES (?, ?, ?, ?, ?)",
                (key, repo_id, commit_sha, stamp, json.dumps(payload)),
            )

    def invalidate(self, repo_id: str) -> int:
        with self.lock, self.connect() as connection:
            return connection.execute("DELETE FROM answers WHERE repo_id = ?", (repo_id,)).rowcount

    def count(self, repo_id: str) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM answers WHERE repo_id = ?", (repo_id,)).fetchone()[0])
