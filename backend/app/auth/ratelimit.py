"""In-process sliding-window failure counter for login and reset requests.

Correct for a single worker (Render runs one uvicorn worker); a multi-worker
deployment would move this to the database or a shared cache.
"""

import time
from collections import defaultdict, deque

MAX_FAILURES = 10
WINDOW_SECONDS = 15 * 60


class FailureLimiter:
    def __init__(self, max_failures: int = MAX_FAILURES, window_seconds: int = WINDOW_SECONDS):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._hits[key]
        while q and q[0] < now - self.window_seconds:
            q.popleft()
        return q

    def allowed(self, key: str) -> bool:
        return len(self._prune(key, time.monotonic())) < self.max_failures

    def hit(self, key: str) -> None:
        self._prune(key, time.monotonic()).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()


login_limiter = FailureLimiter()
reset_limiter = FailureLimiter(max_failures=5)
