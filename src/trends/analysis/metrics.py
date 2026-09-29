"""Pure metric functions (AGENTS.md §8.1).

函数无副作用、无 IO; 数据不足时整行省略, 不写 `NA`、不写 0。
输入输出列名严格使用术语表标识符。
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

SNAPSHOT_COLUMNS = ("repo_full_name", "snapshot_date", "stars")
TRENDING_COLUMNS = ("repo_full_name", "snapshot_date", "rank", "period", "language")
PERIOD_TRENDING_COLUMNS = ("repo_full_name", "snapshot_date", "stars_in_period", "period")
LANGUAGE_SHARE_COLUMNS = ("language", "snapshot_date", "period")


def star_velocity_column(window_days: int) -> str:
    """Return the velocity column name, e.g. `star_velocity_7d`."""
    return f"star_velocity_{window_days}d"


def _require_columns(frame: pd.DataFrame, required: Sequence[str], function_name: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{function_name}: missing required columns {missing}")


def _empty_frame(columns: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="float64") for column in columns})


def compute_star_velocity(
    snapshots: pd.DataFrame,
    window_days: int,
) -> pd.DataFrame:
    """
    Input columns:  repo_full_name, snapshot_date, stars
    Output columns: repo_full_name, snapshot_date, star_velocity_{window_days}d
    Missing window: row omitted (do not fill 0).
    """
    _require_columns(snapshots, SNAPSHOT_COLUMNS, "compute_star_velocity")
    if window_days <= 0:
        raise ValueError("window_days must be a positive integer")
    velocity_column = star_velocity_column(window_days)
    output_columns = ["repo_full_name", "snapshot_date", velocity_column]
    if snapshots.empty:
        return _empty_frame(output_columns)

    frame = snapshots.loc[:, list(SNAPSHOT_COLUMNS)].copy()
    frame["_snapshot_day"] = pd.to_datetime(frame["snapshot_date"], errors="coerce")
    frame = frame.dropna(subset=["_snapshot_day", "repo_full_name"])
    frame = frame.drop_duplicates(subset=["repo_full_name", "_snapshot_day"], keep="last")
    frame["_window_day"] = frame["_snapshot_day"] - pd.Timedelta(days=window_days)
    # 只有数据集中恰好存在 window_days 天前的快照时才有基线, 否则整行省略。
    baseline = frame.loc[:, ["repo_full_name", "_snapshot_day", "stars"]].rename(
        columns={"_snapshot_day": "_window_day", "stars": "_baseline_stars"}
    )
    merged = frame.merge(baseline, on=["repo_full_name", "_window_day"], how="inner")
    merged = merged.dropna(subset=["stars", "_baseline_stars"])
    if merged.empty:
        return _empty_frame(output_columns)

    result = pd.DataFrame(
        {
            "repo_full_name": merged["repo_full_name"],
            "snapshot_date": merged["snapshot_date"],
            velocity_column: (merged["stars"] - merged["_baseline_stars"]) / float(window_days),
        }
    )
    return result.sort_values(["repo_full_name", "snapshot_date"], kind="stable").reset_index(
        drop=True
    )


def compute_rank_momentum(
    trending: pd.DataFrame,
    period: str,
    language: str,
) -> pd.DataFrame:
    """
    Input columns:  repo_full_name, snapshot_date, rank, period, language
    Output columns: repo_full_name, snapshot_date, rank_momentum
    previous_rank 取同 period + 同 language 下前一 snapshot_date 的 rank。
    无前一日数据: row omitted。
    """
    _require_columns(trending, TRENDING_COLUMNS, "compute_rank_momentum")
    output_columns = ["repo_full_name", "snapshot_date", "rank_momentum"]
    if trending.empty:
        return _empty_frame(output_columns)
    subset = trending.loc[(trending["period"] == period) & (trending["language"] == language)]
    if subset.empty:
        return _empty_frame(output_columns)

    frame = subset.loc[:, ["repo_full_name", "snapshot_date", "rank"]].copy()
    frame["_snapshot_day"] = pd.to_datetime(frame["snapshot_date"], errors="coerce")
    frame = frame.dropna(subset=["_snapshot_day", "repo_full_name", "rank"])
    frame = frame.drop_duplicates(subset=["repo_full_name", "_snapshot_day"], keep="last")
    frame = frame.sort_values(["repo_full_name", "_snapshot_day"], kind="stable")
    frame["_previous_rank"] = frame.groupby("repo_full_name", sort=False)["rank"].shift(1)
    frame = frame.dropna(subset=["_previous_rank"])
    if frame.empty:
        return _empty_frame(output_columns)

    # 正数表示排名上升 (上升 3 名 -> 3), 负数表示下滑。
    result = pd.DataFrame(
        {
            "repo_full_name": frame["repo_full_name"],
            "snapshot_date": frame["snapshot_date"],
            "rank_momentum": (frame["_previous_rank"] - frame["rank"]).astype("int64"),
        }
    )
    return result.sort_values(["repo_full_name", "snapshot_date"], kind="stable").reset_index(
        drop=True
    )


def compute_language_share(
    trending: pd.DataFrame,
    period: str,
) -> pd.DataFrame:
    """
    Input columns:  language, snapshot_date, period
    Output columns: snapshot_date, language, language_share
    language_share = 当日该语言仓库数 / 当日全部趋势仓库数。
    """
    _require_columns(trending, LANGUAGE_SHARE_COLUMNS, "compute_language_share")
    output_columns = ["snapshot_date", "language", "language_share"]
    if trending.empty:
        return _empty_frame(output_columns)
    subset = trending.loc[trending["period"] == period, ["snapshot_date", "language"]].copy()
    if subset.empty:
        return _empty_frame(output_columns)

    subset["language"] = subset["language"].fillna("")
    grouped = (
        subset.groupby(["snapshot_date", "language"], dropna=False)
        .size()
        .reset_index(name="_repo_count")
    )
    totals = subset.groupby("snapshot_date").size().reset_index(name="_total_count")
    merged = grouped.merge(totals, on="snapshot_date", how="left")
    result = pd.DataFrame(
        {
            "snapshot_date": merged["snapshot_date"],
            "language": merged["language"],
            "language_share": merged["_repo_count"] / merged["_total_count"],
        }
    )
    return result.sort_values(["snapshot_date", "language"], kind="stable").reset_index(drop=True)


def compute_period_star_velocity(
    trending: pd.DataFrame,
    period: str,
    window_days: int,
) -> pd.DataFrame:
    """
    Input columns:  repo_full_name, snapshot_date, stars_in_period, period
    Output columns: repo_full_name, snapshot_date, star_velocity_{window_days}d
    star_velocity = stars_in_period / window_days。

    周期增量口径: weekly 榜单给的是近 7 天增量, monthly 是近 30 天增量, 所以首次
    采集当天就能算出速度, 不必等历史快照。缺失 `stars_in_period` 的行整体省略。
    """
    _require_columns(trending, PERIOD_TRENDING_COLUMNS, "compute_period_star_velocity")
    if window_days <= 0:
        raise ValueError("window_days must be a positive integer")
    velocity_column = star_velocity_column(window_days)
    output_columns = ["repo_full_name", "snapshot_date", velocity_column]
    if trending.empty:
        return _empty_frame(output_columns)
    subset = trending.loc[
        (trending["period"] == period) & trending["stars_in_period"].notna(),
        ["repo_full_name", "snapshot_date", "stars_in_period"],
    ]
    if subset.empty:
        return _empty_frame(output_columns)
    subset = subset.drop_duplicates(subset=["repo_full_name", "snapshot_date"], keep="last")
    result = pd.DataFrame(
        {
            "repo_full_name": subset["repo_full_name"],
            "snapshot_date": subset["snapshot_date"],
            velocity_column: subset["stars_in_period"].astype("float64") / float(window_days),
        }
    )
    return result.sort_values(["repo_full_name", "snapshot_date"], kind="stable").reset_index(
        drop=True
    )
