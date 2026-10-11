import json
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from codebase_qa.api.app import create_app
from codebase_qa.container import Container
from codebase_qa.generation.cache import ResponseCache
from codebase_qa.generation.gemini_llm import GeminiLLM
from codebase_qa.generation.generator import LLMGenerator
from codebase_qa.generation.llm import QuotaExhaustedError
from codebase_qa.generation.streaming import AnswerDeltas, partial_string_field
from codebase_qa.models import Chunk, Citation, RetrievedChunk
from codebase_qa.qa import QAPipeline
from tests.fakes import VISITOR_A, FakeLLM, fake_embedder, make_settings, wait_for_job

RepoFactory = Callable[..., Path]
CONTEXT = [RetrievedChunk(Chunk("a", "r", "app/auth.py", "python", 1, 9, "def login(): ..."), 0.9, {"vector": 0.9})]
PAYLOAD = json.dumps(
    {
        "answer": 'Login is in `login`.\nIt returns a "token" ✓',
        "citations": [{"path": "app/auth.py", "start_line": 1, "end_line": 2}],
    }
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"citations": []', None),
        ('{"answer": "Hel', "Hel"),
        ('{"answer": "a\\nb\\"c', 'a\nb"c'),
        ('{"answer": "x\\', "x"),
        ('{"answer": "\\u27', ""),
        ('{"answer": "\\u2713 ok", "c', "✓ ok"),
    ],
)
def test_partial_string_field(raw: str, expected: str | None) -> None:
    assert partial_string_field(raw, "answer") == expected


def test_answer_deltas_emit_only_new_text() -> None:
    seen: list[str] = []
    deltas = AnswerDeltas(seen.append)
    for start in range(0, len(PAYLOAD), 5):
        deltas.feed(PAYLOAD[start : start + 5])
    assert "".join(seen) == json.loads(PAYLOAD)["answer"]
    assert all(seen)


def test_generator_streams_and_parses_final_json() -> None:
    llm = FakeLLM({"AnswerSchema": lambda _: PAYLOAD})
    seen: list[str] = []
    answer = LLMGenerator(llm).generate_stream("q", CONTEXT, seen.append)
    assert "".join(seen) == answer.answer and answer.citations == [Citation("app/auth.py", 1, 2)]
    assert len(seen) > 3


class StreamModels:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.calls = 0

    def generate_content_stream(self, **kwargs: object) -> list[SimpleNamespace]:
        self.calls += 1
        usage = SimpleNamespace(prompt_token_count=50, candidates_token_count=9)
        return [SimpleNamespace(text=text, usage_metadata=usage) for text in self.chunks]


def test_gemini_stream_yields_chunks_and_caches(tmp_path: Path) -> None:
    models = StreamModels(['{"answer": "Hi', ' there"}'])
    llm = GeminiLLM(SimpleNamespace(models=models), "m", cache=ResponseCache(tmp_path))
    assert list(llm.stream("s", "p")) == ['{"answer": "Hi', ' there"}']
    assert llm.last_usage is not None and llm.last_usage.input_tokens == 50
    assert list(llm.stream("s", "p")) == ['{"answer": "Hi there"}'] and models.calls == 1
    assert llm.complete("s", "p").text == '{"answer": "Hi there"}'


class OneRetriever:
    name = "vector"
    timings: dict[str, float] = {}

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        return CONTEXT


def test_pipeline_streams_and_still_validates_citations() -> None:
    llm = FakeLLM({"AnswerSchema": lambda _: PAYLOAD})
    seen: list[str] = []
    result = QAPipeline(OneRetriever(), LLMGenerator(llm)).ask("Where is login?", on_delta=seen.append)
    assert "".join(seen) == result.answer.answer
    assert result.answer.citations == [Citation("app/auth.py", 1, 2)] and result.confidence.level in ("high", "medium")


def stream_events(client: TestClient, body: dict, headers: dict) -> list[dict]:
    response = client.post("/ask/stream", json=body, headers=headers)
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def build_client(tmp_path: Path, llm: FakeLLM) -> TestClient:
    container = Container(make_settings(tmp_path / "data"), embedder_factory=fake_embedder, llm_factory=lambda _: llm)
    return TestClient(create_app(container))


def test_stream_endpoint_sends_deltas_then_final(tmp_path: Path, make_repo: RepoFactory) -> None:
    payload = json.dumps(
        {
            "answer": "AuthService.login returns a token.",
            "citations": [{"path": "app/auth.py", "start_line": 2, "end_line": 3}],
        }
    )
    headers = {"X-Visitor-Id": VISITOR_A}
    with build_client(tmp_path, FakeLLM({"AnswerSchema": lambda _: payload})) as client:
        job = client.post("/repos", json={"url": make_repo().as_uri()}, headers=headers).json()
        wait_for_job(client, job["job_id"], headers)
        events = stream_events(client, {"repo_id": "origin", "question": "AuthService login token"}, headers)
        missing = client.post("/ask/stream", json={"repo_id": "nope", "question": "q"}, headers=headers)
    deltas = [event["text"] for event in events if event["type"] == "delta"]
    final = events[-1]
    assert len(deltas) > 1 and "".join(deltas) == "AuthService.login returns a token."
    assert final["type"] == "final" and final["response"]["citations"][0]["path"] == "app/auth.py"
    assert missing.status_code == 404


class QuotaLLM(FakeLLM):
    def stream(self, system: str, prompt: str, schema: type[BaseModel] | None = None) -> Iterator[str]:
        raise QuotaExhaustedError("daily quota exhausted")


def test_stream_endpoint_reports_quota_errors(tmp_path: Path, make_repo: RepoFactory) -> None:
    headers = {"X-Visitor-Id": VISITOR_A}
    with build_client(tmp_path, QuotaLLM()) as client:
        job = client.post("/repos", json={"url": make_repo().as_uri()}, headers=headers).json()
        wait_for_job(client, job["job_id"], headers)
        events = stream_events(client, {"repo_id": "origin", "question": "AuthService login token"}, headers)
    assert events == [
        {"type": "error", "detail": "The AI model's free daily quota is used up. Please try again tomorrow."}
    ]
