import hashlib
import json
from pathlib import Path


class ResponseCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @staticmethod
    def key(*parts: str) -> str:
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    def path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> str | None:
        path = self.path(key)
        if not path.exists():
            return None
        return str(json.loads(path.read_text(encoding="utf-8"))["text"])

    def put(self, key: str, text: str) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"text": text}), encoding="utf-8")
