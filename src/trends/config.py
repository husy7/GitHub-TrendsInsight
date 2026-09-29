"""Application settings and shared constants.

AGENTS.md §0 术语表是命名的唯一来源: 字段名必须使用 `repo_full_name` /
`snapshot_date` / `period` / `language` / `stars` / `forks` /
`star_velocity_7d` / `star_velocity_30d` / `rank_momentum` / `language_share`,
禁止使用同义词。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_NAME = "github-trends-insight"
USER_AGENT = PROJECT_NAME
GITHUB_API_VERSION = "2022-11-28"
GITHUB_API_BASE_URL = "https://api.github.com"
TRENDING_BASE_URL = "https://github.com/trending"
DEFAULT_DATABASE_URL = "sqlite:///data/trends.db"
RAW_RETENTION_DAYS = 90

# AGENTS.md §7.3 的重试默认值, 可通过环境变量覆盖。
DEFAULT_HTTP_TIMEOUT = 15.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_DELAY = 2.0
DEFAULT_MAX_DELAY = 60.0

TrendingPeriod = Literal["daily", "weekly", "monthly"]

TRENDING_PERIODS: tuple[TrendingPeriod, ...] = ("daily", "weekly", "monthly")

# 语言别名映射表: GitHub Trending 页面上的显示写法 -> 统一小写标识。
# 未登记的写法按「合并空白 + 转小写」处理, 保证 `language` 列含义一致。
LANGUAGE_ALIASES: dict[str, str] = {
    "cplusplus": "c++",
    "cpp": "c++",
    "csharp": "c#",
    "fsharp": "f#",
    "objective c": "objective-c",
    "objectivec": "objective-c",
    "objective c++": "objective-c++",
    "jupyter-notebook": "jupyter notebook",
    "jupyter": "jupyter notebook",
    "visual basic .net": "visual basic .net",
    "vb.net": "visual basic .net",
    "vbnet": "visual basic .net",
    "golang": "go",
    "shell script": "shell",
    "bash": "shell",
    "unknown": "",
}


def normalize_language(language: str | None) -> str:
    """Return the canonical lowercase `language` identifier.

    Empty/unknown values collapse to `""` so that the database `language`
    column never stores `NULL` for a missing language on the trending page.
    """
    if language is None:
        return ""
    cleaned = " ".join(language.split()).lower()
    if not cleaned:
        return ""
    return LANGUAGE_ALIASES.get(cleaned, cleaned)


def utc_snapshot_date(moment: datetime | None = None) -> str:
    """Return the UTC `snapshot_date` (`YYYY-MM-DD`) for `moment` (default: now)."""
    current = moment or datetime.now(tz=UTC)
    return current.astimezone(UTC).strftime("%Y-%m-%d")


def parse_periods(value: str | None) -> tuple[TrendingPeriod, ...]:
    """Parse `daily,weekly,monthly` (or `all`) into canonical period order.

    `None`/空字符串/`all` 都表示三个窗口全都要; 未登记的取值直接报错,
    避免采集脚本静默跳过某个窗口。
    """
    if value is None:
        return TRENDING_PERIODS
    parts = [part.strip().lower() for part in re.split(r"[,\s]+", value) if part.strip()]
    if not parts or "all" in parts:
        return TRENDING_PERIODS
    unsupported = sorted({part for part in parts if part not in TRENDING_PERIODS})
    if unsupported:
        raise ValueError(f"unsupported period(s): {', '.join(unsupported)}")
    selected: list[TrendingPeriod] = [known for known in TRENDING_PERIODS if known in parts]
    return tuple(selected) or TRENDING_PERIODS


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    github_token: str = ""
    database_url: str = DEFAULT_DATABASE_URL
    log_level: str = "INFO"
    trending_period: str = "daily,weekly,monthly"
    trending_language: str = ""
    http_timeout: float = DEFAULT_HTTP_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    base_delay: float = DEFAULT_BASE_DELAY
    max_delay: float = DEFAULT_MAX_DELAY

    @property
    def github_headers(self) -> dict[str, str]:
        """Headers required by AGENTS.md §7.1 for every GitHub API request."""
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "Authorization": f"Bearer {self.github_token}",
            "User-Agent": USER_AGENT,
        }

    @field_validator("trending_period")
    @classmethod
    def _validate_trending_period(cls, value: str) -> str:
        parse_periods(value)
        return value

    @property
    def trending_periods(self) -> tuple[TrendingPeriod, ...]:
        """`TRENDING_PERIOD` 展开后的 period 列表 (`daily,weekly,monthly`)。"""
        return parse_periods(self.trending_period)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
