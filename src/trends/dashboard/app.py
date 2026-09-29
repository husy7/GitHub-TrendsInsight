"""Streamlit dashboard for GitHub Trending insights (AGENTS.md §9).

只读 SQLite 的 `trending_snapshots` / `repo_metrics` / `repo_snapshots`,
页面加载不会触发任何 GitHub API 请求。

启动:
    uv run streamlit run src/trends/dashboard/app.py
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from trends.analysis.metrics import compute_language_share, star_velocity_column
from trends.config import get_settings
from trends.storage.db import (
    get_engine,
    init_db,
    load_latest_repo_details,
    load_repo_metrics,
    load_trending_snapshots,
)

WINDOW_OPTIONS = (7, 30)
TIME_RANGE_OPTIONS = (7, 30, 90)

st.set_page_config(page_title="GitHub Trends Insight", page_icon="📈", layout="wide")


@st.cache_data(ttl=300, show_spinner=False)
def load_frames(
    database_url: str,
    period: str,
    days: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the three tables the dashboard needs (no network access)."""
    engine = get_engine(database_url)
    init_db(engine)
    trending = load_trending_snapshots(engine, period=period, days=days)
    metrics = load_repo_metrics(engine, days=days)
    details = load_latest_repo_details(engine)
    return trending, metrics, details


def period_star_gain(trending: pd.DataFrame) -> float | None:
    """最新快照的区间新增合计: daily=今日, weekly=近 7 天, monthly=近 30 天。

    优先用卡片上的 `stars_in_period` (区间真实增量); 老数据该列全为空时,
    退回用相邻两天的 stars 差分近似。
    """
    if trending.empty:
        return None
    latest_day = trending["snapshot_date"].max()
    latest = trending.loc[trending["snapshot_date"] == latest_day]
    if "stars_in_period" in latest.columns:
        values = latest["stars_in_period"].dropna()
        if not values.empty:
            return float(values.sum())
    return _two_day_star_gain(trending)


def _two_day_star_gain(trending: pd.DataFrame) -> float | None:
    """没有 stars_in_period 时的近似口径: 相邻两天都出现的仓库的 stars 差分。"""
    frame = trending.loc[:, ["repo_full_name", "snapshot_date", "stars"]].dropna(subset=["stars"])
    if frame.empty:
        return None
    pivot = frame.pivot_table(
        index="repo_full_name",
        columns="snapshot_date",
        values="stars",
        aggfunc="max",
    )
    if pivot.shape[1] < 2:
        return None
    days = sorted(pivot.columns)
    latest, previous = days[-1], days[-2]
    diff = (pivot[latest] - pivot[previous]).dropna()
    if diff.empty:
        return None
    return float(diff.sum())


def language_trend_figure(trending: pd.DataFrame, period: str) -> object:
    share = compute_language_share(trending, period)
    if share.empty:
        return None
    share = share.loc[share["language"] != ""]
    top_languages = share.groupby("language")["language_share"].mean().nlargest(6).index.tolist()
    plot_frame = share.loc[share["language"].isin(top_languages)].sort_values("snapshot_date")
    figure = px.line(
        plot_frame,
        x="snapshot_date",
        y="language_share",
        color="language",
        markers=True,
        labels={"snapshot_date": "快照日期", "language_share": "语言占比", "language": "语言"},
        title="语言占比趋势 (Top 6)",
    )
    figure.update_layout(legend_title_text="语言", height=380)
    return figure


def covered_language_count(latest_trending: pd.DataFrame, details: pd.DataFrame) -> int:
    """当前榜单仓库覆盖的语言数。

    `trending_snapshots.language` 存的是榜单语言筛选值 (不筛选时是空字符串),
    所以覆盖语言数要取 `repo_snapshots.language` 这个仓库主语言。
    """
    names = set(latest_trending["repo_full_name"])
    if not details.empty:
        scoped = details.loc[details["repo_full_name"].isin(names), "language"].dropna()
        return int(scoped.nunique())
    return int(latest_trending["language"].replace("", pd.NA).nunique())


