"""GitHub REST API client for repository details (AGENTS.md §7.1, §7.3).

约束:
- 每个请求都带 `Accept` / `X-GitHub-Api-Version` / `Authorization` / `User-Agent`。
- 同一采集任务内同一 `repo_full_name` 只请求一次详情。
- 404 记入 `failed_repos` 并跳过; 403/429/5xx 按 §7.3 退避重试。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx

from trends.collector.rate_limit import (
    MissingTokenError,
    RateLimitTracker,
    is_retryable_status,
    resolve_delay_seconds,
)
from trends.config import (
    DEFAULT_BASE_DELAY,
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_MAX_DELAY,
    DEFAULT_MAX_RETRIES,
    GITHUB_API_BASE_URL,
    GITHUB_API_VERSION,
    USER_AGENT,
    normalize_language,
)
from trends.storage.models import FailedRepo

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RepoDetails:
    """Repository details returned by `GET /repos/{owner}/{repo}`."""

    repo_full_name: str
    url: str
    description: str | None
    language: str | None
    stars: int | None
    forks: int | None
    open_issues: int | None
    topics: tuple[str, ...]

    @property
    def topics_json(self) -> str:
        """`topics_json` payload: a JSON array sorted lexicographically."""
        return json.dumps(sorted(self.topics), ensure_ascii=False)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _topic_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def parse_repo_payload(payload: dict[str, Any], repo_full_name: str) -> RepoDetails:
    """Map a GitHub API payload onto `RepoDetails`.

    GitHub API 的响应键名 (`stargazers_count` / `forks_count` /
    `open_issues_count`) 是外部协议字段, 不属于本项目的字段标识符。
    `language` 在这里统一转成术语表要求的小写标识。
    """
    return RepoDetails(
        repo_full_name=repo_full_name,
        url=_optional_str(payload.get("html_url")) or f"https://github.com/{repo_full_name}",
        description=_optional_str(payload.get("description")),
        language=normalize_language(_optional_str(payload.get("language"))) or None,
        stars=_optional_int(payload.get("stargazers_count")),
        forks=_optional_int(payload.get("forks_count")),
        open_issues=_optional_int(payload.get("open_issues_count")),
        topics=tuple(sorted(_topic_list(payload.get("topics")))),
    )


class GitHubApiClient:
    """Thin, retrying wrapper around the GitHub REST API."""

    def __init__(
        self,
        token: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_HTTP_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        jitter: float | None = None,
    ) -> None:
        if not token.strip():
            raise MissingTokenError(
                "GITHUB_TOKEN is missing: stop and report instead of bypassing the rate limit"
            )
        self._token = token
        self._max_retries = max(max_retries, 0)
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._sleep = sleep
        self._jitter = jitter
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._cache: dict[str, RepoDetails | None] = {}
        self._failed: dict[str, FailedRepo] = {}
        self._raw_payloads: dict[str, bytes] = {}
        self.rate_limit = RateLimitTracker()

    @property
    def headers(self) -> dict[str, str]:
        """Request headers mandated by AGENTS.md §7.1."""
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "Authorization": f"Bearer {self._token}",
            "User-Agent": USER_AGENT,
        }

    @property
    def failed_repos(self) -> list[FailedRepo]:
        """Repositories that failed during this task, deduplicated."""
        return list(self._failed.values())

    def get_repo(self, repo_full_name: str, *, snapshot_date: str) -> RepoDetails | None:
        """Fetch one repository, returning `None` when it cannot be collected."""
        if repo_full_name in self._cache:
            return self._cache[repo_full_name]
        details = self._request_repo(repo_full_name, snapshot_date=snapshot_date)
        self._cache[repo_full_name] = details
        return details

    def raw_payload(self, repo_full_name: str) -> bytes | None:
        """Raw response body of the last successful request, for `data/raw/`."""
        return self._raw_payloads.get(repo_full_name)

    def _request_repo(self, repo_full_name: str, *, snapshot_date: str) -> RepoDetails | None:
        url = f"{GITHUB_API_BASE_URL}/repos/{repo_full_name}"
        attempt = 0
        while True:
            response = self._client.get(url, headers=self.headers)
            info = self.rate_limit.update(response.headers)
            status_code = response.status_code
            if status_code == 200:
                logger.debug("fetched %s (rate limit remaining=%s)", repo_full_name, info.remaining)
                self._raw_payloads[repo_full_name] = response.content
                return self._details_from_response(response, repo_full_name, snapshot_date)
            if status_code == 404:
                # 404 不重试, 直接记录到 failed_repos。
                self._record_failure(repo_full_name, snapshot_date, "not_found", status_code)
                return None
            if not is_retryable_status(status_code) or attempt >= self._max_retries:
                reason = "retry_exhausted" if is_retryable_status(status_code) else "http_error"
                self._record_failure(repo_full_name, snapshot_date, reason, status_code)
                logger.error(
                    "giving up on %s after %d retries (status=%s)",
                    repo_full_name,
                    attempt,
                    status_code,
                )
                return None
            delay = resolve_delay_seconds(
                response.headers,
                attempt,
                base_delay=self._base_delay,
                max_delay=self._max_delay,
                jitter=self._jitter,
            )
            logger.warning(
                "retrying %s in %.2fs (status=%s, attempt=%d/%d)",
                repo_full_name,
                delay,
                status_code,
                attempt + 1,
                self._max_retries,
            )
            self._sleep(delay)
            attempt += 1

    def _details_from_response(
        self,
        response: httpx.Response,
        repo_full_name: str,
        snapshot_date: str,
    ) -> RepoDetails | None:
        try:
            payload = response.json()
        except ValueError:
            self._record_failure(
                repo_full_name, snapshot_date, "invalid_json", response.status_code
            )
            return None
        if not isinstance(payload, dict):
            self._record_failure(
                repo_full_name, snapshot_date, "unexpected_payload", response.status_code
            )
            return None
        return parse_repo_payload(payload, repo_full_name)

    def _record_failure(
        self,
        repo_full_name: str,
        snapshot_date: str,
        reason: str,
        status_code: int | None,
    ) -> None:
        self._failed[repo_full_name] = FailedRepo(
            repo_full_name=repo_full_name,
            snapshot_date=snapshot_date,
            reason=reason,
            status_code=status_code,
        )
        logger.warning("failed_repos: %s reason=%s status=%s", repo_full_name, reason, status_code)

    def close(self) -> None:
        """Close the underlying HTTP client when this instance owns it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GitHubApiClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
