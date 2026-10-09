import json
from collections.abc import Callable
from pathlib import Path

from codebase_qa.config import Settings
from codebase_qa.container import Container
from eval.run import parse_args, run
from tests.fakes import fake_embedder, fake_generator

RepoFactory = Callable[..., Path]


def test_run_scores_questions_and_saves_results(tmp_path: Path, make_repo: RepoFactory) -> None:
    origin = make_repo()
    questions = tmp_path / "questions.jsonl"
    rows = [
        {
            "id": "auth",
            "question": "AuthService login token",
            "category": "where-is",
            "expected_locations": [{"path": "app/auth.py", "start_line": 1, "end_line": 3}],
        },
        {
            "id": "hidden",
            "question": "greet name",
            "category": "where-is",
            "expected_locations": [{"path": "web/index.ts", "start_line": 1, "end_line": 3}],
            "held_out": True,
        },
    ]
    questions.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    args = parse_args(
        [
            "--config", "test-config",
            "--questions", str(questions),
            "--results-dir", str(tmp_path / "results"),
            "--repo-url", origin.as_uri(),
            "--answers",
        ]
    )
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    container = Container(settings, embedder_factory=fake_embedder, generator_factory=fake_generator)

    path = run(args, container)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name.startswith("test-config_")
    assert payload["question_count"] == 1
    assert payload["metrics"]["hit_at_1"] == 1.0
    assert payload["metrics"]["citation_precision"] == 1.0
    assert payload["by_category"]["where-is"]["count"] == 1
    assert payload["questions"][0]["citations"] == ["app/auth.py:1-7"]
