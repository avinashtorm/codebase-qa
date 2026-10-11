import argparse
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codebase_qa.config import Settings
from codebase_qa.container import Container
from codebase_qa.generation.llm import GenerationError
from codebase_qa.generation.refusal import is_unknown
from codebase_qa.indexing.registry import RepoRecord
from codebase_qa.ingestion.git import repo_id_from_url
from codebase_qa.interfaces import LLM
from codebase_qa.models import Chunk, RetrievedChunk
from codebase_qa.retrieval.filters import NO_FILTER, SearchFilter
from codebase_qa.routing.followup import Turn
from eval.aggregate import aggregate, by_category
from eval.dataset import EvalQuestion, load_questions
from eval.judge import judge
from eval.metrics import score_citations, score_retrieval

EVAL_DIR = Path(__file__).parent
DEFAULT_QUESTIONS = EVAL_DIR / "questions.jsonl"
RESULTS_DIR = EVAL_DIR / "results"
DEFAULT_REPO_URL = "https://github.com/fastapi/full-stack-fastapi-template"
RETRIEVAL_DEPTH = 10


def ensure_indexed(container: Container, url: str) -> RepoRecord:
    record = container.repo_record(repo_id_from_url(url))
    if record is None or container.store.collection(record.collection).count() == 0:
        print(f"indexing {url} with chunker={container.settings.chunker} ...")
        return container.indexer.index(url)
    return container.indexer.backfill_insights(record, print)


def oracle_filter(question: EvalQuestion) -> SearchFilter:
    path = question.expected_locations[0].path
    return SearchFilter(folder=path.split("/")[0]) if "/" in path else NO_FILTER


def describe(item: RetrievedChunk) -> dict[str, Any]:
    chunk = item.chunk
    return {"location": chunk.location, "score": round(item.score, 4)}


def retrieval_scores(spans: list[Chunk], question: EvalQuestion) -> dict[str, float] | None:
    if not question.expected_locations:
        return None
    return asdict(score_retrieval(spans, question.expected_locations))


def evaluate_question(
    container: Container,
    record: RepoRecord,
    question: EvalQuestion,
    with_answers: bool,
    oracle: bool = False,
    judge_llm: LLM | None = None,
) -> dict[str, Any]:
    pipeline = container.pipeline(record, oracle_filter(question) if oracle else NO_FILTER)
    history = [Turn(turn["role"], turn["content"]) for turn in question.history]
    retrieval = pipeline.retrieve(question.question, RETRIEVAL_DEPTH, history)
    ranked = retrieval.code
    spans = [item.chunk for item in ranked]
    result: dict[str, Any] = {
        "id": question.id,
        "category": question.category,
        "question": question.question,
        "standalone_question": retrieval.question,
        "rewrite_method": retrieval.rewrite_method,
        "route": retrieval.route,
        "route_method": retrieval.route_method,
        "expected": [asdict(location) for location in question.expected_locations],
        "retrieved": [describe(item) for item in ranked],
        "overview": [describe(item) for item in retrieval.overview],
        "retrieval": retrieval_scores(spans, question),
        "latency_ms": dict(retrieval.timings_ms),
    }
    if with_answers:
        answered = pipeline.answer(question.question, retrieval)
        answer = answered.answer
        for stage in ("context", "generation", "self_check"):
            if stage in answered.timings_ms:
                result["latency_ms"][stage] = answered.timings_ms[stage]
        result["used_llm"] = answer.used_llm
        result["refused"] = answered.refused
        result["self_check"] = asdict(answered.self_check)
        result["confidence"] = answered.confidence.level
        result["answer"] = answer.answer
        result["citations"] = [citation.location for citation in answer.citations]
        result["invalid_citations"] = answer.invalid_citations
        result["declined"] = answered.refused or is_unknown(answer)
        if question.expected_locations:
            result["citation_scores"] = asdict(score_citations(answer.citations, question.expected_locations))
        if judge_llm is not None:
            verdict = judge(judge_llm, question.question, answer.answer, answered.context)
            result["judge"] = asdict(verdict) if verdict is not None else None
    return result


