from collections.abc import Callable
from pathlib import Path

from codebase_qa.models import Chunk
from codebase_qa.overview.suggestions import OVERVIEW_QUESTION, QuestionSuggester, clean, heuristic_questions
from tests.fakes import FakeLLM, HashingEmbedder
from tests.overview.test_overview import FILES, build_container

RepoFactory = Callable[..., Path]

FOLDER = Chunk("f", "r", "@overview/folder/app", "overview", 1, 2, "Folder app/: api\n- app/main.py: creates the app")


class FakeCollection:
    def __init__(self, scores: dict[str, float], embedder: HashingEmbedder) -> None:
        self.scores = scores
        self.embedder = embedder

    def query(self, embedding: list[float], k: int) -> list[tuple[Chunk, float]]:
        for question, score in self.scores.items():
            if self.embedder.embed_query(question) == embedding:
                return [(FOLDER, score)]
        return []


def test_suggestions_keep_answerable_questions_and_one_overview_question() -> None:
    questions = [
        "What is the architecture of this project?",
        "Where is the item created?",
        "How are refunds processed?",
        "1. Where is the app built",
    ]
    llm = FakeLLM({"SuggestionsSchema": lambda _: {"questions": questions}})
    embedder = HashingEmbedder()
    scores = {"Where is the item created?": 0.7, "How are refunds processed?": 0.3, "Where is the app built?": 0.9}
    suggester = QuestionSuggester(llm, embedder, min_score=0.6)
    result = suggester.suggest([FOLDER], FakeCollection(scores, embedder))
    assert result == [questions[0], "Where is the app built?", "Where is the item created?"]
    assert "Overview:" in llm.calls[0][2] and "creates the app" in llm.calls[0][2]


def test_clean_strips_numbering_and_adds_question_mark() -> None:
    assert clean("2) Where is login handled") == "Where is login handled?"


def test_heuristic_questions_when_llm_unavailable() -> None:
    assert heuristic_questions([FOLDER], 3) == [OVERVIEW_QUESTION, "What does app/main.py do?"]
    assert QuestionSuggester(None, HashingEmbedder(), 0.6).suggest([FOLDER], FakeCollection({}, HashingEmbedder()))


def test_heuristic_questions_ignore_readme_bullets() -> None:
    readme = Chunk("s", "r", "@overview/summary", "overview", 1, 2, "- ⚡ [**FastAPI**](https://fastapi.dev): API")
    noisy = Chunk("g", "r", "@overview/folder/x", "overview", 1, 2, "- see [docs](https://x.io): links\n- x/a.py: a")
    assert heuristic_questions([readme, noisy], 5) == [OVERVIEW_QUESTION, "What does x/a.py do?"]


def test_index_stores_suggestions_and_reindex_keeps_them(tmp_path: Path, make_repo: RepoFactory) -> None:
    llm = FakeLLM({"SuggestionsSchema": lambda _: {"questions": ["What does this repo do?", "Where is list_items?"]}})
    container = build_container(tmp_path, llm, min_vector_score=0.0)
    record = container.indexer.index(make_repo(FILES).as_uri())
    assert record.suggested_questions == ["What does this repo do?", "Where is list_items?"]
    llm.calls.clear()
    record, _ = container.indexer.reindex(record)
    assert llm.calls == [] and record.suggested_questions == ["What does this repo do?", "Where is list_items?"]
    assert container.pipeline(record).suggestions == record.suggested_questions
