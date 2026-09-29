"""SQLite storage: schema bootstrap, idempotent writers and read helpers."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import Connection, Engine, TextClause, create_engine, text

from trends.storage.models import (
    SCHEMA_STATEMENTS,
    FailedRepo,
    RepoMetrics,
    RepoSnapshot,
    TrendingSnapshot,
)

logger = logging.getLogger(__name__)

# 历史事实表只追加: 同一天重复采集不会覆盖已写入的快照。
_INSERT_TRENDING_SNAPSHOTS = text(
    """
    INSERT INTO trending_snapshots (
        snapshot_date, period, language, rank, repo_full_name,
        stars, forks, stars_in_period, description, url
    ) VALUES (
        :snapshot_date, :period, :language, :rank, :repo_full_name,
        :stars, :forks, :stars_in_period, :description, :url
    )
    ON CONFLICT (repo_full_name, snapshot_date, period, language) DO NOTHING
    """
)

# 老库缺少的新列在这里补齐 (AGENTS.md §14.2: 迁移使用新列, 不覆盖历史数据)。
_COLUMN_MIGRATIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "trending_snapshots": (("stars_in_period", "INTEGER"),),
}

_INSERT_REPO_SNAPSHOTS = text(
    """
    INSERT INTO repo_snapshots (
        repo_full_name, snapshot_date, stars, forks, open_issues,
        language, topics_json
    ) VALUES (
        :repo_full_name, :snapshot_date, :stars, :forks, :open_issues,
        :language, :topics_json
    )
    ON CONFLICT (repo_full_name, snapshot_date) DO NOTHING
    """
)

# 指标是可重算的派生数据: 重跑分析时允许覆盖当天结果。
_UPSERT_REPO_METRICS = text(
    """
    INSERT INTO repo_metrics (
        repo_full_name, snapshot_date, star_velocity_7d,
        star_velocity_30d, rank_momentum, language_share
    ) VALUES (
        :repo_full_name, :snapshot_date, :star_velocity_7d,
        :star_velocity_30d, :rank_momentum, :language_share
    )
    ON CONFLICT (repo_full_name, snapshot_date) DO UPDATE SET
        star_velocity_7d = excluded.star_velocity_7d,
        star_velocity_30d = excluded.star_velocity_30d,
        rank_momentum = excluded.rank_momentum,
        language_share = excluded.language_share
    """
)

_UPSERT_FAILED_REPOS = text(
    """
    INSERT INTO failed_repos (repo_full_name, snapshot_date, reason, status_code)
    VALUES (:repo_full_name, :snapshot_date, :reason, :status_code)
    ON CONFLICT (repo_full_name, snapshot_date) DO UPDATE SET
        reason = excluded.reason,
        status_code = excluded.status_code
    """
)


def get_engine(database_url: str) -> Engine:
    """Create an engine, creating the SQLite parent directory when needed."""
    if database_url.startswith("sqlite"):
        _, _, raw_path = database_url.partition("///")
        if raw_path and raw_path != ":memory:" and not raw_path.startswith("file:"):
            Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, future=True)


def init_db(engine: Engine) -> None:
    """Create every table/index from AGENTS.md §7.5 and apply column migrations."""
    with engine.begin() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(text(statement))
        _apply_column_migrations(connection)
    logger.debug("database schema ensured")


def _apply_column_migrations(connection: Connection) -> None:
    """Add columns introduced after the first release to an existing database."""
    for table, columns in _COLUMN_MIGRATIONS.items():
        existing = {
            str(row[1]) for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
        }
        for column, column_type in columns:
            if column in existing:
                continue
            logger.info("migrating %s: adding column %s", table, column)
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


_RowModel = TrendingSnapshot | RepoSnapshot | RepoMetrics | FailedRepo


def _rows_as_params(rows: Sequence[_RowModel]) -> list[dict[str, object]]:
    return [asdict(row) for row in rows]


def _execute_many(engine: Engine, statement: TextClause, params: list[dict[str, object]]) -> int:
    if not params:
        return 0
    with engine.begin() as connection:
        result = connection.execute(statement, params)
    return max(result.rowcount or 0, 0)


def insert_trending_snapshots(engine: Engine, rows: Sequence[TrendingSnapshot]) -> int:
    """Append trending rows; duplicates on the unique key are skipped."""
    return _execute_many(engine, _INSERT_TRENDING_SNAPSHOTS, _rows_as_params(rows))


def insert_repo_snapshots(engine: Engine, rows: Sequence[RepoSnapshot]) -> int:
    """Append repo detail rows; duplicates on the unique key are skipped."""
    return _execute_many(engine, _INSERT_REPO_SNAPSHOTS, _rows_as_params(rows))


def upsert_repo_metrics(engine: Engine, rows: Sequence[RepoMetrics]) -> int:
    """Insert or refresh derived metrics rows."""
    return _execute_many(engine, _UPSERT_REPO_METRICS, _rows_as_params(rows))


def record_failed_repos(engine: Engine, rows: Sequence[FailedRepo]) -> int:
    """Record repositories that could not be collected."""
    return _execute_many(engine, _UPSERT_FAILED_REPOS, _rows_as_params(rows))


def _cutoff_snapshot_date(days: int) -> str:
    reference = datetime.now(tz=UTC).date() - timedelta(days=max(days, 1) - 1)
    return reference.strftime("%Y-%m-%d")


def _read_frame(engine: Engine, sql: str, params: dict[str, object]) -> pd.DataFrame:
    with engine.connect() as connection:
        return pd.read_sql_query(text(sql), connection, params=params)


def load_trending_snapshots(
    engine: Engine,
    *,
    period: str | None = None,
    language: str | None = None,
    days: int | None = None,
) -> pd.DataFrame:
    """Read `trending_snapshots` with optional `period`/`language`/date filters."""
    conditions: list[str] = []
    params: dict[str, object] = {}
    if period is not None:
        conditions.append("period = :period")
        params["period"] = period
    if language is not None:
        conditions.append("language = :language")
        params["language"] = language
    if days is not None:
        conditions.append("snapshot_date >= :cutoff")
        params["cutoff"] = _cutoff_snapshot_date(days)
    sql = "SELECT * FROM trending_snapshots"
    if conditions:
        sql = f"{sql} WHERE {' AND '.join(conditions)}"
    sql = f"{sql} ORDER BY snapshot_date, period, language, rank"
    return _read_frame(engine, sql, params)


def load_repo_snapshots(
    engine: Engine,
    *,
    repo_full_name: str | None = None,
    days: int | None = None,
) -> pd.DataFrame:
    """Read `repo_snapshots`, optionally for one repository and date window."""
    conditions: list[str] = []
    params: dict[str, object] = {}
    if repo_full_name is not None:
        conditions.append("repo_full_name = :repo_full_name")
        params["repo_full_name"] = repo_full_name
    if days is not None:
        conditions.append("snapshot_date >= :cutoff")
        params["cutoff"] = _cutoff_snapshot_date(days)
    sql = "SELECT * FROM repo_snapshots"
    if conditions:
        sql = f"{sql} WHERE {' AND '.join(conditions)}"
    sql = f"{sql} ORDER BY repo_full_name, snapshot_date"
    return _read_frame(engine, sql, params)


def load_repo_metrics(engine: Engine, *, days: int | None = None) -> pd.DataFrame:
    """Read `repo_metrics`, optionally limited to the last `days` days."""
    params: dict[str, object] = {}
    sql = "SELECT * FROM repo_metrics"
    if days is not None:
        sql = f"{sql} WHERE snapshot_date >= :cutoff"
        params["cutoff"] = _cutoff_snapshot_date(days)
    sql = f"{sql} ORDER BY repo_full_name, snapshot_date"
    return _read_frame(engine, sql, params)


def load_latest_repo_details(engine: Engine) -> pd.DataFrame:
    """Read the most recent `repo_snapshots` row per `repo_full_name`."""
    sql = """
        SELECT snapshots.*
        FROM repo_snapshots AS snapshots
        JOIN (
            SELECT repo_full_name, MAX(snapshot_date) AS snapshot_date
            FROM repo_snapshots
            GROUP BY repo_full_name
        ) AS latest
          ON snapshots.repo_full_name = latest.repo_full_name
         AND snapshots.snapshot_date = latest.snapshot_date
        ORDER BY snapshots.repo_full_name
    """
    return _read_frame(engine, sql, {})


def load_failed_repos(engine: Engine, *, days: int | None = None) -> pd.DataFrame:
    """Read `failed_repos`, optionally limited to the last `days` days."""
    params: dict[str, object] = {}
    sql = "SELECT * FROM failed_repos"
    if days is not None:
        sql = f"{sql} WHERE snapshot_date >= :cutoff"
        params["cutoff"] = _cutoff_snapshot_date(days)
    sql = f"{sql} ORDER BY snapshot_date, repo_full_name"
    return _read_frame(engine, sql, params)
