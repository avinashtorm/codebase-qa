import argparse
import json
from pathlib import Path
from typing import Any

from eval.run import RESULTS_DIR

COLUMNS: list[tuple[str, str]] = [
    ("hit_at_1", "Hit@1"),
    ("hit_at_5", "Hit@5"),
    ("recall_at_10", "Recall@10"),
    ("mrr", "MRR"),
    ("citation_precision", "Cite prec"),
    ("citation_any_correct", "Cite any"),
    ("retrieval_ms_mean", "Retr ms"),
    ("generation_ms_mean", "Gen ms"),
]


def load_results(results_dir: Path) -> list[dict[str, Any]]:
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(results_dir.glob("*.json"))]
    return sorted(runs, key=lambda run: run["timestamp"])


def latest_per_config(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for run in runs:
        latest[(run["config"], run["split"])] = run
    return sorted(latest.values(), key=lambda run: run["timestamp"])


def format_value(key: str, value: Any) -> str:
    if value is None:
        return "-"
    if key.endswith("_ms_mean"):
        return f"{value:.1f}" if value < 10 else f"{value:.0f}"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def render_table(runs: list[dict[str, Any]]) -> str:
    header = ["Config", "Split", "N", *[label for _, label in COLUMNS], "Timestamp"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for run in runs:
        metrics = run["metrics"]
        cells = [
            run["config"],
            run["split"],
            str(run["question_count"]),
            *[format_value(key, metrics.get(key)) for key, _ in COLUMNS],
            run["timestamp"],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare evaluation runs")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--all", action="store_true", help="show every run, not only the latest per config")
    parser.add_argument("--split", default=None, choices=["dev", "held_out", "all"])
    args = parser.parse_args(argv)
    runs = load_results(args.results_dir)
    if args.split:
        runs = [run for run in runs if run["split"] == args.split]
    print(render_table(runs if args.all else latest_per_config(runs)))


if __name__ == "__main__":
    main()
