import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self.hits: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    def check(self, key: str) -> float | None:
        now = self.clock()
        with self.lock:
            hits = self.hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return self.window - (now - hits[0])
            hits.append(now)
            return None


def utc_today() -> date:
    return datetime.now(UTC).date()


class DailyLimiter:
    def __init__(self, limit: int, today: Callable[[], date] = utc_today) -> None:
        self.limit = limit
        self.today = today
        self.day = today()
        self.count = 0
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            current = self.today()
            if current != self.day:
                self.day, self.count = current, 0
            if self.count >= self.limit:
                return False
            self.count += 1
            return True


def client_ip(request: Request, trust_proxy: bool) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if trust_proxy and forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(limiter: SlidingWindowLimiter, request: Request, trust_proxy: bool) -> None:
    retry_after = limiter.check(client_ip(request, trust_proxy))
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded, try again later",
            headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
        )
