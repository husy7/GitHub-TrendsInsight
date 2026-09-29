"""Report builders and CSV writers for `data/processed/` (AGENTS.md §8.2)."""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from trends.analysis.metrics import (
    compute_language_share,
    compute_period_star_velocity,
    compute_rank_momentum,
    compute_star_velocity,
    star_velocity_column,
)
from trends.config import TRENDING_BASE_URL
from trends.storage.models import RepoMetrics

logger = logging.getLogger(__name__)

DEFAULT_PROCESSED_DIR = Path("data/processed")
STAR_VELOCITY_WINDOWS: tuple[int, ...] = (7, 30)
# 每个速度窗口优先用哪个榜单的区间增量: weekly = 近 7 天, monthly = 近 30 天。
STAR_VELOCITY_PERIODS: dict[int, str] = {7: "weekly", 30: "monthly"}
METRICS_FILENAME = "repo_metrics.csv"
MISSING_CELL = "—"


def star_velocity_filename(window_days: int) -> str:
    """CSV name for one velocity window, e.g. `star_velocity_top7d.csv`."""
    return f"star_velocity_top{window_days}d.csv"


def rank_momentum_filename(period: str, language: str) -> str:
    """CSV name for one `period`/`language` pair."""
    return f"rank_momentum_{period}_{language or 'all'}.csv"


def language_share_filename(period: str) -> str:
    """CSV name for one `period`, e.g. `language_share_daily.csv`."""
    return f"language_share_{period}.csv"


def markdown_report_filename(period: str) -> str:
    """Markdown report name for one `period`, e.g. `trending_report_daily.md`."""
    return f"trending_report_{period}.md"


