"""Storage tests: idempotency, upserts and read helpers (AGENTS.md §7.4)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, text

from trends.config import utc_snapshot_date
from trends.storage.db import (
    get_engine,
    insert_repo_snapshots,
    insert_trending_snapshots,
    load_failed_repos,
    load_latest_repo_details,
    load_repo_metrics,
    load_repo_snapshots,
    load_trending_snapshots,
    record_failed_repos,
    upsert_repo_metrics,
)
from trends.storage.models import FailedRepo, RepoMetrics, RepoSnapshot, TrendingSnapshot


def trending_row(
    repo_full_name: str = "a/one",
    snapshot_date: str = "2026-09-01",
    rank: int = 1,
    period: str = "daily",
    language: str = "python",
) -> TrendingSnapshot:
    return TrendingSnapshot(
        snapshot_date=snapshot_date,
        period=period,
        language=language,
        rank=rank,
        repo_full_name=repo_full_name,
        stars=100,
        forks=10,
        description="a description",
        url=f"https://github.com/{repo_full_name}",
    )


def repo_row(
    repo_full_name: str = "a/one",
    snapshot_date: str = "2026-09-01",
    stars: int | None = 100,
) -> RepoSnapshot:
    return RepoSnapshot(
        repo_full_name=repo_full_name,
        snapshot_date=snapshot_date,
        stars=stars,
        forks=10,
        open_issues=3,
        language="rust",
        topics_json='["uv"]',
    )


def test_get_engine_creates_sqlite_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "data"
    engine = get_engine(f"sqlite:///{nested / 'trends.db'}")
    assert nested.is_dir()
    engine.dispose()


def test_insert_trending_snapshots_is_idempotent(engine: Engine) -> None:
    row = trending_row()
    assert insert_trending_snapshots(engine, [row]) == 1
    assert insert_trending_snapshots(engine, [row]) == 0
    frame = load_trending_snapshots(engine)
    assert len(frame) == 1


def test_insert_trending_snapshots_empty_sequence(engine: Engine) -> None:
    assert insert_trending_snapshots(engine, []) == 0


def test_same_repo_different_period_or_language_is_kept(engine: Engine) -> None:
    rows = [
        trending_row(),
        trending_row(period="weekly"),
        trending_row(language="rust"),
    ]
    assert insert_trending_snapshots(engine, rows) == 3


def test_insert_repo_snapshots_is_idempotent(engine: Engine) -> None:
    row = repo_row()
    assert insert_repo_snapshots(engine, [row]) == 1
    assert insert_repo_snapshots(engine, [row]) == 0


def test_upsert_repo_metrics_updates_existing_row(engine: Engine) -> None:
    first = RepoMetrics("a/one", "2026-09-01", 1.0, 2.0, 3, 0.5)
    second = RepoMetrics("a/one", "2026-09-01", 4.0, 5.0, 6, 0.25)
    upsert_repo_metrics(engine, [first])
    upsert_repo_metrics(engine, [second])
    frame = load_repo_metrics(engine)
    assert len(frame) == 1
    assert frame.iloc[0]["star_velocity_7d"] == 4.0
    assert frame.iloc[0]["language_share"] == 0.25


def test_record_failed_repos_upserts_reason(engine: Engine) -> None:
    record_failed_repos(engine, [FailedRepo("a/one", "2026-09-01", "not_found", 404)])
    record_failed_repos(engine, [FailedRepo("a/one", "2026-09-01", "retry_exhausted", 502)])
    frame = load_failed_repos(engine)
    assert len(frame) == 1
    assert frame.iloc[0]["reason"] == "retry_exhausted"
    assert frame.iloc[0]["status_code"] == 502


def test_load_trending_snapshots_filters(engine: Engine) -> None:
    today = utc_snapshot_date()
    insert_trending_snapshots(
        engine,
        [
            trending_row(snapshot_date="2020-01-01"),
            trending_row(snapshot_date=today, period="weekly"),
            trending_row(snapshot_date=today, language="rust"),
        ],
    )
    assert len(load_trending_snapshots(engine)) == 3
    assert len(load_trending_snapshots(engine, period="daily")) == 2
    assert len(load_trending_snapshots(engine, language="rust")) == 1
    assert len(load_trending_snapshots(engine, days=7)) == 2


def test_load_trending_snapshots_is_ordered_by_rank(engine: Engine) -> None:
    insert_trending_snapshots(
        engine,
        [
            trending_row(repo_full_name="b/two", rank=2),
            trending_row(repo_full_name="a/one", rank=1),
        ],
    )
    frame = load_trending_snapshots(engine, period="daily")
    assert frame["repo_full_name"].tolist() == ["a/one", "b/two"]


def test_load_repo_snapshots_filters_by_repo(engine: Engine) -> None:
    insert_repo_snapshots(engine, [repo_row(), repo_row(repo_full_name="b/two")])
    assert len(load_repo_snapshots(engine)) == 2
    assert len(load_repo_snapshots(engine, repo_full_name="b/two")) == 1
    assert load_repo_snapshots(engine, repo_full_name="missing/repo").empty


def test_load_latest_repo_details_returns_newest_row(engine: Engine) -> None:
    insert_repo_snapshots(
        engine,
        [
            repo_row(snapshot_date="2026-09-01", stars=100),
            repo_row(snapshot_date="2026-09-08", stars=180),
            repo_row(repo_full_name="b/two", snapshot_date="2026-09-01", stars=50),
        ],
    )
    latest = load_latest_repo_details(engine)
    assert len(latest) == 2
    stars = dict(zip(latest["repo_full_name"], latest["stars"], strict=True))
    assert stars == {"a/one": 180, "b/two": 50}


def test_missing_numeric_values_stay_null(engine: Engine) -> None:
    insert_repo_snapshots(engine, [repo_row(stars=None)])
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT stars FROM repo_snapshots")).scalar_one()
    assert stored is None


def test_load_failed_repos_days_filter(engine: Engine) -> None:
    record_failed_repos(engine, [FailedRepo("a/one", "2020-01-01", "not_found", 404)])
    assert load_failed_repos(engine, days=7).empty
    assert len(load_failed_repos(engine)) == 1
