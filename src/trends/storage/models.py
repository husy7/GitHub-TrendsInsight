"""Data models and the executable DDL from AGENTS.md §7.5."""

from __future__ import annotations

from dataclasses import dataclass

TRENDING_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS trending_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT    NOT NULL,
    period          TEXT    NOT NULL CHECK (period IN ('daily','weekly','monthly')),
    language        TEXT    NOT NULL DEFAULT '',
    rank            INTEGER NOT NULL,
    repo_full_name  TEXT    NOT NULL,
    stars           INTEGER,
    forks           INTEGER,
    description     TEXT,
    url             TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (repo_full_name, snapshot_date, period, language)
)
"""

TRENDING_SNAPSHOTS_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_trending_date_period
    ON trending_snapshots (snapshot_date, period, language)
"""

REPO_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS repo_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_full_name  TEXT    NOT NULL,
    snapshot_date   TEXT    NOT NULL,
    stars           INTEGER,
    forks           INTEGER,
    open_issues     INTEGER,
    language        TEXT,
    topics_json     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (repo_full_name, snapshot_date)
)
"""

REPO_SNAPSHOTS_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_repo_snapshots_name_date
    ON repo_snapshots (repo_full_name, snapshot_date)
"""

REPO_METRICS_DDL = """
CREATE TABLE IF NOT EXISTS repo_metrics (
    repo_full_name     TEXT    NOT NULL,
    snapshot_date      TEXT    NOT NULL,
    star_velocity_7d   REAL,
    star_velocity_30d  REAL,
    rank_momentum      INTEGER,
    language_share     REAL,
    PRIMARY KEY (repo_full_name, snapshot_date)
)
"""

FAILED_REPOS_DDL = """
CREATE TABLE IF NOT EXISTS failed_repos (
    repo_full_name  TEXT    NOT NULL,
    snapshot_date   TEXT    NOT NULL,
    reason          TEXT    NOT NULL,
    status_code     INTEGER,
    PRIMARY KEY (repo_full_name, snapshot_date)
)
"""

SCHEMA_STATEMENTS: tuple[str, ...] = (
    TRENDING_SNAPSHOTS_DDL,
    TRENDING_SNAPSHOTS_INDEX_DDL,
    REPO_SNAPSHOTS_DDL,
    REPO_SNAPSHOTS_INDEX_DDL,
    REPO_METRICS_DDL,
    FAILED_REPOS_DDL,
)


@dataclass(frozen=True, slots=True)
class TrendingSnapshot:
    """One row of `trending_snapshots` (AGENTS.md §7.5)."""

    snapshot_date: str
    period: str
    language: str
    rank: int
    repo_full_name: str
    stars: int | None
    forks: int | None
    description: str | None
    url: str


@dataclass(frozen=True, slots=True)
class RepoSnapshot:
    """One row of `repo_snapshots` (AGENTS.md §7.5)."""

    repo_full_name: str
    snapshot_date: str
    stars: int | None
    forks: int | None
    open_issues: int | None
    language: str | None
    topics_json: str


@dataclass(frozen=True, slots=True)
class RepoMetrics:
    """One row of `repo_metrics` (AGENTS.md §7.5)."""

    repo_full_name: str
    snapshot_date: str
    star_velocity_7d: float | None
    star_velocity_30d: float | None
    rank_momentum: int | None
    language_share: float | None


@dataclass(frozen=True, slots=True)
class FailedRepo:
    """One row of `failed_repos` (AGENTS.md §7.5)."""

    repo_full_name: str
    snapshot_date: str
    reason: str
    status_code: int | None
