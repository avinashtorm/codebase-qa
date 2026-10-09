import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def timed(timings: dict[str, float], stage: str, action: Callable[[], T]) -> T:
    started = time.perf_counter()
    result = action()
    timings[stage] = round(timings.get(stage, 0.0) + (time.perf_counter() - started) * 1000, 1)
    return result
