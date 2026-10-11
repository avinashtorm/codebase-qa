import argparse
import json
import re
from collections.abc import Iterator
from pathlib import Path

import uvicorn
from pydantic import BaseModel

from codebase_qa.api.app import create_app
from codebase_qa.config import Settings
from codebase_qa.container import Container
from codebase_qa.generation.llm import LLMResponse

VISITORS = 64


def visitor_id(number: int) -> str:
    return f"{number:032x}"


SOURCE = re.compile(r'<context_block source="([^"]+):(\d+)-(\d+)"')


class MockLLM:
    model = "mock-llm"

    def reply(self, prompt: str, schema: type[BaseModel] | None) -> str:
        name = schema.__name__ if schema else "text"
        if name == "AnswerSchema":
            match = SOURCE.search(prompt)
            citations = []
            if match:
                path, start, end = match.group(1), int(match.group(2)), int(match.group(3))
                citations = [{"path": path, "start_line": start, "end_line": min(end, start + 3)}]
            return json.dumps({"answer": "The first retrieved block answers this.", "citations": citations})
        if name == "SelfCheckSchema":
            return json.dumps({"claims": [{"claim": "answer", "supported": True}], "revised_answer": "ok"})
        if name == "RouteSchema":
            return json.dumps({"route": "code"})
        return "ok"

    def complete(self, system: str, prompt: str, schema: type[BaseModel] | None = None) -> LLMResponse:
        text = self.reply(prompt, schema)
        return LLMResponse(text, len(prompt) // 4, len(text) // 4)

    def stream(self, system: str, prompt: str, schema: type[BaseModel] | None = None) -> Iterator[str]:
        yield self.reply(prompt, schema)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backend with a mocked LLM for load testing")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args(argv)
    settings = Settings(
        _env_file=None,
        data_dir=args.data_dir,
        demo_repo_url="",
        answer_cache=False,
        embedding_cache=False,
        ask_rate_limit_per_minute=1_000_000,
        ask_per_visitor_per_day=1_000_000,
        index_per_visitor_per_day=1_000_000,
        log_level="WARNING",
    )
    container = Container(settings, llm_factory=lambda _: MockLLM())
    for record in container.repo_records():
        for number in range(VISITORS):
            container.access.grant(record.repo_id, visitor_id(number))
    app = create_app(container)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
