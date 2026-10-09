import hashlib
import math
import re

from codebase_qa.config import Settings
from codebase_qa.models import Citation, GeneratedAnswer, RetrievedChunk

TOKEN = re.compile(r"[A-Za-z]+")


class HashingEmbedder:
    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def vector(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        for token in TOKEN.findall(text.lower()):
            bucket = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dimension
            values[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.vector(text)


class EchoGenerator:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        self.calls += 1
        if not context:
            return GeneratedAnswer(answer="I don't know.", citations=[])
        top = context[0].chunk
        citation = Citation(path=top.path, start_line=top.start_line, end_line=top.end_line)
        return GeneratedAnswer(answer=f"See {citation.location}", citations=[citation])


def fake_embedder(_: Settings) -> HashingEmbedder:
    return HashingEmbedder()


def fake_generator(_: Settings) -> EchoGenerator:
    return EchoGenerator()
