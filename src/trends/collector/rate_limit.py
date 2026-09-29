"""Rate-limit bookkeeping and exponential backoff (AGENTS.md §7.3).

默认参数:
- `MAX_RETRIES=5`, `BASE_DELAY=2`, `MAX_DELAY=60`
- `delay = min(BASE_DELAY * 2**attempt, MAX_DELAY)` + 0~1 秒随机抖动
- 403/429 优先读取 `Retry-After`, 5xx 按退避重试
"""

from __future__ import annotations

import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from trends.config import DEFAULT_BASE_DELAY, DEFAULT_MAX_DELAY

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = frozenset({403, 429})


class CollectorError(RuntimeError):
    """Base class for collector failures."""


class MissingTokenError(CollectorError):
    """Raised when `GITHUB_TOKEN` is missing: stop and report, never bypass."""


class RetryExhaustedError(CollectorError):
    """Raised when a request still fails after `MAX_RETRIES` retries."""


@dataclass(frozen=True, slots=True)
class RateLimitInfo:
    """Snapshot of the rate-limit headers returned by GitHub."""

    remaining: int | None = None
    reset: int | None = None
    retry_after: float | None = None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def parse_retry_after(value: str | None) -> float | None:
    """Parse `Retry-After` as delta-seconds or an HTTP-date; `None` if invalid."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return max(float(text), 0.0)
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        logger.warning("unparsable Retry-After header: %r", value)
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max((moment - datetime.now(tz=UTC)).total_seconds(), 0.0)


def parse_rate_limit(headers: Mapping[str, str]) -> RateLimitInfo:
    """Read `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`."""
    normalized = {key.lower(): value for key, value in headers.items()}
    return RateLimitInfo(
        remaining=_to_int(normalized.get("x-ratelimit-remaining")),
        reset=_to_int(normalized.get("x-ratelimit-reset")),
        retry_after=parse_retry_after(normalized.get("retry-after")),
    )


def compute_backoff_seconds(
    attempt: int,
    *,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    jitter: float | None = None,
) -> float:
    """Return `min(base_delay * 2**attempt, max_delay)` plus 0~1s jitter."""
    # 底数写成 float: `int ** int` 在 typeshed 中会被推断为 Any。
    delay = min(base_delay * (2.0 ** max(attempt, 0)), max_delay)
    noise = random.uniform(0.0, 1.0) if jitter is None else jitter
    return delay + noise


def resolve_delay_seconds(
    headers: Mapping[str, str],
    attempt: int,
    *,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    jitter: float | None = None,
) -> float:
    """Prefer `Retry-After` for 403/429, otherwise use exponential backoff.

    Every sleep is capped by `max_delay` so a single run can never block for
    hours; clamping is logged so the interruption stays visible.
    """
    retry_after = parse_rate_limit(headers).retry_after
    if retry_after is None:
        return compute_backoff_seconds(
            attempt, base_delay=base_delay, max_delay=max_delay, jitter=jitter
        )
    if retry_after > max_delay:
        logger.warning(
            "Retry-After %.1fs exceeds MAX_DELAY %.1fs, clamping", retry_after, max_delay
        )
    return min(retry_after, max_delay)


def is_retryable_status(status_code: int) -> bool:
    """Return True for 403/429 and 5xx responses."""
    return status_code in RETRYABLE_STATUS_CODES or 500 <= status_code <= 599


class RateLimitTracker:
    """Remember the latest rate-limit headers so runs can log their budget."""

    def __init__(self) -> None:
        self._latest = RateLimitInfo()
        self.requests = 0
        self.throttled = 0

    @property
    def latest(self) -> RateLimitInfo:
        """Most recent `X-RateLimit-*` / `Retry-After` observation."""
        return self._latest

    def update(self, headers: Mapping[str, str]) -> RateLimitInfo:
        """Record one response's headers and warn when the budget runs low."""
        info = parse_rate_limit(headers)
        self.requests += 1
        self._latest = info
        if info.remaining is not None and info.remaining <= 1:
            self.throttled += 1
            logger.warning(
                "rate limit almost exhausted: remaining=%s reset=%s",
                info.remaining,
                info.reset,
            )
        return info
