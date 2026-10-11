from codebase_qa.generation.selfcheck import SelfChecker, evidence
from codebase_qa.models import Chunk, Citation, GeneratedAnswer, RetrievedChunk
from codebase_qa.qa import QAPipeline
from tests.fakes import FakeLLM

CODE = "\n".join(f"line {n}" for n in range(10, 21))
CONTEXT = [RetrievedChunk(Chunk("a", "r", "app/auth.py", "python", 10, 20, CODE), 0.9, {"vector": 0.9})]
ANSWER = GeneratedAnswer("Login checks the password. It also sends an SMS.", [Citation("app/auth.py", 12, 13)])


def checker(payload: object, action: str = "remove") -> tuple[SelfChecker, FakeLLM]:
    llm = FakeLLM({"SelfCheckSchema": lambda _: payload})
    return SelfChecker(llm, action), llm


def verdict(*claims: tuple[str, bool], revised: str = "") -> dict:
    return {"claims": [{"claim": text, "supported": ok} for text, ok in claims], "revised_answer": revised}


def test_evidence_shows_the_whole_containing_block() -> None:
    text = evidence(ANSWER, CONTEXT)
    assert "[app/auth.py:10-20] (cited: lines 12-13)" in text and "line 10" in text and "line 20" in text


def test_supported_answer_is_unchanged() -> None:
    check_with, llm = checker(verdict(("Login checks the password.", True), ("It also sends an SMS.", True)))
    answer, check = check_with.check("q", ANSWER, CONTEXT)
    assert answer == ANSWER and check.ran and check.supported == 2 and check.unsupported == []
    assert "Cited code:" in llm.calls[0][2]


def test_unsupported_claims_are_removed_with_a_note() -> None:
    payload = verdict(("Login checks the password.", True), ("It also sends an SMS.", False), revised="Login checks.")
    answer, check = checker(payload)[0].check("q", ANSWER, CONTEXT)
    assert answer.answer.startswith("Login checks.") and "removed 1 statement" in answer.answer
    assert answer.citations == ANSWER.citations and check.action == "remove"
    assert check.unsupported == ["It also sends an SMS."]


def test_flag_mode_keeps_text_and_lists_claims() -> None:
    payload = verdict(("It also sends an SMS.", False), revised="x")
    answer, check = checker(payload, "flag")[0].check("q", ANSWER, CONTEXT)
    assert answer.answer.startswith(ANSWER.answer) and "- It also sends an SMS." in answer.answer
    assert check.action == "flag"


def test_skipped_without_citations_or_on_bad_output() -> None:
    uncited = GeneratedAnswer("Something.", [])
    with_checker, llm = checker(verdict())
    assert with_checker.check("q", uncited, CONTEXT)[1].ran is False and llm.calls == []
    assert checker("not json")[0].check("q", ANSWER, CONTEXT) == (ANSWER, checker("x")[0].check("q", uncited, [])[1])


class FixedGenerator:
    def generate(self, question: str, context: list[RetrievedChunk]) -> GeneratedAnswer:
        return ANSWER


class OneRetriever:
    name = "vector"
    timings: dict[str, float] = {}

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        return CONTEXT


def test_pipeline_runs_self_check() -> None:
    payload = verdict(("It also sends an SMS.", False), revised="Login checks the password.")
    pipeline = QAPipeline(OneRetriever(), FixedGenerator(), self_checker=checker(payload)[0])
    result = pipeline.ask("How does login work?")
    assert result.self_check.unsupported == ["It also sends an SMS."]
    assert "self_check" in result.timings_ms and "SMS" not in result.answer.answer.split("\n\n")[0]
