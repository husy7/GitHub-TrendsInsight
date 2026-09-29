"""Rate-limit and backoff tests (AGENTS.md §7.3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import formatdate

import pytest

from trends.collector.rate_limit import (
    RateLimitInfo,
    RateLimitTracker,
    compute_backoff_seconds,
    is_retryable_status,
    parse_rate_limit,
    parse_retry_after,
    resolve_delay_seconds,
)


def test_parse_rate_limit_reads_headers_case_insensitively() -> None:
    info = parse_rate_limit(
        {
            "X-RateLimit-Remaining": "42",
            "x-ratelimit-reset": "1790000000",
            "Retry-After": "5",
        }
    )
    assert info == RateLimitInfo(remaining=42, reset=1_790_000_000, retry_after=5.0)


def test_parse_rate_limit_without_headers_is_empty() -> None:
    assert parse_rate_limit({}) == RateLimitInfo()
    assert parse_rate_limit({"X-RateLimit-Remaining": "abc"}).remaining is None


def test_parse_retry_after_accepts_http_date() -> None:
    moment = datetime.now(tz=UTC) + timedelta(seconds=30)
    header = formatdate(timeval=moment.timestamp(), usegmt=True)
    parsed = parse_retry_after(header)
    assert parsed is not None
    assert 20.0 <= parsed <= 31.0


@pytest.mark.parametrize("value", [None, "", "   ", "not-a-date"])
def test_parse_retry_after_invalid_values(value: str | None) -> None:
    assert parse_retry_after(value) is None


def test_parse_retry_after_clamps_negative() -> None:
    assert parse_retry_after("-5") == 0.0


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(0, 2.0), (1, 4.0), (2, 8.0), (4, 32.0), (5, 60.0), (9, 60.0)],
)
def test_compute_backoff_seconds(attempt: int, expected: float) -> None:
    assert compute_backoff_seconds(attempt, jitter=0.0) == expected


def test_compute_backoff_seconds_adds_jitter_within_one_second() -> None:
    for _ in range(5):
        assert 2.0 <= compute_backoff_seconds(0) <= 3.0


def test_resolve_delay_seconds_prefers_retry_after() -> None:
    assert resolve_delay_seconds({"Retry-After": "3"}, 0, jitter=0.0) == 3.0


def test_resolve_delay_seconds_clamps_retry_after_to_max_delay() -> None:
    assert resolve_delay_seconds({"Retry-After": "600"}, 0, jitter=0.0) == 60.0


def test_resolve_delay_seconds_falls_back_to_backoff() -> None:
    assert resolve_delay_seconds({}, 2, base_delay=2.0, max_delay=60.0, jitter=0.0) == 8.0


@pytest.mark.parametrize("status", [403, 429, 500, 502, 599])
def test_is_retryable_status_true(status: int) -> None:
    assert is_retryable_status(status)


@pytest.mark.parametrize("status", [200, 201, 301, 400, 401, 404, 422])
def test_is_retryable_status_false(status: int) -> None:
    assert not is_retryable_status(status)


def test_rate_limit_tracker_counts_requests_and_throttling() -> None:
    tracker = RateLimitTracker()
    tracker.update({"X-RateLimit-Remaining": "10"})
    tracker.update({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "1790000000"})
    assert tracker.requests == 2
    assert tracker.throttled == 1
    assert tracker.latest.remaining == 1
