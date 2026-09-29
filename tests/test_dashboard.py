"""Dashboard smoke tests: the page must render from SQLite only (AGENTS.md §9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine
from streamlit.testing.v1 import AppTest

from trends.config import get_settings, utc_snapshot_date
from trends.storage.db import (
    get_engine,
    init_db,
    insert_repo_snapshots,
    insert_trending_snapshots,
    upsert_repo_metrics,
)
from trends.storage.models import RepoMetrics, RepoSnapshot, TrendingSnapshot

DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "src" / "trends" / "dashboard" / "app.py"


def seed_database(database_url: str) -> None:
    engine: Engine = get_engine(database_url)
    init_db(engine)
    today = utc_snapshot_date()
    yesterday = utc_snapshot_date(datetime.now(tz=UTC) - timedelta(days=1))
    insert_trending_snapshots(
        engine,
        [
            TrendingSnapshot(yesterday, "daily", "python", 1, "a/one", 100, 10, "d", "u"),
            TrendingSnapshot(yesterday, "daily", "rust", 2, "b/two", 200, 20, "d", "u"),
            TrendingSnapshot(today, "daily", "python", 2, "a/one", 150, 12, "d", "u"),
            TrendingSnapshot(today, "daily", "rust", 1, "b/two", 250, 22, "d", "u"),
        ],
    )
    insert_repo_snapshots(
        engine,
        [
            RepoSnapshot("a/one", today, 150, 12, 3, "python", '["cli", "uv"]'),
            RepoSnapshot("b/two", today, 250, 22, 5, "rust", "[]"),
        ],
    )
    upsert_repo_metrics(
        engine,
        [
            RepoMetrics("a/one", today, 7.14, 2.5, 1, 0.5),
            RepoMetrics("b/two", today, 7.14, 2.5, -1, 0.5),
        ],
    )
    engine.dispose()


def test_dashboard_renders_overview_cards_from_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'trends.db'}"
    seed_database(database_url)
    monkeypatch.delenv("TRENDING_LANGUAGE", raising=False)
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    app = AppTest.from_file(str(DASHBOARD_PATH), default_timeout=60)
    app.run()

    assert not app.exception
    overview = {metric.label: metric.value for metric in app.metric[:4]}
    assert overview == {
        "总 Star (最新快照)": "400",
        "今日新增 Star": "+100",
        "覆盖语言数": "2",
        "趋势仓库数": "2",
    }
    # 仓库详情卡片也会渲染 stars / forks / open_issues / language。
    detail_labels = [metric.label for metric in app.metric[4:]]
    assert detail_labels == ["stars", "forks", "open_issues", "language"]
    # 筛选器默认值: period=daily (30 天窗口), 详情默认选第一个仓库。
    selectbox_values = {box.value for box in app.selectbox}
    assert {"daily", 30, "全部", "a/one"} <= selectbox_values


def test_dashboard_shows_hint_when_database_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    app = AppTest.from_file(str(DASHBOARD_PATH), default_timeout=60)
    app.run()

    assert not app.exception
    assert any("还没有该 period 的快照数据" in warning.value for warning in app.warning)
