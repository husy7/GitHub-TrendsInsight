"""Settings, language normalization and UTC helpers (AGENTS.md §6)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from trends.config import Settings, get_settings, normalize_language, utc_snapshot_date


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Python", "python"),
        ("  C++  ", "c++"),
        ("CSharp", "c#"),
        ("Objective C", "objective-c"),
        ("Jupyter-Notebook", "jupyter notebook"),
        ("Bash", "shell"),
        ("Unknown", ""),
        ("", ""),
        ("   ", ""),
        (None, ""),
        ("Rust", "rust"),
    ],
)
def test_normalize_language(value: str | None, expected: str) -> None:
    assert normalize_language(value) == expected


def test_utc_snapshot_date_uses_utc() -> None:
    assert utc_snapshot_date(datetime(2026, 9, 29, 23, 30, tzinfo=UTC)) == "2026-09-29"


def test_utc_snapshot_date_converts_other_timezones() -> None:
    shanghai = timezone(timedelta(hours=8))
    assert utc_snapshot_date(datetime(2026, 9, 30, 7, 0, tzinfo=shanghai)) == "2026-09-29"


def test_utc_snapshot_date_matches_iso_format() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", utc_snapshot_date())


def test_settings_defaults_match_agents_md() -> None:
    settings = Settings(_env_file=None)
    assert settings.trending_period == "daily"
    assert settings.trending_language == ""
    assert settings.http_timeout == 15.0
    assert settings.max_retries == 5
    assert settings.base_delay == 2.0
    assert settings.max_delay == 60.0
    assert settings.database_url.endswith("data/trends.db")


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_RETRIES", "9")
    monkeypatch.setenv("TRENDING_PERIOD", "weekly")
    monkeypatch.setenv("TRENDING_LANGUAGE", "python")
    settings = Settings(_env_file=None)
    assert settings.max_retries == 9
    assert settings.trending_period == "weekly"
    assert settings.trending_language == "python"


def test_settings_reject_unknown_period() -> None:
    with pytest.raises(ValueError, match="trending_period"):
        Settings(_env_file=None, trending_period="yearly")  # type: ignore[arg-type]


def test_github_headers_follow_agents_md() -> None:
    headers = Settings(_env_file=None, github_token="abc123").github_headers
    assert headers == {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer abc123",
        "User-Agent": "github-trends-insight",
    }


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
