"""Report builders and CSV writers for `data/processed/` (AGENTS.md §8.2)."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import pandas as pd

from trends.analysis.metrics import (
    compute_language_share,
    compute_rank_momentum,
    compute_star_velocity,
    star_velocity_column,
)
from trends.storage.models import RepoMetrics

logger = logging.getLogger(__name__)

DEFAULT_PROCESSED_DIR = Path("data/processed")
STAR_VELOCITY_WINDOWS: tuple[int, ...] = (7, 30)
LANGUAGE_SHARE_FILENAME = "daily_language_share.csv"
METRICS_FILENAME = "repo_metrics.csv"


def star_velocity_filename(window_days: int) -> str:
    """CSV name for one velocity window, e.g. `star_velocity_top7d.csv`."""
    return f"star_velocity_top{window_days}d.csv"


def rank_momentum_filename(period: str, language: str) -> str:
    """CSV name for one `period`/`language` pair."""
    return f"rank_momentum_{period}_{language or 'all'}.csv"


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
    """Write `daily_language_share.csv` for `period`."""
    share = compute_language_share(trending, period)
    return write_dataframe(share, output_dir / LANGUAGE_SHARE_FILENAME)


def export_star_velocity_top(
    snapshots: pd.DataFrame,
    window_days: int,
    output_dir: Path = DEFAULT_PROCESSED_DIR,
    top_n: int = 10,
) -> Path:
    """Write the latest-day `star_velocity_{window_days}d` top `top_n` rows."""
    velocity_column = star_velocity_column(window_days)
    velocity = compute_star_velocity(snapshots, window_days)
    path = output_dir / star_velocity_filename(window_days)
    if velocity.empty:
        return write_dataframe(velocity, path)
    latest_day = velocity["snapshot_date"].max()
    top = velocity.loc[velocity["snapshot_date"] == latest_day]
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
    """Join every §8.1 metric into one frame keyed by repo + `snapshot_date`."""
    scope = trending.loc[
        (trending["period"] == period) & (trending["language"] == language),
        ["repo_full_name", "snapshot_date"],
    ].drop_duplicates()
    frame = scope.reset_index(drop=True)
    for window_days in STAR_VELOCITY_WINDOWS:
        column = star_velocity_column(window_days)
        velocity = compute_star_velocity(snapshots, window_days)
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
