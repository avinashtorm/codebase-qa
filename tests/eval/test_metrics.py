import json
from pathlib import Path

import pytest

from eval.compare import latest_per_config, render_table
from eval.dataset import Location, load_questions
from eval.metrics import (
    hit_at_k,
    overlaps,
    recall_at_k,
    reciprocal_rank,
    score_citations,
    score_retrieval,
)

EXPECTED = [Location("a.py", 10, 20), Location("b.py", 1, 5)]


def loc(path: str, start: int, end: int) -> Location:
    return Location(path, start, end)


def test_overlap_requires_same_path_and_intersecting_lines() -> None:
    assert overlaps(loc("a.py", 1, 10), loc("a.py", 10, 20))
    assert overlaps(loc("a.py", 15, 16), loc("a.py", 10, 20))
    assert not overlaps(loc("a.py", 1, 9), loc("a.py", 10, 20))
    assert not overlaps(loc("x.py", 10, 20), loc("a.py", 10, 20))


def test_ranking_metrics() -> None:
    ranked = [loc("z.py", 1, 5), loc("a.py", 18, 30), loc("b.py", 3, 3)]
    assert hit_at_k(ranked, EXPECTED, 1) == 0.0
    assert hit_at_k(ranked, EXPECTED, 2) == 1.0
    assert recall_at_k(ranked, EXPECTED, 2) == 0.5
    assert recall_at_k(ranked, EXPECTED, 10) == 1.0
    assert reciprocal_rank(ranked, EXPECTED) == 0.5
    assert score_retrieval([], EXPECTED).mrr == 0.0


def test_citation_scores() -> None:
    scores = score_citations([loc("a.py", 12, 14), loc("c.py", 1, 2)], EXPECTED)
    assert scores.precision == 0.5
    assert scores.any_correct == 1.0
    assert score_citations([], EXPECTED).precision == 0.0


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def question(qid: str, held_out: bool = False, category: str = "where-is") -> dict:
    return {
        "id": qid,
        "question": f"q {qid}",
        "category": category,
        "expected_locations": [{"path": "a.py", "start_line": 1, "end_line": 3}],
        "held_out": held_out,
    }


def test_load_questions_splits(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "q.jsonl", [question("1"), question("2", True), question("3")])
    assert [q.id for q in load_questions(path, "dev")] == ["1", "3"]
    assert [q.id for q in load_questions(path, "held_out")] == ["2"]
    assert [q.id for q in load_questions(path, "all", limit=2)] == ["1", "2"]


def test_load_questions_rejects_bad_rows(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="category"):
        load_questions(write_jsonl(tmp_path / "a.jsonl", [question("1", category="other")]))
    with pytest.raises(ValueError, match="duplicate"):
        load_questions(write_jsonl(tmp_path / "b.jsonl", [question("1"), question("1")]))


def test_compare_table_uses_latest_run_per_config() -> None:
    runs = [
        {"config": "base", "split": "dev", "question_count": 2, "timestamp": "1", "metrics": {"mrr": 0.1}},
        {"config": "base", "split": "dev", "question_count": 2, "timestamp": "2", "metrics": {"mrr": 0.5}},
    ]
    table = render_table(latest_per_config(runs))
    assert "0.500" in table
    assert "0.100" not in table


def test_suggest_threshold_sits_between_off_topic_and_lowest_dev_score() -> None:
    from eval.calibrate import suggest_threshold

    assert suggest_threshold([0.70, 0.80], [0.40, 0.60, 0.75]) == 0.65
    assert suggest_threshold([0.70], [0.90]) == 0.69
