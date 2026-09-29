"""Report builders and CSV writers (AGENTS.md §8.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from trends.analysis.reports import (
    METRICS_FILENAME,
    build_markdown_report,
    build_metrics_frame,
    export_language_share,
    export_markdown_report,
    export_metrics_frame,
    export_rank_momentum,
    export_star_velocity_top,
    language_share_filename,
    markdown_report_filename,
    rank_momentum_filename,
    star_velocity_filename,
    to_repo_metrics,
    write_dataframe,
)

REPORT_FIELDS = [
    "repo_full_name",
    "snapshot_date",
    "rank",
    "period",
    "language",
    "stars",
    "forks",
    "stars_in_period",
    "description",
    "url",
]

TRENDING_FIELDS = ["repo_full_name", "snapshot_date", "rank", "period", "language"]
SNAPSHOT_FIELDS = ["repo_full_name", "snapshot_date", "stars"]


def trending_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("a/one", "2026-09-01", 5, "daily", ""),
            ("a/one", "2026-09-08", 3, "daily", ""),
            ("b/two", "2026-09-08", 1, "daily", ""),
        ],
        columns=TRENDING_FIELDS,
    )


def snapshot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("a/one", "2026-09-01", 100),
            ("a/one", "2026-09-08", 170),
            ("b/two", "2026-09-08", 50),
        ],
        columns=SNAPSHOT_FIELDS,
    )


def test_filenames() -> None:
    assert star_velocity_filename(7) == "star_velocity_top7d.csv"
    assert star_velocity_filename(30) == "star_velocity_top30d.csv"
    assert rank_momentum_filename("daily", "python") == "rank_momentum_daily_python.csv"
    assert rank_momentum_filename("daily", "") == "rank_momentum_daily_all.csv"
    assert language_share_filename("daily") == "language_share_daily.csv"
    assert language_share_filename("weekly") == "language_share_weekly.csv"
    assert markdown_report_filename("daily") == "trending_report_daily.md"


def test_write_dataframe_creates_parent_and_skips_index(tmp_path: Path) -> None:
    path = write_dataframe(pd.DataFrame({"a": [1]}), tmp_path / "nested" / "out.csv")
    assert path.read_text(encoding="utf-8") == "a\n1\n"


def test_build_metrics_frame_joins_every_metric() -> None:
    frame = build_metrics_frame(trending_frame(), snapshot_frame(), period="daily", language="")
    assert list(frame.columns) == [
        "repo_full_name",
        "snapshot_date",
        "star_velocity_7d",
        "star_velocity_30d",
        "rank_momentum",
        "language_share",
    ]
    records = {
        (row["repo_full_name"], row["snapshot_date"]): row for row in frame.to_dict("records")
    }
    latest = records[("a/one", "2026-09-08")]
    assert latest["star_velocity_7d"] == 10.0
    assert latest["rank_momentum"] == 2
    assert latest["language_share"] == 1.0

    first_day = records[("a/one", "2026-09-01")]
    assert pd.isna(first_day["star_velocity_7d"])
    assert pd.isna(first_day["rank_momentum"])


def test_build_metrics_frame_without_star_history_keeps_language_share() -> None:
    trending = pd.DataFrame([("a/one", "2026-09-01", 1, "daily", "")], columns=TRENDING_FIELDS)
    empty = pd.DataFrame(columns=SNAPSHOT_FIELDS)
    frame = build_metrics_frame(trending, empty, period="daily", language="")
    assert frame["star_velocity_7d"].isna().all()
    assert frame["star_velocity_30d"].isna().all()
    assert frame["rank_momentum"].isna().all()
    # language_share 只依赖 trending, 因此没有 star 历史时依然可计算。
    assert frame["language_share"].tolist() == [1.0]


def test_build_metrics_frame_keeps_missing_rows_out() -> None:
    trending = pd.DataFrame([("a/one", "2026-09-08", 1, "weekly", "")], columns=TRENDING_FIELDS)
    frame = build_metrics_frame(trending, snapshot_frame(), period="daily", language="")
    assert frame.empty


def test_to_repo_metrics_maps_missing_values_to_none() -> None:
    frame = build_metrics_frame(trending_frame(), snapshot_frame(), period="daily", language="")
    rows = to_repo_metrics(frame)
    assert len(rows) == 3
    latest = next(
        row for row in rows if row.repo_full_name == "a/one" and row.snapshot_date == "2026-09-08"
    )
    assert latest.star_velocity_7d == 10.0
    assert latest.star_velocity_30d is None
    assert latest.rank_momentum == 2
    assert latest.language_share == 1.0

    first_day = next(
        row for row in rows if row.repo_full_name == "a/one" and row.snapshot_date == "2026-09-01"
    )
    assert first_day.star_velocity_7d is None
    assert first_day.rank_momentum is None


def test_export_language_share_writes_csv(tmp_path: Path) -> None:
    path = export_language_share(trending_frame(), "daily", tmp_path)
    assert path.name == "language_share_daily.csv"
    frame = pd.read_csv(path)
    assert list(frame.columns) == ["snapshot_date", "language", "language_share"]


def test_export_star_velocity_top_keeps_latest_day_and_limit(tmp_path: Path) -> None:
    metrics = pd.DataFrame(
        [
            ("a/one", "2026-09-01", 5.0),
            ("a/one", "2026-09-08", 10.0),
            ("b/two", "2026-09-08", 4.0),
            ("c/three", "2026-09-08", 20.0),
        ],
        columns=["repo_full_name", "snapshot_date", "star_velocity_7d"],
    )
    path = export_star_velocity_top(metrics, 7, tmp_path, top_n=2)
    frame = pd.read_csv(path)
    assert frame["repo_full_name"].tolist() == ["c/three", "a/one"]
    assert frame["star_velocity_7d"].tolist() == [20.0, 10.0]
    assert set(frame["snapshot_date"]) == {"2026-09-08"}


def test_export_star_velocity_top_handles_empty_input(tmp_path: Path) -> None:
    path = export_star_velocity_top(pd.DataFrame(), 7, tmp_path)
    assert path.exists()
    assert pd.read_csv(path).empty


def test_export_star_velocity_top_ignores_rows_without_velocity(tmp_path: Path) -> None:
    metrics = pd.DataFrame(
        [
            ("a/one", "2026-09-08", None),
            ("b/two", "2026-09-08", 4.0),
        ],
        columns=["repo_full_name", "snapshot_date", "star_velocity_7d"],
    )
    frame = pd.read_csv(export_star_velocity_top(metrics, 7, tmp_path))
    assert frame["repo_full_name"].tolist() == ["b/two"]


def period_trending_frame() -> pd.DataFrame:
    """同一批仓库分别出现在 daily / weekly / monthly 榜上。"""
    return pd.DataFrame(
        [
            ("a/one", "2026-09-08", 3, "daily", "", None),
            ("b/two", "2026-09-08", 1, "daily", "", None),
            ("a/one", "2026-09-08", 3, "weekly", "", 700),
            ("b/two", "2026-09-08", 1, "weekly", "", 70),
            ("a/one", "2026-09-08", 3, "monthly", "", 3000),
        ],
        columns=[*TRENDING_FIELDS, "stars_in_period"],
    )


def test_build_metrics_frame_prefers_period_increment_over_history() -> None:
    frame = build_metrics_frame(
        period_trending_frame(), snapshot_frame(), period="daily", language=""
    )
    records = {row["repo_full_name"]: row for row in frame.to_dict("records")}
    # 700 / 7 = 100 天均, 而不是历史快照差分的 (170-100)/7。
    assert records["a/one"]["star_velocity_7d"] == 100.0
    assert records["a/one"]["star_velocity_30d"] == 100.0
    # b/two 只有 weekly 增量, monthly 缺失则整格留空。
    assert records["b/two"]["star_velocity_7d"] == 10.0
    assert pd.isna(records["b/two"]["star_velocity_30d"])


def test_build_metrics_frame_falls_back_to_history_without_increment() -> None:
    trending = pd.DataFrame(
        [("a/one", "2026-09-08", 3, "daily", "", None)],
        columns=[*TRENDING_FIELDS, "stars_in_period"],
    )
    frame = build_metrics_frame(trending, snapshot_frame(), period="daily", language="")
    assert frame.iloc[0]["star_velocity_7d"] == 10.0


def test_export_rank_momentum_writes_csv(tmp_path: Path) -> None:
    path = export_rank_momentum(trending_frame(), "daily", "", tmp_path)
    assert path.name == "rank_momentum_daily_all.csv"
    frame = pd.read_csv(path)
    # b/two 只有一天数据, 无前一 snapshot_date, 按 §8.1 整行省略。
    assert frame["repo_full_name"].tolist() == ["a/one"]


def test_export_metrics_frame_writes_csv(tmp_path: Path) -> None:
    frame = build_metrics_frame(trending_frame(), snapshot_frame(), period="daily", language="")
    path = export_metrics_frame(frame, tmp_path)
    assert path.name == METRICS_FILENAME
    assert len(pd.read_csv(path)) == len(frame)


def report_trending_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            (
                "a/one",
                "2026-09-08",
                3,
                "daily",
                "",
                170,
                12,
                700,
                "A | tiny tool",
                "https://github.com/a/one",
            ),
            (
                "b/two",
                "2026-09-08",
                1,
                "daily",
                "",
                50,
                5,
                None,
                None,
                "https://github.com/b/two",
            ),
        ],
        columns=REPORT_FIELDS,
    )


def details_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "repo_full_name": "a/one",
                "snapshot_date": "2026-09-08",
                "stars": 170,
                "forks": 12,
                "open_issues": 3,
                "language": "rust",
                "topics_json": '["cli", "uv"]',
            },
            {
                "repo_full_name": "b/two",
                "snapshot_date": "2026-09-08",
                "stars": 50,
                "forks": 5,
                "open_issues": None,
                "language": None,
                "topics_json": "not-json",
            },
        ]
    )


def test_build_markdown_report_covers_description_links_and_metrics() -> None:
    trending = report_trending_frame()
    metrics = build_metrics_frame(trending, snapshot_frame(), period="daily", language="")
    report = build_markdown_report(
        trending,
        metrics,
        period="daily",
        language="",
        details=details_frame(),
        generated_at=datetime(2026, 9, 29, 8, 6, 35, tzinfo=UTC),
    )

    assert report.startswith("# GitHub Trending 洞察报告 · 2026-09-08")
    assert "生成时间 (UTC): `2026-09-29T08:06:35Z`" in report
    assert "https://github.com/trending?since=daily" in report
    assert "https://github.com/trending?since=weekly" in report
    # 链接 + 描述 (表格里的竖线被转义)
    assert "[a/one](https://github.com/a/one)" in report
    assert "[b/two](https://github.com/b/two)" in report
    assert "A \\| tiny tool" in report
    # 明细里的 topics 与缺失值
    assert "`cli`, `uv`" in report
    assert "—" in report
    # 速度来自历史快照差分 (170-100)/7
    assert "| 10.0 |" in report
    # 语言占比: 只有 a/one 取到仓库主语言, 共 2 个仓库 -> 50%
    assert "| rust | 1 | 50.0% |" in report
    # 只有一天数据时给出明确提示, 而不是编造动量
    assert "需要至少两个 `snapshot_date`" in report
    for section in ("## 1. 概览", "## 4. 语言占比", "## 5. 仓库明细", "## 6. 口径与方法"):
        assert section in report


def test_build_markdown_report_without_data() -> None:
    report = build_markdown_report(
        pd.DataFrame(columns=REPORT_FIELDS),
        pd.DataFrame(),
        period="daily",
        language="",
    )
    assert "当前没有可用的 `trending_snapshots` 数据" in report


def test_build_markdown_report_without_details() -> None:
    trending = report_trending_frame()
    metrics = build_metrics_frame(trending, snapshot_frame(), period="daily", language="")
    report = build_markdown_report(trending, metrics, period="daily", language="python")
    assert "language 筛选: python" in report
    assert "`cli`" not in report
    assert "—" in report


def test_export_markdown_report_writes_file(tmp_path: Path) -> None:
    path = export_markdown_report("# hello\n", "daily", tmp_path)
    assert path.name == "trending_report_daily.md"
    assert path.read_text(encoding="utf-8") == "# hello\n"