def velocity_figure(metrics: pd.DataFrame, window_days: int) -> object:
    column = star_velocity_column(window_days)
    if metrics.empty or column not in metrics.columns:
        return None
    frame = metrics.dropna(subset=[column])
    if frame.empty:
        return None
    latest_day = frame["snapshot_date"].max()
    frame = frame.loc[frame["snapshot_date"] == latest_day]
    frame = frame.sort_values(column, ascending=False).head(10)
    figure = px.bar(
        frame.iloc[::-1],
        x=column,
        y="repo_full_name",
        orientation="h",
        labels={column: f"Star Velocity ({window_days} 天, Star/天)", "repo_full_name": "仓库"},
        title=f"Star Velocity Top 10 ({latest_day})",
    )
    figure.update_layout(height=420, showlegend=False)
    return figure


def render_repo_details(details: pd.DataFrame, repo_full_name: str) -> None:
    row = details.loc[details["repo_full_name"] == repo_full_name]
    if row.empty:
        st.info("该仓库还没有详情快照, 等待下一次采集。")
        return
    record = row.iloc[0]
    first, second, third, fourth = st.columns(4)
    first.metric("stars", f"{record['stars']:,.0f}" if pd.notna(record["stars"]) else "—")
    second.metric("forks", f"{record['forks']:,.0f}" if pd.notna(record["forks"]) else "—")
    third.metric(
        "open_issues",
        f"{record['open_issues']:,.0f}" if pd.notna(record["open_issues"]) else "—",
    )
    fourth.metric("language", record["language"] or "—")
    topics = record.get("topics_json")
    if isinstance(topics, str) and topics.strip():
        st.write("topics: " + ", ".join(json.loads(topics)))
    st.caption(f"snapshot_date: {record['snapshot_date']}")


def main() -> None:
    """Render the single-page dashboard."""
    settings = get_settings()
    st.title("GitHub Trending Insight")
    st.caption("数据来自每日采集的 GitHub Trending 页面与仓库详情, 仅读取本地 SQLite 快照。")

    with st.sidebar:
        st.header("筛选器")
        period = st.selectbox("period", ("daily", "weekly", "monthly"), index=0)
        days = st.selectbox("时间范围 (天)", TIME_RANGE_OPTIONS, index=1)
        window_days = st.radio("Star Velocity 窗口", WINDOW_OPTIONS, index=0, horizontal=True)

    trending, metrics, details = load_frames(settings.database_url, period, int(days))
    if trending.empty:
        st.warning(
            "还没有该 period 的快照数据, 先运行 "
            "`uv run python scripts/collect.py --period daily,weekly,monthly`。"
        )
        return

    languages = sorted({value for value in trending["language"].fillna("") if value})
    with st.sidebar:
        language = st.selectbox("language", ["全部", *languages], index=0)
    if language != "全部":
        trending = trending.loc[trending["language"] == language]

    latest_day = trending["snapshot_date"].max()
    latest_trending = trending.loc[trending["snapshot_date"] == latest_day]
    gain = period_star_gain(trending)
    metrics_latest = (
        metrics.loc[metrics["snapshot_date"] == latest_day] if not metrics.empty else metrics
    )

    card_two, card_three, card_four = st.columns(3)
    card_two.metric("本周期新增 Star", "—" if gain is None else f"{gain:+,.0f}")
    card_three.metric("覆盖语言数", f"{covered_language_count(latest_trending, details)}")
    card_four.metric("趋势仓库数", f"{latest_trending['repo_full_name'].nunique()}")

    figure = language_trend_figure(trending, period)
    if figure is not None:
        st.plotly_chart(figure)

    velocity = velocity_figure(metrics_latest, int(window_days))
    if velocity is not None:
        st.plotly_chart(velocity)
    else:
        st.info(
            "还没有可用的 Star Velocity 结果, 运行 `uv run python scripts/analyze.py --days 30` 生成。"
        )

    st.subheader("仓库详情")
    options = sorted(latest_trending["repo_full_name"].tolist())
    if options:
        selected = st.selectbox("选择仓库", options, index=0)
        render_repo_details(details, selected)

    with st.expander("原始趋势快照 (最新一天)"):
        st.dataframe(
            latest_trending.loc[
                :,
                [
                    "rank",
                    "repo_full_name",
                    "stars",
                    "forks",
                    "stars_in_period",
                    "language",
                    "description",
                ],
            ].sort_values("rank"),
            hide_index=True,
        )


main()
