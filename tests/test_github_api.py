"""GitHub API client tests. All requests are mocked with `respx`."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx

from trends.collector.github_api import GitHubApiClient, parse_repo_payload
from trends.collector.rate_limit import MissingTokenError
from trends.storage.models import FailedRepo

REPO_API_URL = "https://api.github.com/repos/astral-sh/uv"
REPO_FULL_NAME = "astral-sh/uv"
SNAPSHOT_DATE = "2026-09-29"


@pytest.fixture
def api_client() -> Iterator[GitHubApiClient]:
    client = GitHubApiClient("test-token", jitter=0.0, sleep=lambda _seconds: None)
    yield client
    client.close()


def test_missing_token_raises() -> None:
    with pytest.raises(MissingTokenError):
        GitHubApiClient("   ")


@respx.mock
def test_get_repo_success(api_client: GitHubApiClient, repo_api_payload: dict[str, object]) -> None:
    route = respx.get(REPO_API_URL).mock(return_value=httpx.Response(200, json=repo_api_payload))
    details = api_client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE)

    assert details is not None
    assert details.repo_full_name == REPO_FULL_NAME
    assert details.stars == 101_234
    assert details.forks == 8_901
    assert details.open_issues == 1_204
    assert details.language == "rust"
    assert details.topics == ("packaging", "python", "resolver", "uv")
    assert details.topics_json == '["packaging", "python", "resolver", "uv"]'
    assert details.url == "https://github.com/astral-sh/uv"
    assert api_client.failed_repos == []

    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert request.headers["User-Agent"] == "github-trends-insight"


@respx.mock
def test_get_repo_deduplicates_requests(
    api_client: GitHubApiClient, repo_api_payload: dict[str, object]
) -> None:
    route = respx.get(REPO_API_URL).mock(return_value=httpx.Response(200, json=repo_api_payload))
    first = api_client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE)
    second = api_client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE)
    assert first == second
    assert route.call_count == 1


@respx.mock
def test_get_repo_404_records_failure_without_retry(api_client: GitHubApiClient) -> None:
    route = respx.get(REPO_API_URL).mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    assert api_client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE) is None
    assert route.call_count == 1
    assert api_client.failed_repos == [
        FailedRepo(
            repo_full_name=REPO_FULL_NAME,
            snapshot_date=SNAPSHOT_DATE,
            reason="not_found",
            status_code=404,
        )
    ]


@respx.mock
def test_get_repo_retries_5xx_then_succeeds(repo_api_payload: dict[str, object]) -> None:
    sleeps: list[float] = []
    client = GitHubApiClient("test-token", max_retries=3, sleep=sleeps.append, jitter=0.0)
    respx.get(REPO_API_URL).mock(
        side_effect=[
            httpx.Response(500, json={"message": "boom"}),
            httpx.Response(503, json={"message": "boom"}),
            httpx.Response(200, json=repo_api_payload),
        ]
    )
    assert client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE) is not None
    assert sleeps == [2.0, 4.0]
    assert client.failed_repos == []
    client.close()


@respx.mock
def test_get_repo_prefers_retry_after_header(repo_api_payload: dict[str, object]) -> None:
    sleeps: list[float] = []
    client = GitHubApiClient("test-token", max_retries=2, sleep=sleeps.append, jitter=0.0)
    respx.get(REPO_API_URL).mock(
        side_effect=[
            httpx.Response(403, headers={"Retry-After": "1"}, json={"message": "limited"}),
            httpx.Response(200, json=repo_api_payload),
        ]
    )
    assert client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE) is not None
    assert sleeps == [1.0]
    client.close()


@respx.mock
def test_get_repo_records_failure_after_retry_exhausted() -> None:
    sleeps: list[float] = []
    client = GitHubApiClient("test-token", max_retries=2, sleep=sleeps.append, jitter=0.0)
    route = respx.get(REPO_API_URL).mock(
        return_value=httpx.Response(502, json={"message": "bad gateway"})
    )
    assert client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE) is None
    assert route.call_count == 3
    assert sleeps == [2.0, 4.0]
    assert client.failed_repos[0].reason == "retry_exhausted"
    assert client.failed_repos[0].status_code == 502
    client.close()


@respx.mock
def test_get_repo_non_retryable_status(api_client: GitHubApiClient) -> None:
    route = respx.get(REPO_API_URL).mock(
        return_value=httpx.Response(401, json={"message": "bad credentials"})
    )
    assert api_client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE) is None
    assert route.call_count == 1
    assert api_client.failed_repos[0].reason == "http_error"
    assert api_client.failed_repos[0].status_code == 401


@respx.mock
def test_get_repo_invalid_json_records_failure(api_client: GitHubApiClient) -> None:
    respx.get(REPO_API_URL).mock(return_value=httpx.Response(200, text="<html>nope</html>"))
    assert api_client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE) is None
    assert api_client.failed_repos[0].reason == "invalid_json"


@respx.mock
def test_get_repo_unexpected_payload_records_failure(api_client: GitHubApiClient) -> None:
    respx.get(REPO_API_URL).mock(return_value=httpx.Response(200, json=[1, 2, 3]))
    assert api_client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE) is None
    assert api_client.failed_repos[0].reason == "unexpected_payload"


@respx.mock
def test_get_repo_keeps_raw_payload(
    api_client: GitHubApiClient, repo_api_payload: dict[str, object]
) -> None:
    respx.get(REPO_API_URL).mock(return_value=httpx.Response(200, json=repo_api_payload))
    api_client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE)
    payload = api_client.raw_payload(REPO_FULL_NAME)
    assert payload is not None
    assert b"astral-sh/uv" in payload
    assert api_client.raw_payload("other/repo") is None


@respx.mock
def test_rate_limit_headers_are_tracked(
    api_client: GitHubApiClient, repo_api_payload: dict[str, object]
) -> None:
    respx.get(REPO_API_URL).mock(
        return_value=httpx.Response(
            200,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1790000000"},
            json=repo_api_payload,
        )
    )
    api_client.get_repo(REPO_FULL_NAME, snapshot_date=SNAPSHOT_DATE)
    assert api_client.rate_limit.latest.remaining == 0
    assert api_client.rate_limit.latest.reset == 1_790_000_000
    assert api_client.rate_limit.throttled == 1


def test_close_does_not_close_injected_client() -> None:
    outer = httpx.Client()
    client = GitHubApiClient("test-token", client=outer)
    client.close()
    assert not outer.is_closed
    outer.close()


def test_context_manager_closes_owned_client() -> None:
    with GitHubApiClient("test-token") as client:
        owned = client._client
        assert not owned.is_closed
    assert owned.is_closed


def test_parse_repo_payload_handles_missing_fields() -> None:
    details = parse_repo_payload({"full_name": "a/b"}, "a/b")
    assert details.stars is None
    assert details.forks is None
    assert details.open_issues is None
    assert details.language is None
    assert details.description is None
    assert details.topics == ()
    assert details.url == "https://github.com/a/b"