def write_dataframe(frame: pd.DataFrame, path: Path) -> Path:
    """Write `frame` to UTF-8 CSV without the index and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")
    logger.info("wrote %d rows to %s", len(frame), path)
    return path


def export_language_share(
    trending: pd.DataFrame,
    period: str,
    output_dir: Path = DEFAULT_PROCESSED_DIR,
) -> Path:
    """Write `language_share_{period}.csv` for `period`."""
    share = compute_language_share(trending, period)
    return write_dataframe(share, output_dir / language_share_filename(period))


def export_star_velocity_top(
    metrics_frame: pd.DataFrame,
    window_days: int,
    output_dir: Path = DEFAULT_PROCESSED_DIR,
    top_n: int = 10,
) -> Path:
    """Write the latest-day `star_velocity_{window_days}d` top `top_n` rows.

    输入是 `build_metrics_frame` 的结果: 其中 7d/30d 速度已优先采用周期增量口径。
    """
    velocity_column = star_velocity_column(window_days)
    path = output_dir / star_velocity_filename(window_days)
    columns = ["repo_full_name", "snapshot_date", velocity_column]
    if metrics_frame.empty or velocity_column not in metrics_frame.columns:
        return write_dataframe(pd.DataFrame(columns=columns), path)
    frame = metrics_frame.loc[:, columns].dropna(subset=[velocity_column])
    if frame.empty:
        return write_dataframe(pd.DataFrame(columns=columns), path)
    latest_day = frame["snapshot_date"].max()
    top = frame.loc[frame["snapshot_date"] == latest_day]
    top = top.sort_values(velocity_column, ascending=False, kind="stable").head(top_n)
    return write_dataframe(top, path)


def export_rank_momentum(
    trending: pd.DataFrame,
    period: str,
    language: str,
    output_dir: Path = DEFAULT_PROCESSED_DIR,
) -> Path:
    """Write `rank_momentum_{period}_{language}.csv`."""
    momentum = compute_rank_momentum(trending, period, language)
    return write_dataframe(momentum, output_dir / rank_momentum_filename(period, language))


def build_metrics_frame(
    trending: pd.DataFrame,
    snapshots: pd.DataFrame,
    *,
    period: str,
    language: str,
) -> pd.DataFrame:
    """Join every §8.1 metric into one frame keyed by repo + `snapshot_date`.

    7d/30d 速度优先使用周期增量口径 (weekly/monthly), 缺失时才回退历史快照差分。
    因此 `trending` 应传入包含全部 period 的 frame, `period`/`language` 只决定输出范围。
    """
    scope = trending.loc[
        (trending["period"] == period) & (trending["language"] == language),
        ["repo_full_name", "snapshot_date"],
    ].drop_duplicates()
    frame = scope.reset_index(drop=True)
    for window_days in STAR_VELOCITY_WINDOWS:
        column = star_velocity_column(window_days)
        velocity = _combined_velocity(trending, snapshots, window_days)
        if velocity.empty:
            frame[column] = pd.NA
            continue
        frame = frame.merge(velocity, on=["repo_full_name", "snapshot_date"], how="left")

    momentum = compute_rank_momentum(trending, period, language)
    if momentum.empty:
        frame["rank_momentum"] = pd.NA
    else:
        frame = frame.merge(momentum, on=["repo_full_name", "snapshot_date"], how="left")

    share = compute_language_share(trending, period)
    if share.empty:
        frame["language_share"] = pd.NA
    else:
        share = share.loc[share["language"] == language, ["snapshot_date", "language_share"]]
        frame = frame.merge(share, on="snapshot_date", how="left")

    ordered = [
        "repo_full_name",
        "snapshot_date",
        *(star_velocity_column(window) for window in STAR_VELOCITY_WINDOWS),
        "rank_momentum",
        "language_share",
    ]
    return (
        frame.loc[:, ordered]
        .sort_values(["repo_full_name", "snapshot_date"], kind="stable")
        .reset_index(drop=True)
    )


def _combined_velocity(
    trending: pd.DataFrame,
    snapshots: pd.DataFrame,
    window_days: int,
) -> pd.DataFrame:
    """周期增量口径优先, 缺失处回退到历史快照差分。"""
    column = star_velocity_column(window_days)
    pieces: list[pd.DataFrame] = []
    source_period = STAR_VELOCITY_PERIODS.get(window_days)
    # 老数据/手工构造的 frame 可能没有 stars_in_period: 直接走历史差分口径。
    if source_period is not None and "stars_in_period" in trending.columns:
        pieces.append(compute_period_star_velocity(trending, source_period, window_days))
    pieces.append(compute_star_velocity(snapshots, window_days))
    usable = [piece for piece in pieces if not piece.empty]
    if not usable:
        return pd.DataFrame(columns=["repo_full_name", "snapshot_date", column])
    combined = pd.concat(usable, ignore_index=True)
    return combined.drop_duplicates(
        subset=["repo_full_name", "snapshot_date"], keep="first"
    ).reset_index(drop=True)


def _optional_float(value: Any) -> float | None:
    """Return `None` for missing/NaN cells instead of writing 0 (AGENTS.md §7.4)."""
    if value is None or pd.isna(value):
        return None
    numeric = float(value)
    return None if math.isnan(numeric) else numeric


def _optional_int(value: Any) -> int | None:
    numeric = _optional_float(value)
    return None if numeric is None else int(numeric)


def to_repo_metrics(frame: pd.DataFrame) -> list[RepoMetrics]:
    """Convert a `build_metrics_frame` result into `repo_metrics` rows."""
    rows: list[RepoMetrics] = []
    for record in frame.to_dict(orient="records"):
        rows.append(
            RepoMetrics(
                repo_full_name=str(record["repo_full_name"]),
                snapshot_date=str(record["snapshot_date"]),
                star_velocity_7d=_optional_float(record.get("star_velocity_7d")),
                star_velocity_30d=_optional_float(record.get("star_velocity_30d")),
                rank_momentum=_optional_int(record.get("rank_momentum")),
                language_share=_optional_float(record.get("language_share")),
            )
        )
    return rows


def export_metrics_frame(
    frame: pd.DataFrame,
    output_dir: Path = DEFAULT_PROCESSED_DIR,
) -> Path:
    """Write `repo_metrics.csv` for the dashboard."""
    return write_dataframe(frame, output_dir / METRICS_FILENAME)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _cell(value: Any) -> str:
    """Render one Markdown table cell; missing values become `—` (never 0)."""
    if _is_missing(value):
        return MISSING_CELL
    text = str(value).replace("|", "\\|").replace("\n", " ").strip()
    return text or MISSING_CELL


def _number(value: Any, digits: int = 0) -> str:
    if _is_missing(value):
        return MISSING_CELL
    return f"{float(value):,.{digits}f}"


def _signed(value: Any) -> str:
    if _is_missing(value):
        return MISSING_CELL
    return f"{float(value):+,.0f}"


def _percent(value: Any) -> str:
    if _is_missing(value):
        return MISSING_CELL
    return f"{float(value) * 100:.1f}%"


def _repo_link(repo_full_name: str, url: Any) -> str:
    target = _cell(url)
    if target == MISSING_CELL:
        return _cell(repo_full_name)
    return f"[{repo_full_name}]({target})"


def _details_by_repo(details: pd.DataFrame | None, repo_names: list[str]) -> dict[str, Any]:
    if details is None or details.empty:
        return {}
    scoped = details.loc[details["repo_full_name"].isin(repo_names)]
    return {str(row["repo_full_name"]): row for row in scoped.to_dict("records")}


def _language_table(latest: pd.DataFrame, details: dict[str, Any]) -> list[tuple[str, int, float]]:
    """语言分布按仓库主语言 (`repo_snapshots.language`) 统计, 缺失时退回榜单筛选值。"""
    resolved: list[str] = []
    for repo_full_name in latest["repo_full_name"]:
        detail = details.get(str(repo_full_name))
        language = detail.get("language") if detail is not None else None
        resolved.append(str(language).strip() if isinstance(language, str) and language else "")
    counts: dict[str, int] = {}
    for language in resolved:
        if language:
            counts[language] = counts.get(language, 0) + 1
    total = int(latest["repo_full_name"].nunique())
    if not counts and total:
        for value, count in latest["language"].fillna("").value_counts().items():
            if value:
                counts[str(value)] = int(count)
    if not counts:
        return []
    ranking = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [(language, count, count / total) for language, count in ranking]


def build_markdown_report(
    trending: pd.DataFrame,
    metrics_frame: pd.DataFrame,
    *,
    period: str,
    language: str,
    details: pd.DataFrame | None = None,
    top_n: int = 10,
    generated_at: datetime | None = None,
) -> str:
    """Render a human-readable Markdown report for the latest snapshot.

    报告覆盖: 概览、Star Velocity Top N、Rank Momentum、语言占比、仓库明细
    (`description` / `url` 链接 / topics / `stars_in_period`)。纯函数, 不写文件。
    """
    generated = (generated_at or datetime.now(tz=UTC)).astimezone(UTC)
    stamp = generated.strftime("%Y-%m-%dT%H:%M:%SZ")
    source_links = " · ".join(
        f"[{name}]({TRENDING_BASE_URL}?since={name})" for name in ("daily", "weekly", "monthly")
    )
    header = [
        f"- 生成时间 (UTC): `{stamp}`",
        f"- 主榜单 period: `{period}` · language 筛选: {_cell(language) if language else '全部'}",
        f"- 数据源: {source_links}",
    ]
    if trending.empty:
        return "\n".join(
            [
                f"# GitHub Trending 洞察报告 · {MISSING_CELL}",
                "",
                *header,
                "",
                "> 当前没有可用的 `trending_snapshots` 数据。",
                "",
            ]
        )

    latest_day = str(trending["snapshot_date"].max())
    latest = trending.loc[trending["snapshot_date"] == latest_day].sort_values("rank")
    repo_names = [str(name) for name in latest["repo_full_name"]]
    detail_map = _details_by_repo(details, repo_names)
    metrics = (
        metrics_frame.loc[metrics_frame["snapshot_date"] == latest_day]
        if not metrics_frame.empty
        else metrics_frame
    )

    lines: list[str] = [
        f"# GitHub Trending 洞察报告 · {latest_day}",
        "",
        *header,
        f"- snapshot_date: `{latest_day}` · 仓库数: {len(repo_names)}",
        "",
    ]

    # 1. 概览
    velocity_7d = (
        metrics["star_velocity_7d"]
        if "star_velocity_7d" in metrics.columns
        else pd.Series(dtype="float64")
    )
    lines += [
        "## 1. 概览",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 趋势仓库数 | {len(repo_names)} |",
        f"| 榜单 Star 合计 | {_number(latest['stars'].sum(min_count=1))} |",
        f"| 本周期新增 Star | {_signed(latest['stars_in_period'].sum(min_count=1))} |",
        f"| 覆盖语言数 | {len(_language_table(latest, detail_map))} |",
        f"| 有 7 天速度的仓库数 | {int(velocity_7d.notna().sum())} |",
        "",
    ]

    # 2. Star Velocity Top N
    lines += [f"## 2. Star Velocity Top {top_n} (近 7 天)", ""]
    ranked = (
        metrics.dropna(subset=["star_velocity_7d"])
        if "star_velocity_7d" in metrics.columns
        else pd.DataFrame()
    )
    if ranked.empty:
        lines += [
            "> 本周期暂时拿不到 7 天速度 (需要 weekly 榜单的 `stars_in_period` 或 7 天前的快照)。",
            "",
        ]
    else:
        ranked = ranked.sort_values("star_velocity_7d", ascending=False, kind="stable").head(top_n)
        lines += [
            "| # | 仓库 | 语言 | stars | 本周期新增 | star_velocity_7d | star_velocity_30d | rank_momentum |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for position, row in enumerate(ranked.to_dict("records"), start=1):
            detail = detail_map.get(str(row["repo_full_name"]), {})
            trending_row = latest.loc[latest["repo_full_name"] == row["repo_full_name"]].iloc[0]
            lines.append(
                "| {position} | {repo} | {language} | {stars} | {period} | {v7} | {v30} | {momentum} |".format(
                    position=position,
                    repo=_repo_link(str(row["repo_full_name"]), trending_row.get("url")),
                    language=_cell(detail.get("language")),
                    stars=_number(trending_row.get("stars")),
                    period=_signed(trending_row.get("stars_in_period")),
                    v7=_number(row.get("star_velocity_7d"), 1),
                    v30=_number(row.get("star_velocity_30d"), 1),
                    momentum=_signed(row.get("rank_momentum")),
                )
            )
        lines.append("")

    # 3. Rank Momentum
    lines += ["## 3. 排名动量 (rank_momentum)", ""]
    momentum = (
        metrics.dropna(subset=["rank_momentum"])
        if "rank_momentum" in metrics.columns
        else pd.DataFrame()
    )
    if momentum.empty:
        days = int(trending["snapshot_date"].nunique())
        lines += [
            f"> 需要至少两个 `snapshot_date` 的同 period + language 快照才能算排名动量 (当前 {days} 天)。",
            "",
        ]
    else:
        momentum = momentum.sort_values("rank_momentum", ascending=False, kind="stable")
        lines += ["| 仓库 | rank_momentum | 说明 |", "|---|---|---|"]
        for row in momentum.to_dict("records"):
            value = float(row["rank_momentum"])
            note = "排名上升" if value > 0 else ("排名下滑" if value < 0 else "排名不变")
            lines.append(
                f"| {_repo_link(str(row['repo_full_name']), _url_for(latest, str(row['repo_full_name'])))} "
                f"| {_signed(value)} | {note} |"
            )
        lines.append("")

    # 4. 语言占比
    lines += ["## 4. 语言占比 (按仓库主语言)", "", "| language | 仓库数 | 占比 |", "|---|---|---|"]
    language_rows = _language_table(latest, detail_map)
    if language_rows:
        lines += [
            f"| {language} | {count} | {_percent(share)} |"
            for language, count, share in language_rows
        ]
    else:
        lines.append(f"| {MISSING_CELL} | 0 | {MISSING_CELL} |")
    lines.append("")

    # 5. 仓库明细
    lines += ["## 5. 仓库明细", ""]
    for trending_row in latest.to_dict("records"):
        repo_full_name = str(trending_row["repo_full_name"])
        detail = detail_map.get(repo_full_name, {})
        topics = _topics_text(detail.get("topics_json"))
        lines += [
            f"### {int(trending_row['rank'])}. {_repo_link(repo_full_name, trending_row.get('url'))}",
            "",
            f"- 描述: {_cell(trending_row.get('description'))}",
            "- 指标: "
            f"stars {_number(trending_row.get('stars'))} · "
            f"forks {_number(detail.get('forks', trending_row.get('forks')))} · "
            f"open_issues {_number(detail.get('open_issues'))} · "
            f"language {_cell(detail.get('language'))}",
            f"- 本周期新增 ({period}): {_signed(trending_row.get('stars_in_period'))} Star",
            f"- topics: {topics}",
            "",
        ]

    # 6. 口径与方法
    lines += [
        "## 6. 口径与方法",
        "",
        "- Star Velocity 优先用 weekly/monthly 榜单的区间增量 (`stars_in_period / 窗口天数`), "
        "缺失时回退到历史快照差分 (`stars(T) - stars(T-n 天)) / n`。",
        "- Rank Momentum = 前一 `snapshot_date` 的 `rank` - 当日 `rank`, 正数表示排名上升。",
        "- 缺失值显示为 `—`, 不补 0; 历史快照只追加, 不覆盖。",
        "- 语言占比按仓库主语言 (`repo_snapshots.language`) 统计; "
        f"未取到主语言的仓库不计入分子; CSV `{language_share_filename(period)}` 用的是榜单筛选口径。",
        "",
    ]

    # 7. 相关产物
    lines += [
        "## 7. 相关产物",
        "",
        f"- `{METRICS_FILENAME}` · `{language_share_filename(period)}` · "
        f"`{rank_momentum_filename(period, language)}` · `{star_velocity_filename(7)}` · "
        f"`{star_velocity_filename(30)}`",
        "- 仪表板: `uv run streamlit run src/trends/dashboard/app.py`",
        "",
    ]
    return "\n".join(lines)


def _url_for(trending: pd.DataFrame, repo_full_name: str) -> Any:
    matched = trending.loc[trending["repo_full_name"] == repo_full_name, "url"]
    return matched.iloc[0] if not matched.empty else None


def _topics_text(topics_json: Any) -> str:
    """Render `topics_json` as inline code list; missing topics show `—`."""
    if not isinstance(topics_json, str) or not topics_json.strip():
        return MISSING_CELL
    try:
        parsed = json.loads(topics_json)
    except json.JSONDecodeError:
        return _cell(topics_json)
    if not isinstance(parsed, list) or not parsed:
        return MISSING_CELL
    return ", ".join(f"`{_cell(topic)}`" for topic in parsed)


def export_markdown_report(
    content: str,
    period: str,
    output_dir: Path = DEFAULT_PROCESSED_DIR,
) -> Path:
    """Write the Markdown report for `period` and return its path."""
    path = output_dir / markdown_report_filename(period)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("wrote markdown report to %s (%d chars)", path, len(content))
    return path
