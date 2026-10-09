import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "succeeded", "failed"]
Progress = Callable[[str], None]
JobAction = Callable[[Progress], dict[str, Any]]


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Job:
    job_id: str
    kind: str
    repo_id: str
    status: JobStatus = "queued"
    progress: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=now_iso)
    finished_at: str | None = None


class JobManager:
    def __init__(self, max_history: int = 200) -> None:
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="indexer")
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.max_history = max_history

    def submit(self, kind: str, repo_id: str, action: JobAction) -> Job:
        job = Job(job_id=uuid.uuid4().hex, kind=kind, repo_id=repo_id)
        with self.lock:
            self.jobs[job.job_id] = job
            self.trim()
        self.executor.submit(self.run, job, action)
        return job

    def run(self, job: Job, action: JobAction) -> None:
        job.status = "running"

        def report(message: str) -> None:
            job.progress = message

        try:
            job.result = action(report)
            job.status = "succeeded"
            job.progress = "done"
        except Exception as exc:
            logger.exception("job failed", extra={"job_id": job.job_id, "kind": job.kind})
            job.status = "failed"
            job.error = str(exc) if isinstance(exc, ValueError | RuntimeError) else "internal error"
            job.progress = "failed"
        finally:
            job.finished_at = now_iso()

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def active_for(self, repo_id: str) -> Job | None:
        return next(
            (job for job in self.jobs.values() if job.repo_id == repo_id and job.status in ("queued", "running")),
            None,
        )

    def running_count(self) -> int:
        return sum(job.status in ("queued", "running") for job in self.jobs.values())

    def trim(self) -> None:
        finished = [job for job in self.jobs.values() if job.status in ("succeeded", "failed")]
        for job in finished[: max(0, len(self.jobs) - self.max_history)]:
            self.jobs.pop(job.job_id, None)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
