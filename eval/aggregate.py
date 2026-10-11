from typing import Any

from eval.metrics import average

Row = dict[str, Any]
RETRIEVAL_KEYS = ("hit_at_1", "hit_at_5", "recall_at_10", "mrr")


def retrieval_metrics(rows: list[Row]) -> dict[str, float]:
    scored = [row for row in rows if row.get("retrieval")]
    if not scored:
        return {}
    return {name: average([row["retrieval"][name] for row in scored]) for name in RETRIEVAL_KEYS}


def citation_metrics(answered: list[Row]) -> dict[str, float]:
    scored = [row for row in answered if row.get("citation_scores")]
    metrics: dict[str, float] = {"invalid_citations": sum(row["invalid_citations"] for row in answered)}
    if scored:
        metrics["citation_precision"] = average([row["citation_scores"]["precision"] for row in scored])
        metrics["citation_any_correct"] = average([row["citation_scores"]["any_correct"] for row in scored])
    return metrics


def refusal_metrics(answered: list[Row]) -> dict[str, float]:
    metrics: dict[str, float] = {"refused": sum(bool(row.get("declined")) for row in answered)}
    answerable = [row for row in answered if row["category"] != "unanswerable"]
    unanswerable = [row for row in answered if row["category"] == "unanswerable"]
    correct = [bool(row.get("declined")) == (row["category"] == "unanswerable") for row in answered]
    metrics["refusal_accuracy"] = average([float(value) for value in correct])
    if answerable:
        metrics["answered_when_answerable"] = average([float(not row.get("declined")) for row in answerable])
    if unanswerable:
        metrics["refused_when_unanswerable"] = average([float(bool(row.get("declined"))) for row in unanswerable])
    return metrics


def judge_metrics(answered: list[Row]) -> dict[str, float]:
    judged = [row for row in answered if row.get("judge")]
    if not judged:
        return {}
    given = [row["judge"] for row in judged if not row.get("declined")]
    answerable = [row["judge"] for row in judged if row["category"] != "unanswerable"]
    metrics: dict[str, float] = {"judged": len(judged)}
    if given:
        metrics["faithfulness_mean"] = average([verdict["faithfulness"] for verdict in given])
        metrics["faithful_rate"] = average([float(verdict["faithfulness"] >= 4) for verdict in given])
    if answerable:
        metrics["relevance_mean"] = average([verdict["relevance"] for verdict in answerable])
        metrics["relevant_rate"] = average([float(verdict["relevance"] >= 4) for verdict in answerable])
    return metrics


def confidence_metrics(answered: list[Row]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for level in ("high", "medium", "low"):
        bucket = [row for row in answered if row.get("confidence") == level]
        metrics[f"confidence_{level}"] = len(bucket)
        scored = [row["citation_scores"]["any_correct"] for row in bucket if row.get("citation_scores")]
        if scored:
            metrics[f"confidence_{level}_correct"] = average(scored)
    return metrics


def self_check_metrics(answered: list[Row]) -> dict[str, float]:
    checked = [row["self_check"] for row in answered if row.get("self_check", {}).get("ran")]
    if not checked:
        return {}
    claims = sum(check["supported"] + len(check["unsupported"]) for check in checked)
    unsupported = sum(len(check["unsupported"]) for check in checked)
    return {
        "self_checked": len(checked),
        "answers_with_unsupported": sum(bool(check["unsupported"]) for check in checked),
        "unsupported_claim_rate": round(unsupported / max(claims, 1), 4),
    }


def latency_metrics(rows: list[Row]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for stage in sorted({stage for row in rows for stage in row["latency_ms"]}):
        values = [row["latency_ms"][stage] for row in rows if stage in row["latency_ms"]]
        metrics[f"{stage}_ms_mean"] = round(sum(values) / len(values), 1)
    return metrics


def aggregate(rows: list[Row]) -> dict[str, float]:
    metrics = retrieval_metrics(rows)
    answered = [row for row in rows if "answer" in row]
    if answered:
        for part in (citation_metrics, refusal_metrics, judge_metrics, confidence_metrics, self_check_metrics):
            metrics |= part(answered)
    for route in ("code", "overview", "tool"):
        metrics[f"route_{route}"] = sum(row.get("route") == route for row in rows)
    return metrics | latency_metrics(rows)


def by_category(rows: list[Row]) -> dict[str, dict[str, float]]:
    categories = sorted({row["category"] for row in rows})
    return {
        category: {"count": sum(row["category"] == category for row in rows)}
        | aggregate([row for row in rows if row["category"] == category])
        for category in categories
    }
