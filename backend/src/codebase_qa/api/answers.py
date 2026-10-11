import time
import uuid

from codebase_qa.api.observe import observed_ask
from codebase_qa.api.schemas import AskRequest, AskResponse
from codebase_qa.caching.answers import answer_key
from codebase_qa.container import Container
from codebase_qa.feedback.store import AnswerRecord
from codebase_qa.generation.streaming import Delta
from codebase_qa.indexing.registry import RepoRecord
from codebase_qa.observability.store import QuestionLog


def cache_key(services: Container, record: RepoRecord, body: AskRequest) -> str | None:
    if not services.settings.answer_cache or body.history:
        return None
    scope = body.filters.model_dump()
    return answer_key(record.repo_id, record.commit_sha, body.question, scope, services.settings.answer_fingerprint)


def cached_answer(services: Container, record: RepoRecord, key: str, on_delta: Delta | None) -> AskResponse | None:
    started = time.perf_counter()
    payload = services.answer_cache.get(key)
    if payload is None:
        return None
    elapsed = (time.perf_counter() - started) * 1000
    response = AskResponse.model_validate(payload | {"timings_ms": {"answer_cache": elapsed}, "cached": True})
    services.stats.record(
        QuestionLog(
            repo_id=record.repo_id,
            route=response.route,
            refused=response.refused,
            confidence=response.confidence,
            total_ms=elapsed,
            stages={"answer_cache": elapsed},
        )
    )
    if on_delta is not None:
        on_delta(response.answer)
    return response


def answer_request(
    services: Container, record: RepoRecord, body: AskRequest, on_delta: Delta | None = None
) -> AskResponse:
    key = cache_key(services, record, body)
    response = cached_answer(services, record, key, on_delta) if key is not None else None
    if response is None:
        result = observed_ask(services, record, body.question, body.turns(), body.filters.to_filter(), on_delta)
        response = AskResponse.from_result(result, record.commit_sha)
        if key is not None and not response.degraded:
            services.answer_cache.put(key, record.repo_id, record.commit_sha, response.model_dump())
    return remember(services, record, body.question, response)


def remember(services: Container, record: RepoRecord, question: str, response: AskResponse) -> AskResponse:
    answer_id = uuid.uuid4().hex
    services.recent_answers.remember(
        AnswerRecord(
            answer_id=answer_id,
            repo_id=record.repo_id,
            commit_sha=record.commit_sha,
            question=question,
            answer=response.answer,
            route=response.route,
            confidence=response.confidence,
            citations=[f"{c.path}:{c.start_line}-{c.end_line}" for c in response.citations],
            retrieved=[
                {"location": f"{c.path}:{c.start_line}-{c.end_line}", "score": round(c.score, 4)}
                for c in response.context
            ],
        )
    )
    return response.model_copy(update={"answer_id": answer_id})
