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
    build_metrics_frame,
    export_language_share,
    export_metrics_frame,
    export_rank_momentum,
    export_star_velocity_top,
    to_repo_metrics,
)
from trends.config import (
    TRENDING_PERIODS,
    Settings,
    get_settings,
    normalize_language,
)
from trends.logging_setup import setup_logging
from trends.storage.db import (
    get_engine,
    init_db,
    load_repo_snapshots,
    load_trending_snapshots,
    upsert_repo_metrics,
)

logger = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze collected trending snapshots")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--period", choices=list(TRENDING_PERIODS), default=None)
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
    period = args.period or settings.trending_period
    raw_language = args.language if args.language is not None else settings.trending_language
    language = normalize_language(raw_language)
    database_url = args.database_url or settings.database_url
    output_dir = Path(args.output_dir)
    days = max(args.days, 1)

    engine = get_engine(database_url)
    init_db(engine)

    trending = load_trending_snapshots(engine, period=period, days=days)
    if trending.empty:
        logger.error("no trending_snapshots for period=%s within %d days", period, days)
        return 1
    snapshots = load_repo_snapshots(engine, days=days + max(STAR_VELOCITY_WINDOWS))
    stars = star_source(trending, snapshots)

    metrics_frame = build_metrics_frame(trending, stars, period=period, language=language)
    rows = to_repo_metrics(metrics_frame)
    written = upsert_repo_metrics(engine, rows)
    logger.info("repo_metrics upserted=%d (period=%s, language=%r)", written, period, language)

    paths = [
        export_metrics_frame(metrics_frame, output_dir),
        export_language_share(trending, period, output_dir),
        export_rank_momentum(trending, period, language, output_dir),
    ]
    for window_days in STAR_VELOCITY_WINDOWS:
        paths.append(export_star_velocity_top(stars, window_days, output_dir))
    for path in paths:
        logger.info("report ready: %s", path)

    for window_days in STAR_VELOCITY_WINDOWS:
        column = star_velocity_column(window_days)
        if column in metrics_frame.columns and metrics_frame[column].notna().any():
            top = metrics_frame.sort_values(column, ascending=False).head(3)
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
