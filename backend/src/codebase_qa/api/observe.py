import logging
import time

from codebase_qa.container import Container
from codebase_qa.generation.llm import GenerationError
from codebase_qa.generation.streaming import Delta
from codebase_qa.indexing.registry import RepoRecord
from codebase_qa.observability.store import QuestionLog
from codebase_qa.observability.usage import CURRENT_METER, UsageMeter
from codebase_qa.qa import AskResult
from codebase_qa.retrieval.filters import SearchFilter
from codebase_qa.routing.followup import Turn

logger = logging.getLogger("codebase_qa.api")


def observed_ask(
    services: Container,
    record: RepoRecord,
    question: str,
    history: list[Turn],
    search_filter: SearchFilter,
    on_delta: Delta | None = None,
) -> AskResult:
    meter = UsageMeter()
    token = CURRENT_METER.set(meter)
    started = time.perf_counter()
    try:
        result = services.pipeline(record, search_filter).ask(question, history, on_delta)
    except GenerationError as exc:
        total_ms = (time.perf_counter() - started) * 1000
        log = usage_log(services, record, meter, total_ms, route="error", error=type(exc).__name__)
        services.stats.record(log)
        raise
    finally:
        CURRENT_METER.reset(token)
    total_ms = (time.perf_counter() - started) * 1000
    log = usage_log(services, record, meter, total_ms, result=result)
    services.stats.record(log)
    logger.info(
        "answered",
        extra={
            "repo_id": record.repo_id,
            "route": result.route,
            "refused": result.refused,
            "confidence": result.confidence.level,
            "total_ms": round(total_ms, 1),
            "stages_ms": {stage: round(ms, 1) for stage, ms in result.timings_ms.items()},
            "llm_calls": meter.calls,
            "input_tokens": meter.input_tokens,
            "output_tokens": meter.output_tokens,
            "cost_usd": log.cost_usd,
        },
    )
    return result


def usage_log(
    services: Container,
    record: RepoRecord,
    meter: UsageMeter,
    total_ms: float,
    result: AskResult | None = None,
    route: str = "",
    error: str | None = None,
) -> QuestionLog:
    return QuestionLog(
        repo_id=record.repo_id,
        route=result.route if result else route,
        refused=result.refused if result else False,
        confidence=result.confidence.level if result else "none",
        total_ms=total_ms,
        stages=result.timings_ms if result else {},
        llm_calls=meter.calls,
        cached_calls=meter.cached_calls,
        input_tokens=meter.input_tokens,
        output_tokens=meter.output_tokens,
        cost_usd=round(meter.cost(services.pricing), 8),
        error=error,
    )
