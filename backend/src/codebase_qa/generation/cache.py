import hashlib
import json
from pathlib import Path
from typing import Any


class ResponseCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @staticmethod
    def key(*parts: str) -> str:
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    def path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get_entry(self, key: str) -> dict[str, Any] | None:
        path = self.path(key)
        if not path.exists():
            return None
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def get(self, key: str) -> str | None:
        entry = self.get_entry(key)
        return None if entry is None else str(entry["text"])

    def put(self, key: str, text: str, **extra: Any) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"text": text} | extra), encoding="utf-8")
