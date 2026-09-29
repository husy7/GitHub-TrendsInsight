"""End-to-end test: mocked HTTP -> SQLite -> CSV reports.

两个入口脚本都以真实 CLI 参数运行, 但所有 HTTP 请求由 `respx` mock,
不接触真实网络与真实 Token (AGENTS.md §10)。
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import httpx
import pandas as pd
import pytest
import respx
from sqlalchemy import Engine

from trends.config import utc_snapshot_date
from trends.storage.db import (
    get_engine,
    init_db,
    insert_repo_snapshots,
    insert_trending_snapshots,
    load_failed_repos,
    load_repo_metrics,
    load_trending_snapshots,
)
from trends.storage.models import RepoSnapshot, TrendingSnapshot

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
DAILY_REPOS = {
    "openai/whisper": 12_345,
    "langchain-ai/langchain": 45_600,
    "microsoft/PowerToys": 78_901,
    "astral-sh/uv": 101_200,
}


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"script_{name}", SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def collect_script() -> ModuleType:
    return load_script("collect")


@pytest.fixture
def analyze_script() -> ModuleType:
    return load_script("analyze")


@pytest.fixture
def temp_engine(tmp_path: Path) -> Iterator[tuple[Engine, str]]:
    database_url = f"sqlite:///{tmp_path / 'trends.db'}"
    engine = get_engine(database_url)
    yield engine, database_url
    engine.dispose()


@respx.mock
def test_collect_then_analyze_end_to_end(
    collect_script: ModuleType,
    analyze_script: ModuleType,
    temp_engine: tuple[Engine, str],
    tmp_path: Path,
    trending_daily_html: str,
    repo_api_payload: dict[str, object],
) -> None:
    engine, database_url = temp_engine
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "processed"

    for period in ("daily", "weekly", "monthly"):
        respx.get(f"https://github.com/trending?since={period}").mock(
            return_value=httpx.Response(200, text=trending_daily_html)
        )

    def repo_handler(request: httpx.Request) -> httpx.Response:
        repo_full_name = request.url.path.removeprefix("/repos/")
        payload = dict(repo_api_payload)
        payload["full_name"] = repo_full_name
        payload["html_url"] = f"https://github.com/{repo_full_name}"
        payload["stargazers_count"] = DAILY_REPOS[repo_full_name]
        return httpx.Response(200, json=payload, headers={"X-RateLimit-Remaining": "4999"})

    respx.get(url__startswith="https://api.github.com/repos/").mock(side_effect=repo_handler)

    exit_code = collect_script.main(
        [
            "--period",
            "daily,weekly,monthly",
            "--language",
            "",
            "--database-url",
            database_url,
            "--raw-dir",
            str(raw_dir),
        ]
    )
    assert exit_code == 0

    snapshot_date = utc_snapshot_date()
    trending = load_trending_snapshots(engine)
    assert set(trending["period"]) == {"daily", "weekly", "monthly"}
    assert sorted(set(trending["repo_full_name"])) == sorted(DAILY_REPOS)
    assert len(trending) == 12  # 4 个仓库 x 3 个窗口
    assert set(trending["snapshot_date"]) == {snapshot_date}
    assert set(trending["language"]) == {""}
    # 卡片上的区间新增落库到 stars_in_period。
    assert trending["stars_in_period"].notna().all()
    assert load_failed_repos(engine).empty

    # 原始响应按天归档, 每个窗口一份; 仓库详情跨窗口去重只请求一次。
    for period in ("daily", "weekly", "monthly"):
        assert (raw_dir / snapshot_date / f"trending_{period}_all.gz").exists()
    assert len(list((raw_dir / snapshot_date / "repos").glob("*.gz"))) == 4

    # 再补一天前的主榜单快照, 让 rank_momentum 有前一天可比。
    yesterday = utc_snapshot_date(datetime.now(tz=UTC) - timedelta(days=1))
    insert_trending_snapshots(
        engine,
        [
            TrendingSnapshot(
                snapshot_date=yesterday,
                period="daily",
                language="",
                rank=index,
                repo_full_name=repo_full_name,
                stars=stars - 5,
                forks=None,
                stars_in_period=None,
                description=None,
                url=f"https://github.com/{repo_full_name}",
            )
            for index, (repo_full_name, stars) in enumerate(sorted(DAILY_REPOS.items()), start=1)
        ],
    )

    assert (
        analyze_script.main(
            [
                "--days",
                "30",
                "--period",
                "daily,weekly,monthly",
                "--language",
                "",
                "--database-url",
                database_url,
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    assert (output_dir / "repo_metrics.csv").exists()
    for period in ("daily", "weekly", "monthly"):
        assert (output_dir / f"language_share_{period}.csv").exists()
        assert (output_dir / f"rank_momentum_{period}_all.csv").exists()

    metrics = load_repo_metrics(engine, days=30)
    assert len(metrics) == 8
    # 7d/30d 速度来自 weekly/monthly 卡片的区间增量, 首次采集当天即可算出。
    assert metrics["star_velocity_7d"].notna().sum() == 4
    assert metrics["star_velocity_30d"].notna().sum() == 4
    assert metrics["rank_momentum"].notna().sum() == 4

    velocity = pd.read_csv(output_dir / "star_velocity_top7d.csv")
    assert set(velocity["repo_full_name"]) == set(DAILY_REPOS)
    assert velocity["star_velocity_7d"].max() == pytest.approx(1234 / 7)
    monthly = pd.read_csv(output_dir / "star_velocity_top30d.csv")
    assert monthly["star_velocity_30d"].max() == pytest.approx(1234 / 30)

    share = pd.read_csv(output_dir / "language_share_daily.csv")
    latest_share = share.loc[share["snapshot_date"] == snapshot_date]
    assert latest_share["language_share"].tolist() == [1.0]


def test_analyze_falls_back_to_snapshot_history(
    analyze_script: ModuleType,
    temp_engine: tuple[Engine, str],
    tmp_path: Path,
) -> None:
    """没有区间增量 (老数据) 时, 7d 速度仍可用历史快照差分算出来。"""
    engine, database_url = temp_engine
    init_db(engine)
    output_dir = tmp_path / "processed"
    today = utc_snapshot_date()
    seven_days_ago = utc_snapshot_date(datetime.now(tz=UTC) - timedelta(days=7))

    insert_trending_snapshots(
        engine,
        [
            TrendingSnapshot(
                snapshot_date=today,
                period="daily",
                language="",
                rank=1,
                repo_full_name="a/one",
                stars=170,
                forks=None,
                stars_in_period=None,
                description=None,
                url="https://github.com/a/one",
            )
        ],
    )
    insert_repo_snapshots(
        engine,
        [
            RepoSnapshot("a/one", seven_days_ago, 100, 1, 1, "python", "[]"),
            RepoSnapshot("a/one", today, 170, 1, 1, "python", "[]"),
        ],
    )

    exit_code = analyze_script.main(
        [
            "--days",
            "30",
            "--period",
            "daily",
            "--language",
            "",
            "--database-url",
            database_url,
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0
    velocity = pd.read_csv(output_dir / "star_velocity_top7d.csv")
    assert velocity["star_velocity_7d"].tolist() == [10.0]


def test_collect_without_token_reports_error(
    collect_script: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "")
    exit_code = collect_script.main(
        [
            "--period",
            "daily",
            "--database-url",
            f"sqlite:///{tmp_path / 'trends.db'}",
            "--raw-dir",
            str(tmp_path / "raw"),
        ]
    )
    assert exit_code == 1


@respx.mock
def test_collect_reports_network_failure(collect_script: ModuleType, tmp_path: Path) -> None:
    respx.get("https://github.com/trending?since=daily").mock(
        return_value=httpx.Response(500, text="boom")
    )
    exit_code = collect_script.main(
        [
            "--period",
            "daily",
            "--database-url",
            f"sqlite:///{tmp_path / 'trends.db'}",
            "--raw-dir",
            str(tmp_path / "raw"),
        ]
    )
    assert exit_code == 1


@respx.mock
def test_collect_aborts_when_trending_page_is_empty(
    collect_script: ModuleType, tmp_path: Path
) -> None:
    respx.get("https://github.com/trending?since=daily").mock(
        return_value=httpx.Response(200, text="<html><body></body></html>")
    )
    exit_code = collect_script.main(
        [
            "--period",
            "daily",
            "--database-url",
            f"sqlite:///{tmp_path / 'trends.db'}",
            "--raw-dir",
            str(tmp_path / "raw"),
        ]
    )
    assert exit_code == 1


def test_analyze_without_data_returns_error(analyze_script: ModuleType, tmp_path: Path) -> None:
    exit_code = analyze_script.main(
        [
            "--days",
            "30",
            "--period",
            "daily",
            "--database-url",
            f"sqlite:///{tmp_path / 'trends.db'}",
            "--output-dir",
            str(tmp_path / "processed"),
        ]
    )
    assert exit_code == 1


def test_collect_script_helpers() -> None:
    module = load_script("collect")
    assert module.safe_name("") == "all"
    assert module.safe_name("c++") == "c-"
    assert module.safe_name("openai/whisper") == "openai-whisper"
