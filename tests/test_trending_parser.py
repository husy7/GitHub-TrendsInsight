"""Parser tests using the offline fixtures only (AGENTS.md §10)."""

from __future__ import annotations

import httpx
import pytest
import respx

from trends.collector.trending_page import (
    build_trending_url,
    fetch_trending_html,
    parse_number,
    parse_trending_html,
)

EXPECTED_DAILY_REPOS = [
    "openai/whisper",
    "langchain-ai/langchain",
    "microsoft/PowerToys",
    "astral-sh/uv",
]


def test_build_trending_url_without_language() -> None:
    assert build_trending_url("daily") == "https://github.com/trending?since=daily"


def test_build_trending_url_with_language_and_spoken_code() -> None:
    url = build_trending_url("weekly", "python", "zh")
    assert url.startswith("https://github.com/trending/python?")
    assert "since=weekly" in url
    assert "spoken_language_code=zh" in url


def test_build_trending_url_quotes_special_language() -> None:
    assert "c%2B%2B" in build_trending_url("daily", "c++")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,234", 1234),
        ("12", 12),
        ("1.2k", 1200),
        ("45.6k", 45_600),
        ("3M", 3_000_000),
        ("1,234 stars today", 1234),
        ("0 stars today", 0),
        ("", None),
        ("  ", None),
        ("no digits here", None),
        (None, None),
    ],
)
def test_parse_number(text: str | None, expected: int | None) -> None:
    assert parse_number(text) == expected


def test_parse_daily_fixture(trending_daily_html: str) -> None:
    entries = parse_trending_html(trending_daily_html, period="daily")
    assert [entry.repo_full_name for entry in entries] == EXPECTED_DAILY_REPOS
    # 无仓库链接的卡片被跳过, 但 rank 仍保持页面真实位置。
    assert [entry.rank for entry in entries] == [1, 2, 3, 4]

    first = entries[0]
    assert first.url == "https://github.com/openai/whisper"
    assert first.stars == 12_345
    assert first.forks == 1_234
    assert first.stars_today == 1_234
    assert first.language == "python"
    assert first.description == "Robust Speech Recognition via Large-Scale Weak Supervision"


def test_parse_daily_fixture_missing_values(trending_daily_html: str) -> None:
    entries = {
        entry.repo_full_name: entry
        for entry in parse_trending_html(trending_daily_html, period="daily")
    }
    assert entries["microsoft/PowerToys"].description is None
    assert entries["astral-sh/uv"].language is None
    assert entries["langchain-ai/langchain"].stars == 45_600
    assert entries["langchain-ai/langchain"].forks == 2_100


def test_parse_python_fixture(trending_python_html: str) -> None:
    entries = parse_trending_html(trending_python_html, period="weekly", language="python")
    assert [entry.repo_full_name for entry in entries] == [
        "psf/requests",
        "pandas-dev/pandas",
        "numpy/numpy",
    ]
    assert entries[0].stars_today == 0
    assert entries[1].description is None
    assert entries[2].language is None
    assert entries[2].stars_today is None


def test_parse_html_without_cards_returns_empty_list() -> None:
    assert parse_trending_html("<html><body></body></html>", period="daily") == []


@respx.mock
def test_fetch_trending_html_uses_expected_url(trending_daily_html: str) -> None:
    route = respx.get("https://github.com/trending?since=daily").mock(
        return_value=httpx.Response(200, text=trending_daily_html)
    )
    with httpx.Client() as client:
        html = fetch_trending_html(client, period="daily")
    assert route.called
    assert "openai/whisper" in html


@respx.mock
def test_fetch_trending_html_retries_5xx(trending_daily_html: str) -> None:
    sleeps: list[float] = []
    respx.get("https://github.com/trending?since=daily").mock(
        side_effect=[
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, text=trending_daily_html),
        ]
    )
    with httpx.Client() as client:
        html = fetch_trending_html(
            client, period="daily", sleep=sleeps.append, jitter=0.0, max_retries=1
        )
    assert "openai/whisper" in html
    assert sleeps == [2.0]


@respx.mock
def test_fetch_trending_html_retries_transport_error(trending_daily_html: str) -> None:
    sleeps: list[float] = []
    respx.get("https://github.com/trending?since=daily").mock(
        side_effect=[
            httpx.ConnectError("connection reset"),
            httpx.Response(200, text=trending_daily_html),
        ]
    )
    with httpx.Client() as client:
        html = fetch_trending_html(
            client, period="daily", sleep=sleeps.append, jitter=0.0, max_retries=1
        )
    assert "openai/whisper" in html
    assert sleeps == [2.0]


@respx.mock
def test_fetch_trending_html_raises_after_retries_exhausted() -> None:
    respx.get("https://github.com/trending?since=daily").mock(
        return_value=httpx.Response(502, text="bad gateway")
    )
    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        fetch_trending_html(
            client, period="daily", sleep=lambda _seconds: None, jitter=0.0, max_retries=1
        )


@respx.mock
def test_fetch_trending_html_raises_client_error_without_retry() -> None:
    route = respx.get("https://github.com/trending?since=daily").mock(
        return_value=httpx.Response(404, text="not found")
    )
    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        fetch_trending_html(client, period="daily", sleep=lambda _seconds: None, jitter=0.0)
    assert route.call_count == 1
