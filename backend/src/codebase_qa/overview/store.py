import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from codebase_qa.models import Chunk, RetrievedChunk
from codebase_qa.overview.builder import OverviewEntry


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


@dataclass
class OverviewIndex:
    entries: dict[str, OverviewEntry]
    chunks: list[Chunk]
    embeddings: list[list[float]]

    def embedding_by_id(self) -> dict[str, list[float]]:
        return {chunk.chunk_id: vector for chunk, vector in zip(self.chunks, self.embeddings, strict=True)}

    def search(self, query_embedding: list[float], k: int) -> list[RetrievedChunk]:
        scored = [
            (cosine(query_embedding, vector), chunk) for chunk, vector in zip(self.chunks, self.embeddings, strict=True)
        ]
        ranked = sorted(scored, key=lambda pair: (-pair[0], pair[1].chunk_id))[:k]
        return [RetrievedChunk(chunk=chunk, score=score, scores={"overview": score}) for score, chunk in ranked]

    def find(self, path: str) -> list[Chunk]:
        return [chunk for chunk in self.chunks if chunk.path == path]


class OverviewStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, collection: str) -> Path:
        return self.directory / f"{collection}.json"

    def load(self, collection: str) -> OverviewIndex | None:
        path = self.path(collection)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return OverviewIndex(
            entries={key: OverviewEntry(**value) for key, value in data["entries"].items()},
            chunks=[Chunk(**chunk) for chunk in data["chunks"]],
            embeddings=data["embeddings"],
        )

    def save(self, collection: str, index: OverviewIndex) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "entries": {key: asdict(entry) for key, entry in index.entries.items()},
            "chunks": [asdict(chunk) for chunk in index.chunks],
            "embeddings": index.embeddings,
        }
        temp = self.path(collection).with_suffix(".tmp")
        temp.write_text(json.dumps(payload), encoding="utf-8")
        temp.replace(self.path(collection))

    def delete(self, collection: str) -> None:
        self.path(collection).unlink(missing_ok=True)
