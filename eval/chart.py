import argparse
import json
from pathlib import Path
from typing import Any

from eval.run import RESULTS_DIR

SERIES: list[tuple[str, str]] = [
    ("Baseline (40-line chunks)", "baseline-fixed-vector_"),
    ("Tree-sitter", "treesitter-vector_"),
    ("Hybrid BM25", "treesitter-hybrid_"),
    ("Hybrid + rerank fusion", "treesitter-hybrid-rerank-fusion_"),
    ("+ Index hygiene (Part A)", "step04-hygiene_"),
    ("Final (Parts A-D)", "final-dev-final-retrieval_"),
]
METRICS: list[tuple[str, str, str]] = [
    ("hit_at_1", "Hit@1", "#7C83FD"),
    ("hit_at_5", "Hit@5", "#3FB950"),
    ("mrr", "MRR", "#D29922"),
]
WIDTH, HEIGHT, LEFT, BOTTOM, TOP = 960, 420, 60, 110, 50


def latest(results_dir: Path, prefix: str) -> dict[str, Any]:
    files = sorted(results_dir.glob(f"{prefix}*.json"))
    if not files:
        raise FileNotFoundError(f"no results for {prefix}")
    return json.loads(files[-1].read_text(encoding="utf-8"))["metrics"]


def render(rows: list[tuple[str, dict[str, Any]]]) -> str:
    plot_height = HEIGHT - BOTTOM - TOP
    group = (WIDTH - LEFT - 20) / len(rows)
    bar = group * 0.8 / len(METRICS)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="Segoe UI, Helvetica, Arial, sans-serif">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#0D1117"/>',
        f'<text x="{LEFT}" y="28" fill="#E6EDF3" font-size="16" font-weight="600">'
        "Retrieval on the 35 development questions</text>",
    ]
    for step in range(0, 11, 2):
        value = step / 10
        y = TOP + plot_height * (1 - value)
        parts.append(f'<line x1="{LEFT}" x2="{WIDTH - 20}" y1="{y:.1f}" y2="{y:.1f}" stroke="#30363D"/>')
        parts.append(
            f'<text x="{LEFT - 8}" y="{y + 4:.1f}" fill="#8B949E" font-size="11" text-anchor="end">{value:.1f}</text>'
        )
    for index, (label, metrics) in enumerate(rows):
        start = LEFT + index * group + group * 0.1
        for offset, (key, _, color) in enumerate(METRICS):
            value = float(metrics[key])
            height = plot_height * value
            x = start + offset * bar
            y = TOP + plot_height - height
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar - 2:.1f}" height="{height:.1f}" fill="{color}"/>')
            parts.append(
                f'<text x="{x + bar / 2 - 1:.1f}" y="{y - 4:.1f}" fill="#E6EDF3" font-size="10" '
                f'text-anchor="middle">{value:.2f}</text>'
            )
        center = LEFT + index * group + group / 2
        words = label.split(" ")
        lines = [" ".join(words[: (len(words) + 1) // 2]), " ".join(words[(len(words) + 1) // 2 :])]
        for line_number, line in enumerate(line for line in lines if line):
            y = HEIGHT - BOTTOM + 22 + line_number * 15
            parts.append(
                f'<text x="{center:.1f}" y="{y}" fill="#C9D1D9" font-size="12" text-anchor="middle">{line}</text>'
            )
    for offset, (_, name, color) in enumerate(METRICS):
        x = LEFT + offset * 90
        y = HEIGHT - 28
        parts.append(f'<rect x="{x}" y="{y - 10}" width="12" height="12" fill="{color}"/>')
        parts.append(f'<text x="{x + 18}" y="{y}" fill="#C9D1D9" font-size="12">{name}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Render the evaluation chart used in the README")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--out", type=Path, default=Path("docs/eval-chart.svg"))
    args = parser.parse_args(argv)
    rows = [(label, latest(args.results_dir, prefix)) for label, prefix in SERIES]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(rows), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
