import hashlib
import sqlite3
import threading
from array import array
from collections import OrderedDict
from pathlib import Path

from codebase_qa.interfaces import Embedder


def text_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\x1f{text}".encode()).hexdigest()


class EmbeddingStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, vector BLOB NOT NULL)")

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        found: dict[str, list[float]] = {}
        with self.connect() as connection:
            for start in range(0, len(keys), 500):
                batch = keys[start : start + 500]
                marks = ",".join("?" * len(batch))
                rows = connection.execute(f"SELECT key, vector FROM embeddings WHERE key IN ({marks})", batch)
                for key, blob in rows:
                    found[key] = array("f", blob).tolist()
        return found

    def put_many(self, items: dict[str, list[float]]) -> None:
        rows = [(key, array("f", vector).tobytes()) for key, vector in items.items()]
        with self.lock, self.connect() as connection:
            connection.executemany("INSERT OR REPLACE INTO embeddings (key, vector) VALUES (?, ?)", rows)


class CachingEmbedder:
    def __init__(self, inner: Embedder, store: EmbeddingStore, model: str, query_cache_size: int = 256) -> None:
        self.inner = inner
        self.store = store
        self.model = model
        self.query_cache_size = query_cache_size
        self.queries: OrderedDict[str, list[float]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        keys = [text_key(self.model, text) for text in texts]
        cached = self.store.get_many(list(dict.fromkeys(keys)))
        missing = list(dict.fromkeys(key for key in keys if key not in cached))
        if missing:
            first_text = {key: text for key, text in zip(keys, texts, strict=True)}
            vectors = self.inner.embed_documents([first_text[key] for key in missing])
            fresh = dict(zip(missing, vectors, strict=True))
            self.store.put_many(fresh)
            cached.update(fresh)
        self.hits += len(keys) - len(missing)
        self.misses += len(missing)
        return [cached[key] for key in keys]

    def embed_query(self, text: str) -> list[float]:
        if text in self.queries:
            self.queries.move_to_end(text)
            return self.queries[text]
        vector = self.inner.embed_query(text)
        self.queries[text] = vector
        if len(self.queries) > self.query_cache_size:
            self.queries.popitem(last=False)
        return vector
