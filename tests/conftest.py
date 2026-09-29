"""Shared pytest fixtures.

AGENTS.md §6/§10: 测试不得读取真实 `GITHUB_TOKEN`, 不得打真实网络,
不得依赖真实数据库。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from trends.config import get_settings
from trends.storage.db import get_engine, init_db

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def fake_github_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test runs with a fake token and a cleared settings cache."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def trending_daily_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "trending_daily.html").read_text(encoding="utf-8")


@pytest.fixture
def trending_python_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "trending_python.html").read_text(encoding="utf-8")


@pytest.fixture
def repo_api_payload(fixtures_dir: Path) -> dict[str, object]:
    payload: dict[str, object] = json.loads(
        (fixtures_dir / "repo_api_response.json").read_text(encoding="utf-8")
    )
    return payload


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    instance = get_engine(f"sqlite:///{tmp_path / 'trends.db'}")
    init_db(instance)
    yield instance
    instance.dispose()
