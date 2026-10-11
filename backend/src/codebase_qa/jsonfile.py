import json
import os
import threading
from pathlib import Path
from typing import Any


class JsonFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.text: str | None = None
        self.stamp: tuple[int, int] | None = None

    def read(self) -> dict[str, Any]:
        with self.lock:
            if not self.path.exists():
                return {}
            stat = self.path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            if self.text is None or stamp != self.stamp:
                self.text = self.path.read_text(encoding="utf-8")
                self.stamp = stamp
            return dict(json.loads(self.text))

    def write(self, data: dict[str, Any], indent: int | None = 1) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(data, indent=indent)
            temp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            temp.write_text(text, encoding="utf-8")
            temp.replace(self.path)
            stat = self.path.stat()
            self.text = text
            self.stamp = (stat.st_mtime_ns, stat.st_size)
