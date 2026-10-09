import json
import shutil
from dataclasses import asdict
from pathlib import Path

import bm25s

from codebase_qa.models import Chunk, RetrievedChunk
from codebase_qa.retrieval.tokenizer import code_tokenize

CHUNKS_FILE = "chunks.json"


class BM25Index:
    def __init__(self, model: bm25s.BM25 | None, chunks: list[Chunk]) -> None:
        self.model = model
        self.chunks = chunks

    @classmethod
    def build(cls, chunks: list[Chunk]) -> "BM25Index":
        ordered = sorted(chunks, key=lambda chunk: (chunk.path, chunk.start_line, chunk.end_line, chunk.chunk_id))
        if not ordered:
            return cls(None, [])
        model = bm25s.BM25()
        corpus = [code_tokenize(f"{chunk.header}\n{chunk.content}") or ["<empty>"] for chunk in ordered]
        model.index(corpus, show_progress=False)
        return cls(model, ordered)

    def save(self, directory: Path) -> None:
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
        if self.model is not None:
            self.model.save(str(directory), show_progress=False)
        payload = [asdict(chunk) for chunk in self.chunks]
        (directory / CHUNKS_FILE).write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "BM25Index":
        chunks = [Chunk(**item) for item in json.loads((directory / CHUNKS_FILE).read_text(encoding="utf-8"))]
        model = bm25s.BM25.load(str(directory), show_progress=False) if chunks else None
        return cls(model, chunks)

    @staticmethod
    def exists(directory: Path) -> bool:
        return (directory / CHUNKS_FILE).exists()

    def search(self, query: str, k: int) -> list[RetrievedChunk]:
        if self.model is None:
            return []
        vocabulary = self.model.vocab_dict
        tokens = [token for token in code_tokenize(query) if token in vocabulary]
        if not tokens:
            return []
        indices, scores = self.model.retrieve([tokens], k=min(k, len(self.chunks)), show_progress=False)
        results = []
        for index, score in zip(indices[0], scores[0], strict=True):
            if score > 0:
                results.append(RetrievedChunk(self.chunks[int(index)], float(score), {"bm25": float(score)}))
        return results


class BM25Retriever:
    name = "bm25"

    def __init__(self, index: BM25Index) -> None:
        self.index = index

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        return self.index.search(query, k)
