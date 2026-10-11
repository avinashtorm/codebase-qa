import json
from collections.abc import Callable
from pathlib import Path

import pytest

from codebase_qa.container import Container
from codebase_qa.generation.grounding import validate_citations
from codebase_qa.generation.prompt import OVERVIEW_SYSTEM_PROMPT, SYSTEM_PROMPT, system_prompt_for
from codebase_qa.models import Chunk, Citation, RetrievedChunk
from codebase_qa.routing.router import QuestionRouter
from codebase_qa.routing.rules import rule_route
from codebase_qa.routing.tool import FALLBACK_ANSWER, ToolAnswerer
from eval.dataset import CODE_CATEGORIES
from tests.fakes import FakeLLM, fake_embedder, fake_generator, make_settings
from tests.overview.test_overview import FILES

RepoFactory = Callable[..., Path]
DEV_ROWS = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[2] / "eval" / "questions.jsonl").read_text("utf-8").splitlines()
    if line.strip()
]
DEV_QUESTIONS = [row["question"] for row in DEV_ROWS if not row.get("held_out") and row["category"] in CODE_CATEGORIES]
OVERVIEW_QUESTIONS = [row["question"] for row in DEV_ROWS if row["category"] == "overview"]


@pytest.mark.parametrize(
    "question",
    ["hi", "What can you do?", "How do you work?", "Which model do you use?", "How should I use this tool?"],
)
def test_tool_questions(question: str) -> None:
    assert rule_route(question) == "tool"


@pytest.mark.parametrize(
    "question",
    [
        "What does this repo do?",
        "Give me an overview of the project",
        "What is the tech stack?",
        "Explain the codebase",
        "How is the project structured?",
        "What are the main components?",
        "Where should I start reading?",
    ],
)
def test_overview_questions(question: str) -> None:
    assert rule_route(question) == "overview"


@pytest.mark.parametrize(
    "question", ["Where is get_password_hash used?", "What does `useAuth` return?", "Explain crud.py", "the userId"]
)
def test_code_questions(question: str) -> None:
    assert rule_route(question) == "code"


def test_every_dev_question_is_routed_to_code_by_rules() -> None:
    assert DEV_QUESTIONS and {question: rule_route(question) for question in DEV_QUESTIONS} == {
        question: "code" for question in DEV_QUESTIONS
    }


def test_router_asks_llm_only_when_rules_are_unsure() -> None:
    llm = FakeLLM({"RouteSchema": lambda _: {"route": "overview"}})
    router = QuestionRouter(llm)
    assert router.route("Where is login?").method == "rule"
    decision = router.route("Tell me about authentication and users")
    assert (decision.route, decision.method) == ("overview", "llm")
    assert len(llm.calls) == 1


def test_router_defaults_to_code_when_llm_fails() -> None:
    decision = QuestionRouter(FakeLLM({"RouteSchema": lambda _: "not json"})).route("Tell me about users")
    assert (decision.route, decision.method) == ("code", "default")


def test_tool_answer_uses_llm_and_falls_back() -> None:
    llm = FakeLLM({"text": lambda _: "I answer questions about code."})
    assert ToolAnswerer(llm).answer("what can you do").answer == "I answer questions about code."
    assert ToolAnswerer(None).answer("what can you do").answer == FALLBACK_ANSWER


def test_overview_chunks_are_never_valid_citations() -> None:
    overview = Chunk("o", "r", "@overview/repository", "overview", 1, 3, "summary", "# Overview: x", "overview")
    code = Chunk("c", "r", "app/main.py", "python", 1, 5, "code")
    context = [RetrievedChunk(overview, 1.0), RetrievedChunk(code, 0.9)]
    cited = [Citation("@overview/repository", 1, 2), Citation("app/main.py", 2, 3)]
    valid, invalid = validate_citations(cited, context)
    assert valid == [Citation("app/main.py", 2, 3)] and invalid == 1
    assert system_prompt_for(context) == OVERVIEW_SYSTEM_PROMPT
    assert system_prompt_for(context[1:]) == SYSTEM_PROMPT


def build(tmp_path: Path, llm: FakeLLM, **overrides: object) -> Container:
    return Container(
        make_settings(tmp_path / "data", **overrides),
        embedder_factory=fake_embedder,
        generator_factory=fake_generator,
        llm_factory=lambda _: llm,
    )


def test_pipeline_routes_tool_overview_and_code(tmp_path: Path, make_repo: RepoFactory) -> None:
    llm = FakeLLM({"text": lambda _: "I am a code Q&A assistant."})
    container = build(tmp_path, llm)
    record = container.indexer.index(make_repo(FILES).as_uri())
    pipeline = container.pipeline(record)

    tool = pipeline.ask("What can you do?")
    assert tool.route == "tool" and tool.context == [] and tool.answer.answer == "I am a code Q&A assistant."

    overview = pipeline.ask("What is the architecture of this project?")
    paths = [item.chunk.path for item in overview.context]
    assert overview.route == "overview"
    assert sum(path.startswith("@overview/") or path == "README.md" for path in paths) == 3
    assert len(paths) == container.settings.top_k

    code = pipeline.ask("Where is create_item defined?")
    assert code.route == "code"
    assert not any(item.chunk.path.startswith("@overview/") for item in code.context)


def test_routing_can_be_disabled(tmp_path: Path, make_repo: RepoFactory) -> None:
    container = build(tmp_path, FakeLLM(), routing=False)
    record = container.indexer.index(make_repo(FILES).as_uri())
    assert container.pipeline(record).ask("What can you do?").route == "code"


def test_most_overview_eval_questions_route_to_overview() -> None:
    routes = [rule_route(question) for question in OVERVIEW_QUESTIONS]
    assert routes.count("overview") >= 6 and "tool" not in routes
