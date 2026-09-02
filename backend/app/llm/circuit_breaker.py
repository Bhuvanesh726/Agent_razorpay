"""A minimal circuit breaker: after `failure_threshold` consecutive
failures, the breaker opens and stays open for `cooldown_seconds` — calls
during that window should fail fast without even attempting the underlying
operation. After the cooldown elapses, the breaker allows one attempt
through (half-open); success closes it, failure reopens it for another full
cooldown.

Deliberately has no knowledge of the LLM, HTTP, or anything else it might
guard — it's just a state machine over pass/fail signals the caller reports.
"""

import time


class CircuitBreaker:
    def __init__(self, failure_threshold: int, cooldown_seconds: float):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown_seconds:
            return False  # cooldown elapsed — half-open, let the next attempt through
        return True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._opened_at = time.monotonic()

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures
