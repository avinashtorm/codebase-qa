import hashlib
import json
import math
import re
import time
from collections.abc import Callable

from pydantic import BaseModel

from codebase_qa.config import Settings
from codebase_qa.generation.llm import LLMResponse
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


ITEM_HEADER = re.compile(r"^### (?:repository|folder|file): (.+)$", re.MULTILINE)


def summaries_response(prompt: str) -> dict:
    return {"summaries": [{"path": path, "summary": f"Summary of {path}"} for path in ITEM_HEADER.findall(prompt)]}


class FakeLLM:
    model = "fake-llm"

    def __init__(self, handlers: dict[str, Callable[[str], object]] | None = None) -> None:
        self.handlers: dict[str, Callable[[str], object]] = {"SummariesSchema": summaries_response} | (handlers or {})
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, system: str, prompt: str, schema: type[BaseModel] | None = None) -> LLMResponse:
        name = schema.__name__ if schema is not None else "text"
        self.calls.append((name, system, prompt))
        handler = self.handlers.get(name)
        payload = handler(prompt) if handler else ""
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return LLMResponse(text=text, input_tokens=len(prompt) // 4, output_tokens=len(text) // 4)

    def calls_for(self, schema_name: str) -> list[str]:
        return [prompt for name, _, prompt in self.calls if name == schema_name]


def fake_llm(_: Settings) -> FakeLLM:
    return FakeLLM()


def fake_embedder(_: Settings) -> HashingEmbedder:
    return HashingEmbedder()


def fake_generator(_: Settings) -> EchoGenerator:
    return EchoGenerator()


def make_settings(data_dir: object, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "data_dir": data_dir,
        "min_vector_score": 0.0,
        "allow_local_repos": True,
        "demo_repo_url": "",
        "demo_password": "",
    }
    return Settings(_env_file=None, **(values | overrides))


def wait_for_job(client: object, job_id: str, headers: dict[str, str] | None = None, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}", headers=headers or {}).json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} did not finish")


VISITOR_A = "a" * 32
VISITOR_B = "b" * 32
