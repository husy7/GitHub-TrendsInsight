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

    respx.get("https://github.com/trending?since=daily").mock(
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
            "daily",
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
    trending = load_trending_snapshots(engine, period="daily")
    assert sorted(trending["repo_full_name"]) == sorted(DAILY_REPOS)
    assert set(trending["snapshot_date"]) == {snapshot_date}
    assert trending["language"].tolist() == [""] * 4
    assert load_failed_repos(engine).empty

    # 原始响应按天归档, gzip + repos/ 子目录。
    assert (raw_dir / snapshot_date / "trending_daily_all.gz").exists()
    assert len(list((raw_dir / snapshot_date / "repos").glob("*.gz"))) == 4

    # 造一天前与七天前的快照, 让 Star Velocity / rank_momentum 都有基线。
    seven_days_ago = utc_snapshot_date(datetime.now(tz=UTC) - timedelta(days=7))
    yesterday = utc_snapshot_date(datetime.now(tz=UTC) - timedelta(days=1))
    baseline: list[RepoSnapshot] = []
    for index, (repo_full_name, stars) in enumerate(sorted(DAILY_REPOS.items())):
        baseline.append(
            RepoSnapshot(
                repo_full_name=repo_full_name,
                snapshot_date=seven_days_ago,
                stars=stars - 70 * (index + 1),
                forks=1,
                open_issues=1,
                language="python",
                topics_json="[]",
            )
        )
        baseline.append(
            RepoSnapshot(
                repo_full_name=repo_full_name,
                snapshot_date=yesterday,
                stars=stars - 5,
                forks=1,
                open_issues=1,
                language="python",
                topics_json="[]",
            )
        )
    insert_repo_snapshots(engine, baseline)
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
                "daily",
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
    assert (output_dir / "daily_language_share.csv").exists()
    assert (output_dir / "rank_momentum_daily_all.csv").exists()

    metrics = load_repo_metrics(engine, days=30)
    assert len(metrics) == 8
    assert metrics["star_velocity_7d"].notna().sum() == 4
    assert metrics["rank_momentum"].notna().sum() == 4

    velocity = pd.read_csv(output_dir / "star_velocity_top7d.csv")
    assert set(velocity["repo_full_name"]) == set(DAILY_REPOS)
    assert velocity["star_velocity_7d"].max() == pytest.approx(40.0)

    share = pd.read_csv(output_dir / "daily_language_share.csv")
    latest_share = share.loc[share["snapshot_date"] == snapshot_date]
    assert latest_share["language_share"].tolist() == [1.0]


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
