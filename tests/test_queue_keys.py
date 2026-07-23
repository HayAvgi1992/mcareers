"""Unit tests for Redis priority score helper."""

from datetime import UTC, datetime

from app.queue.keys import priority_score


def test_higher_priority_sorts_before_lower() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    high = priority_score(10, created)
    low = priority_score(1, created)
    assert high < low


def test_same_priority_is_fifo_by_created_at() -> None:
    earlier = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 1, 2, tzinfo=UTC)
    assert priority_score(0, earlier) < priority_score(0, later)


def test_priority_score_formula() -> None:
    created = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    epoch_ms = int(created.timestamp() * 1000)
    assert priority_score(2, created) == (-2 * 10**12) + epoch_ms
