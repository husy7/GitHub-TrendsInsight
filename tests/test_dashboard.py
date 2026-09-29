"""Dashboard smoke tests: the page must render from SQLite only (AGENTS.md §9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import streamlit as st
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
            TrendingSnapshot(
                snapshot_date=yesterday,
                period="daily",
                language="python",
                rank=1,
                repo_full_name="a/one",
                stars=100,
                forks=10,
                stars_in_period=50,
                description="d",
                url="u",
            ),
            TrendingSnapshot(
                snapshot_date=yesterday,
                period="daily",
                language="rust",
                rank=2,
                repo_full_name="b/two",
                stars=200,
                forks=20,
                stars_in_period=60,
                description="d",
                url="u",
            ),
            TrendingSnapshot(
                snapshot_date=today,
                period="daily",
                language="python",
                rank=2,
                repo_full_name="a/one",
                stars=150,
                forks=12,
                stars_in_period=200,
                description="d",
                url="u",
            ),
            TrendingSnapshot(
                snapshot_date=today,
                period="daily",
                language="rust",
                rank=1,
                repo_full_name="b/two",
                stars=250,
                forks=22,
                stars_in_period=100,
                description="d",
                url="u",
            ),
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
    overview = {metric.label: metric.value for metric in app.metric[:3]}
    assert overview == {
        "本周期新增 Star": "+300",
        "覆盖语言数": "2",
        "趋势仓库数": "2",
    }
    # 仓库详情卡片也会渲染 stars / forks / open_issues / language。
    detail_labels = [metric.label for metric in app.metric[3:]]
    assert detail_labels == ["stars", "forks", "open_issues", "language"]
    # 语言占比图 + Star Velocity 图, 两张都要渲染出来 (不能是空白图)。
    assert len(app.get("plotly_chart")) == 2
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


def test_dashboard_exports_analyze_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'trends.db'}"
    seed_database(database_url)
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    (processed / "trending_report_daily.md").write_text("# 报告测试标记\n", encoding="utf-8")
    (processed / "repo_metrics.csv").write_text("repo_full_name\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    st.cache_data.clear()

    app = AppTest.from_file(str(DASHBOARD_PATH), default_timeout=60)
    app.run()

    assert not app.exception
    labels = [button.label for button in app.get("download_button")]
    assert any("下载 Markdown 报告" in label for label in labels)
    assert any("repo_metrics.csv" in label for label in labels)
    assert any("报告测试标记" in item.value for item in app.markdown)


def test_dashboard_hints_when_report_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'trends.db'}"
    seed_database(database_url)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    st.cache_data.clear()

    app = AppTest.from_file(str(DASHBOARD_PATH), default_timeout=60)
    app.run()

    assert not app.exception
    assert any("还没有报告文件" in info.value for info in app.info)
    assert not list(app.get("download_button"))
