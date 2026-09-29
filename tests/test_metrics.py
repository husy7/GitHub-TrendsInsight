"""Metric tests with fixed inputs and fixed expected outputs (AGENTS.md §8.1)."""

from __future__ import annotations

import pandas as pd
import pytest

from trends.analysis.metrics import (
    compute_language_share,
    compute_period_star_velocity,
    compute_rank_momentum,
    compute_star_velocity,
    star_velocity_column,
)

SNAPSHOT_FIELDS = ["repo_full_name", "snapshot_date", "stars"]
TRENDING_FIELDS = ["repo_full_name", "snapshot_date", "rank", "period", "language"]


def snapshot_frame(rows: list[tuple[str, str, int | None]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=SNAPSHOT_FIELDS)


def trending_frame(rows: list[tuple[str, str, int, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=TRENDING_FIELDS)


def test_star_velocity_column_name() -> None:
    assert star_velocity_column(7) == "star_velocity_7d"
    assert star_velocity_column(30) == "star_velocity_30d"


def test_star_velocity_uses_exact_window() -> None:
    frame = snapshot_frame(
        [
            ("a/one", "2026-09-01", 100),
            ("a/one", "2026-09-08", 170),
            ("a/one", "2026-09-15", 240),
        ]
    )
    result = compute_star_velocity(frame, 7)
    assert list(result.columns) == ["repo_full_name", "snapshot_date", "star_velocity_7d"]
    assert result["snapshot_date"].tolist() == ["2026-09-08", "2026-09-15"]
    assert result["star_velocity_7d"].tolist() == [10.0, 10.0]


def test_star_velocity_omits_missing_window() -> None:
    frame = snapshot_frame([("a/one", "2026-09-01", 100), ("a/one", "2026-09-05", 140)])
    result = compute_star_velocity(frame, 7)
    assert result.empty
    assert list(result.columns) == ["repo_full_name", "snapshot_date", "star_velocity_7d"]


def test_star_velocity_omits_rows_without_stars() -> None:
    frame = snapshot_frame([("a/one", "2026-09-01", None), ("a/one", "2026-09-08", 170)])
    assert compute_star_velocity(frame, 7).empty


def test_star_velocity_handles_multiple_repos_and_duplicate_rows() -> None:
    frame = snapshot_frame(
        [
            ("a/one", "2026-09-01", 100),
            ("a/one", "2026-09-08", 170),
            ("a/one", "2026-09-01", 100),
            ("b/two", "2026-09-01", 50),
            ("b/two", "2026-09-08", 260),
        ]
    )
    result = compute_star_velocity(frame, 7)
    assert result["repo_full_name"].tolist() == ["a/one", "b/two"]
    assert result["star_velocity_7d"].tolist() == [10.0, 30.0]


def test_star_velocity_empty_input() -> None:
    result = compute_star_velocity(snapshot_frame([]), 7)
    assert result.empty
    assert list(result.columns) == ["repo_full_name", "snapshot_date", "star_velocity_7d"]


def test_star_velocity_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window_days"):
        compute_star_velocity(snapshot_frame([]), 0)


def test_star_velocity_requires_columns() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        compute_star_velocity(pd.DataFrame({"repo_full_name": ["a/b"]}), 7)


def period_trending_frame(rows: list[tuple[str, str, int, str, str, int | None]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=[*TRENDING_FIELDS, "stars_in_period"])


def test_period_star_velocity_divides_increment_by_window() -> None:
    frame = period_trending_frame(
        [
            ("a/one", "2026-09-29", 1, "weekly", "python", 700),
            ("b/two", "2026-09-29", 2, "weekly", "python", 70),
        ]
    )
    result = compute_period_star_velocity(frame, "weekly", 7)
    assert list(result.columns) == ["repo_full_name", "snapshot_date", "star_velocity_7d"]
    assert result["star_velocity_7d"].tolist() == [100.0, 10.0]


def test_period_star_velocity_uses_requested_period_only() -> None:
    frame = period_trending_frame(
        [
            ("a/one", "2026-09-29", 1, "weekly", "python", 700),
            ("b/two", "2026-09-29", 2, "daily", "python", 70),
        ]
    )
    assert compute_period_star_velocity(frame, "monthly", 30).empty
    daily = compute_period_star_velocity(frame, "daily", 7)
    assert daily["repo_full_name"].tolist() == ["b/two"]


def test_period_star_velocity_skips_rows_without_increment() -> None:
    frame = period_trending_frame([("a/one", "2026-09-29", 1, "weekly", "python", None)])
    assert compute_period_star_velocity(frame, "weekly", 7).empty


def test_period_star_velocity_empty_input_and_errors() -> None:
    empty = compute_period_star_velocity(period_trending_frame([]), "weekly", 7)
    assert empty.empty
    assert list(empty.columns) == ["repo_full_name", "snapshot_date", "star_velocity_7d"]
    with pytest.raises(ValueError, match="window_days"):
        compute_period_star_velocity(period_trending_frame([]), "weekly", 0)
    with pytest.raises(ValueError, match="missing required columns"):
        compute_period_star_velocity(pd.DataFrame({"repo_full_name": ["a/b"]}), "weekly", 7)


def test_rank_momentum_uses_previous_snapshot_date() -> None:
    frame = trending_frame(
        [
            ("a/one", "2026-09-01", 5, "daily", "python"),
            ("a/one", "2026-09-02", 2, "daily", "python"),
        ]
    )
    result = compute_rank_momentum(frame, "daily", "python")
    assert list(result.columns) == ["repo_full_name", "snapshot_date", "rank_momentum"]
    assert result.to_dict("records") == [
        {"repo_full_name": "a/one", "snapshot_date": "2026-09-02", "rank_momentum": 3}
    ]


def test_rank_momentum_is_negative_when_rank_drops() -> None:
    frame = trending_frame(
        [
            ("c/three", "2026-09-01", 1, "daily", "python"),
            ("c/three", "2026-09-02", 4, "daily", "python"),
        ]
    )
    result = compute_rank_momentum(frame, "daily", "python")
    assert result["rank_momentum"].tolist() == [-3]


def test_rank_momentum_omits_first_day_and_other_scopes() -> None:
    frame = trending_frame(
        [
            ("a/one", "2026-09-01", 5, "daily", "python"),
            ("a/one", "2026-09-02", 2, "daily", "rust"),
            ("b/two", "2026-09-01", 1, "weekly", "python"),
        ]
    )
    assert compute_rank_momentum(frame, "daily", "python").empty
    assert compute_rank_momentum(frame, "weekly", "python").empty
    assert compute_rank_momentum(frame, "daily", "rust").empty


def test_rank_momentum_empty_input() -> None:
    assert compute_rank_momentum(trending_frame([]), "daily", "").empty


def test_rank_momentum_requires_columns() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        compute_rank_momentum(pd.DataFrame({"repo_full_name": ["a/b"]}), "daily", "")


def test_language_share_uses_all_trending_rows_as_denominator() -> None:
    frame = trending_frame(
        [
            ("a/one", "2026-09-01", 1, "daily", "python"),
            ("b/two", "2026-09-01", 2, "daily", "python"),
            ("c/three", "2026-09-01", 3, "daily", "rust"),
            ("d/four", "2026-09-01", 4, "daily", ""),
            ("e/five", "2026-09-01", 5, "weekly", "python"),
        ]
    )
    result = compute_language_share(frame, "daily")
    assert list(result.columns) == ["snapshot_date", "language", "language_share"]
    shares = dict(zip(result["language"], result["language_share"], strict=True))
    assert shares == {"": 0.25, "python": 0.5, "rust": 0.25}


def test_language_share_per_language_and_day() -> None:
    frame = trending_frame(
        [
            ("a/one", "2026-09-01", 1, "daily", "python"),
            ("b/two", "2026-09-02", 1, "daily", "python"),
            ("c/three", "2026-09-02", 2, "daily", "rust"),
        ]
    )
    result = compute_language_share(frame, "daily")
    records = result.to_dict("records")
    assert records[0] == {
        "snapshot_date": "2026-09-01",
        "language": "python",
        "language_share": 1.0,
    }
    assert {
        row["language"]: row["language_share"]
        for row in records
        if row["snapshot_date"] == "2026-09-02"
    } == {
        "python": 0.5,
        "rust": 0.5,
    }


def test_language_share_empty_and_missing_columns() -> None:
    assert compute_language_share(trending_frame([]), "daily").empty
    with pytest.raises(ValueError, match="missing required columns"):
        compute_language_share(pd.DataFrame({"language": ["python"]}), "daily")


def test_language_share_filters_period() -> None:
    frame = trending_frame([("a/one", "2026-09-01", 1, "weekly", "python")])
    assert compute_language_share(frame, "daily").empty
    assert not compute_language_share(frame, "weekly").empty