def save_results(payload: dict[str, Any], results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = payload["timestamp"].replace(":", "").replace("-", "")
    path = results_dir / f"{payload['config']}_{stamp}.json"
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


def run(args: argparse.Namespace, container: Container | None = None) -> Path:
    container = container or Container(Settings(**settings_overrides(args)))
    settings = container.settings
    record = ensure_indexed(container, args.repo_url)
    questions = load_questions(args.questions, split=args.split, limit=args.limit)
    rows = []
    generation_error: str | None = None
    for index, question in enumerate(questions, start=1):
        with_answers = args.answers and generation_error is None
        try:
            judge_llm = container.llm if args.judge and with_answers else None
            rows.append(evaluate_question(container, record, question, with_answers, args.oracle_filter, judge_llm))
        except GenerationError as exc:
            generation_error = str(exc)
            print(f"generation stopped: {generation_error}")
            rows.append(evaluate_question(container, record, question, False, args.oracle_filter))
        scores = rows[-1]["retrieval"]
        print(f"[{index}/{len(questions)}] {question.id} hit@5={scores['hit_at_5']:.0f}" if scores else question.id)
        if with_answers and args.delay:
            time.sleep(args.delay)
    payload = {
        "config": args.config,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "split": args.split,
        "question_count": len(rows),
        "with_answers": args.answers,
        "answered_count": sum("citation_scores" in row for row in rows),
        "generation_error": generation_error,
        "settings": describe_settings(settings, record),
        "metrics": aggregate(rows),
        "by_category": by_category(rows),
        "questions": rows,
    }
    path = save_results(payload, args.results_dir)
    print(json.dumps(payload["metrics"], indent=1))
    print(f"saved {path}")
    return path


def describe_settings(settings: Settings, record: RepoRecord) -> dict[str, Any]:
    return {
        "chunker": settings.chunker,
        "retrieval_mode": settings.retrieval_mode,
        "rerank": settings.rerank,
        "rerank_candidates": settings.rerank_candidates,
        "rerank_fusion": settings.rerank_fusion,
        "overview": settings.overview,
        "routing": settings.routing,
        "routing_llm": settings.routing_llm,
        "followup_rewrite": settings.followup_rewrite,
        "query_expansion": settings.query_expansion,
        "expansion_original_weight": settings.expansion_original_weight,
        "expansion_skip_above": settings.expansion_skip_above,
        "parent_context": settings.parent_context,
        "call_context": settings.call_context,
        "self_check": settings.self_check,
        "hygiene": settings.hygiene,
        "downweight_factor": settings.downweight_factor,
        "downweight_tests": settings.downweight_tests,
        "reranker_model": settings.reranker_model if settings.rerank else None,
        "top_k": settings.top_k,
        "embedding_model": settings.embedding_model,
        "llm": settings.gemini_model,
        "repo_commit": record.commit_sha,
    }


def settings_overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {
        "chunker": args.chunker,
        "retrieval_mode": args.mode,
        "rerank": args.rerank or args.rerank_fusion,
        "rerank_fusion": args.rerank_fusion,
        "llm_cache": True,
        "routing": not args.no_routing,
    }
    if args.llm_model:
        overrides["gemini_model"] = args.llm_model
    for assignment in args.set:
        key, _, value = assignment.partition("=")
        overrides[key.strip()] = value.strip()
    return overrides


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the retrieval/answer evaluation")
    parser.add_argument("--config", required=True, help="name recorded with the results")
    parser.add_argument("--chunker", default="fixed")
    parser.add_argument("--mode", default="vector", choices=["vector", "bm25", "hybrid"])
    parser.add_argument("--rerank", action="store_true", help="rerank the top 30 candidates with a cross-encoder")
    parser.add_argument("--rerank-fusion", action="store_true", help="fuse reranker and first-stage ranks with RRF")
    parser.add_argument("--split", default="dev", choices=["dev", "held_out", "all"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--answers", action="store_true", help="also generate answers and score citations")
    parser.add_argument("--delay", type=float, default=0.0, help="seconds between LLM calls")
    parser.add_argument("--llm-model", default=None, help="override GEMINI_MODEL for this run")
    parser.add_argument("--no-routing", action="store_true", help="send every question down the code path")
    parser.add_argument("--judge", action="store_true", help="grade answers with the LLM judge (needs --answers)")
    parser.add_argument("--oracle-filter", action="store_true", help="restrict each question to its answer's folder")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override any setting")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
