import argparse
from pathlib import Path
from statistics import median

from codebase_qa.config import Settings
from codebase_qa.container import Container
from codebase_qa.generation.grounding import relevance
from eval.dataset import load_questions
from eval.run import DEFAULT_QUESTIONS, DEFAULT_REPO_URL, ensure_indexed

OFF_TOPIC = Path(__file__).parent / "off_topic.txt"


def top_relevance(container: Container, record_url: str, questions: list[str]) -> list[float]:
    record = ensure_indexed(container, record_url)
    retriever = container.retriever(record)
    values = []
    for question in questions:
        scores = [relevance(item) for item in retriever.retrieve(question, container.settings.top_k)]
        values.append(max((s for s in scores if s is not None), default=0.0))
    return values


def suggest_threshold(on_topic: list[float], off_topic: list[float]) -> float:
    lowest_on_topic = min(on_topic)
    candidates = [value for value in off_topic if value < lowest_on_topic]
    upper = max(candidates, default=lowest_on_topic - 0.02)
    return round((upper + lowest_on_topic) / 2, 3)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Calibrate the low-relevance refusal threshold")
    parser.add_argument("--chunker", default="treesitter")
    parser.add_argument("--mode", default="vector", choices=["vector", "hybrid"])
    parser.add_argument("--rerank", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings(chunker=args.chunker, retrieval_mode=args.mode, rerank=args.rerank)
    container = Container(settings)
    dev = [q.question for q in load_questions(DEFAULT_QUESTIONS, split="dev")]
    off = [line.strip() for line in OFF_TOPIC.read_text(encoding="utf-8").splitlines() if line.strip()]
    on_scores = top_relevance(container, DEFAULT_REPO_URL, dev)
    off_scores = top_relevance(container, DEFAULT_REPO_URL, off)
    print(f"dev:       min={min(on_scores):.3f} median={median(on_scores):.3f} max={max(on_scores):.3f}")
    print(f"off-topic: min={min(off_scores):.3f} median={median(off_scores):.3f} max={max(off_scores):.3f}")
    for question, score in sorted(zip(off, off_scores, strict=True), key=lambda pair: -pair[1]):
        print(f"  {score:.3f}  {question}")
    threshold = suggest_threshold(on_scores, off_scores)
    refused_off = sum(score < threshold for score in off_scores)
    print(f"suggested threshold {threshold}: refuses 0/{len(dev)} dev and {refused_off}/{len(off)} off-topic")


if __name__ == "__main__":
    main()
