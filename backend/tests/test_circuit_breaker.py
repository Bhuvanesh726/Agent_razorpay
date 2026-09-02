import time

from app.llm.circuit_breaker import CircuitBreaker


def test_closed_by_default():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=10)
    assert cb.is_open() is False


def test_opens_after_threshold_consecutive_failures():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=10)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open() is False  # 2 failures, threshold is 3
    cb.record_failure()
    assert cb.is_open() is True


def test_success_resets_the_failure_count():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=10)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.consecutive_failures == 0
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open() is False  # only 2 since the reset


def test_closes_again_after_cooldown_elapses():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    cb.record_failure()
    assert cb.is_open() is True
    time.sleep(0.08)
    assert cb.is_open() is False  # cooldown elapsed -> half-open


def test_a_failure_during_cooldown_reopens_for_a_fresh_window():
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.1)
    cb.record_failure()
    time.sleep(0.12)
    assert cb.is_open() is False
    cb.record_failure()  # the half-open attempt also failed
    assert cb.is_open() is True
