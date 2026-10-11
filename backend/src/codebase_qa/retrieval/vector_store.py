import re
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from codebase_qa.models import Chunk


def collection_name(repo_id: str, variant: str) -> str:
    raw = f"{repo_id}--{variant}"
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "-", raw).strip("-._")
    return cleaned[:63].rstrip("-._")


def chunk_metadata(chunk: Chunk) -> dict[str, Any]:
    return {
        "repo_id": chunk.repo_id,
        "path": chunk.path,
        "language": chunk.language,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "header": chunk.header,
    }


def chunk_from_record(chunk_id: str, document: str, metadata: dict[str, Any]) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        repo_id=str(metadata["repo_id"]),
        path=str(metadata["path"]),
        language=str(metadata["language"]),
        start_line=int(metadata["start_line"]),
        end_line=int(metadata["end_line"]),
        content=document,
        header=str(metadata.get("header", "")),
    )


class VectorCollection:
    def __init__(self, raw: Any, max_batch: int) -> None:
        self.raw = raw
        self.max_batch = max(1, min(max_batch, 2000))

    @property
    def name(self) -> str:
        return str(self.raw.name)

    def count(self) -> int:
        return int(self.raw.count())

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        for start in range(0, len(chunks), self.max_batch):
            batch = chunks[start : start + self.max_batch]
            self.raw.upsert(
                ids=[chunk.chunk_id for chunk in batch],
                documents=[chunk.content for chunk in batch],
                metadatas=[chunk_metadata(chunk) for chunk in batch],
                embeddings=embeddings[start : start + self.max_batch],
            )

    def query(self, embedding: list[float], k: int, paths: list[str] | None = None) -> list[tuple[Chunk, float]]:
        total = self.count()
        if total == 0 or (paths is not None and not paths):
            return []
        where = {"path": {"$in": paths}} if paths is not None else None
        result = self.raw.query(
            query_embeddings=[embedding],
            n_results=min(k, total),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        columns = [result[key][0] for key in ("ids", "documents", "metadatas", "distances")]
        rows = zip(*columns, strict=True)
        return [(chunk_from_record(cid, doc, meta), 1.0 - float(dist)) for cid, doc, meta, dist in rows]

    def all_chunks(self) -> list[Chunk]:
        result = self.raw.get(include=["documents", "metadatas"])
        rows = zip(result["ids"], result["documents"], result["metadatas"], strict=True)
        chunks = [chunk_from_record(cid, doc, meta) for cid, doc, meta in rows]
        return sorted(chunks, key=lambda chunk: (chunk.path, chunk.start_line, chunk.end_line))

    def delete_paths(self, paths: list[str]) -> int:
        if not paths:
            return 0
        existing = self.raw.get(where={"path": {"$in": paths}}, include=[])
        ids = list(existing["ids"])
        if ids:
            self.raw.delete(ids=ids)
        return len(ids)


class ChromaStore:
    def __init__(self, persist_dir: Path) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(persist_dir), settings=ChromaSettings(anonymized_telemetry=False)
        )

    def collection(self, name: str) -> VectorCollection:
        raw = self.client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
        return VectorCollection(raw, self.client.get_max_batch_size())

    def delete_collection(self, name: str) -> None:
        if name in self.list_collections():
            self.client.delete_collection(name)

    def list_collections(self) -> list[str]:
        return [collection.name for collection in self.client.list_collections()]
