"""Compute metrics and write `data/processed/` reports.

用法:
    uv run python scripts/analyze.py --days 30
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from trends.analysis.metrics import star_velocity_column
from trends.analysis.reports import (
    DEFAULT_PROCESSED_DIR,
    STAR_VELOCITY_WINDOWS,
    build_markdown_report,
    build_metrics_frame,
    export_language_share,
    export_markdown_report,
    export_metrics_frame,
    export_rank_momentum,
    export_star_velocity_top,
    to_repo_metrics,
)
from trends.config import (
    Settings,
    get_settings,
    normalize_language,
    parse_periods,
)
from trends.logging_setup import setup_logging
from trends.storage.db import (
    get_engine,
    init_db,
    load_latest_repo_details,
    load_repo_snapshots,
    load_trending_snapshots,
    upsert_repo_metrics,
)

logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze collected trending snapshots")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--period",
        default=None,
        help="逗号分隔的 period 组合, 例如 daily,weekly,monthly 或 all (默认取 TRENDING_PERIOD)",
    )
    parser.add_argument("--language", default=None, help="语言筛选值, 空字符串表示全部")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_PROCESSED_DIR))
    return parser.parse_args(argv)


def star_source(trending: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    """Prefer `repo_snapshots` for star history, fall back to trending rows."""
    if not snapshots.empty:
        return snapshots.loc[:, ["repo_full_name", "snapshot_date", "stars"]]
    logger.warning("repo_snapshots is empty: falling back to trending_snapshots for stars")
    return trending.loc[:, ["repo_full_name", "snapshot_date", "stars"]]


def run(args: argparse.Namespace, settings: Settings) -> int:
    periods = parse_periods(args.period) if args.period is not None else settings.trending_periods
    raw_language = args.language if args.language is not None else settings.trending_language
    language = normalize_language(raw_language)
    database_url = args.database_url or settings.database_url
    output_dir = Path(args.output_dir)
    days = max(args.days, 1)

    engine = get_engine(database_url)
    init_db(engine)

    frames: dict[str, pd.DataFrame] = {}
    for period in periods:
        trending_period = load_trending_snapshots(engine, period=period, days=days)
        if not trending_period.empty:
            frames[period] = trending_period
    if not frames:
        logger.error("no trending_snapshots for periods=%s within %d days", ",".join(periods), days)
        return 1
    # repo_metrics 主键是 (repo_full_name, snapshot_date), 只能存一份:
    # 用 daily 榜单圈定仓库范围 (没有 daily 时退回第一个有数据的窗口)。
    primary_period = "daily" if "daily" in frames else next(iter(frames))
    trending = frames[primary_period]
    snapshots = load_repo_snapshots(engine, days=days + max(STAR_VELOCITY_WINDOWS))
    stars = star_source(trending, snapshots)

    # 指标层需要同时看到所有窗口: 7d/30d 速度来自 weekly/monthly 的区间增量。
    all_periods = pd.concat(frames.values(), ignore_index=True)
    metrics_frame = build_metrics_frame(
        all_periods, stars, period=primary_period, language=language
    )
    rows = to_repo_metrics(metrics_frame)
    written = upsert_repo_metrics(engine, rows)
    logger.info(
        "repo_metrics upserted=%d (primary period=%s, language=%r)",
        written,
        primary_period,
        language,
    )

    paths = [export_metrics_frame(metrics_frame, output_dir)]
    for period, trending_period in frames.items():
        paths.append(export_language_share(trending_period, period, output_dir))
        paths.append(export_rank_momentum(trending_period, period, language, output_dir))
    for window_days in STAR_VELOCITY_WINDOWS:
        paths.append(export_star_velocity_top(metrics_frame, window_days, output_dir))
    report = build_markdown_report(
        trending,
        metrics_frame,
        period=primary_period,
        language=language,
        details=load_latest_repo_details(engine),
    )
    paths.append(export_markdown_report(report, primary_period, output_dir))
    for path in paths:
        logger.info("report ready: %s", path)

    for window_days in STAR_VELOCITY_WINDOWS:
        column = star_velocity_column(window_days)
        if column in metrics_frame.columns:
            ranked = metrics_frame.dropna(subset=[column])
        else:
            ranked = metrics_frame.iloc[0:0]
        if not ranked.empty:
            top = ranked.sort_values(column, ascending=False).head(3)
            logger.info(
                "%s top3: %s",
                column,
                ", ".join(
                    f"{row.repo_full_name}={getattr(row, column):.1f}" for row in top.itertuples()
                ),
            )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: returns a process exit code, never raises."""
    args = parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level)
    return run(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
