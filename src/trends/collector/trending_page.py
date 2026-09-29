"""Parse `https://github.com/trending` HTML (AGENTS.md §7.2).

GitHub 没有 Trending API, 所以这一层用 BeautifulSoup 解析 HTML 卡片。
所有字段严格使用术语表标识符: `repo_full_name` / `stars` / `forks` /
`language` / `description`。
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from trends.collector.rate_limit import compute_backoff_seconds
from trends.config import (
    DEFAULT_BASE_DELAY,
    DEFAULT_MAX_DELAY,
    DEFAULT_MAX_RETRIES,
    TRENDING_BASE_URL,
    USER_AGENT,
    normalize_language,
)

logger = logging.getLogger(__name__)

REPO_CARD_SELECTOR = "article.Box-row"
REPO_LINK_SELECTOR = "h2.h3 a"
DESCRIPTION_SELECTOR = "p.col-9"
LANGUAGE_SELECTOR = 'span[itemprop="programmingLanguage"]'
STARS_SELECTOR = 'a[href$="/stargazers"]'
FORKS_SELECTOR = 'a[href$="/forks"]'
STARS_TODAY_SELECTOR = "span.d-inline-block.float-sm-right"

_NUMBER_PATTERN = re.compile(r"(\d[\d,]*(?:\.\d+)?\s*[kKmM]?)")
_SUFFIX_MULTIPLIERS = {"k": 1_000, "m": 1_000_000}


@dataclass(frozen=True, slots=True)
class TrendingEntry:
    """One repository card from the trending page."""

    rank: int
    repo_full_name: str
    url: str
    description: str | None
    language: str | None
    stars: int | None
    forks: int | None
    stars_today: int | None


def build_trending_url(
    period: str,
    language: str = "",
    spoken_language_code: str = "",
) -> str:
    """Build the trending URL; the language filter lives in the path."""
    url = TRENDING_BASE_URL
    if language:
        url = f"{url}/{quote(language, safe='')}"
    parameters = {"since": period}
    if spoken_language_code:
        parameters["spoken_language_code"] = spoken_language_code
    return f"{url}?{urlencode(parameters)}"


def parse_number(text: str | None) -> int | None:
    """Parse `1,234` / `1.2k` / `3M`; return `None` when nothing parses.

    Numbers that cannot be parsed are never converted to `0` (AGENTS.md §7.4).
    """
    if text is None:
        return None
    match = _NUMBER_PATTERN.search(text)
    if match is None:
        return None
    raw = match.group(1).replace(",", "").replace(" ", "")
    multiplier = 1
    if raw and raw[-1].lower() in _SUFFIX_MULTIPLIERS:
        multiplier = _SUFFIX_MULTIPLIERS[raw[-1].lower()]
        raw = raw[:-1]
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value * multiplier)


def _tag_text(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    text = tag.get_text(strip=True)
    return text or None


def _extract_repo_full_name(article: Tag) -> str | None:
    link = article.select_one(REPO_LINK_SELECTOR) or article.select_one("h2 a")
    href = link.get("href") if link is not None else None
    if not isinstance(href, str):
        return None
    candidate = href.strip("/")
    if "/" not in candidate:
        return None
    return candidate


def parse_trending_html(
    html: str,
    *,
    period: str,
    language: str = "",
) -> list[TrendingEntry]:
    """Parse trending cards into `TrendingEntry` rows.

    `period` and `language` are carried through unchanged; the language
    filter cannot be recovered from the HTML itself.
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: list[TrendingEntry] = []
    for position, article in enumerate(soup.select(REPO_CARD_SELECTOR), start=1):
        repo_full_name = _extract_repo_full_name(article)
        if repo_full_name is None:
            logger.warning("skipping trending card without repository link (position=%d)", position)
            continue
        language_text = _tag_text(article.select_one(LANGUAGE_SELECTOR))
        entries.append(
            TrendingEntry(
                rank=position,
                repo_full_name=repo_full_name,
                url=f"https://github.com/{repo_full_name}",
                description=_tag_text(article.select_one(DESCRIPTION_SELECTOR)),
                language=normalize_language(language_text) or None,
                stars=parse_number(_tag_text(article.select_one(STARS_SELECTOR))),
                forks=parse_number(_tag_text(article.select_one(FORKS_SELECTOR))),
                stars_today=parse_number(_tag_text(article.select_one(STARS_TODAY_SELECTOR))),
            )
        )
    logger.info(
        "parsed %d trending repositories (period=%s, language=%r)", len(entries), period, language
    )
    return entries


def fetch_trending_html(
    client: httpx.Client,
    *,
    period: str,
    language: str = "",
    spoken_language_code: str = "",
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    sleep: Callable[[float], None] = time.sleep,
    jitter: float | None = None,
) -> str:
    """Fetch the trending page HTML without touching the GitHub REST API.

    HTML 抓取没有 API 的 rate limit, 但同样要抗抖动: 网络错误与 5xx 使用
    §7.3 的退避参数重试, 最终失败则抛出 `httpx.HTTPError` 交由入口脚本报告。
    """
    url = build_trending_url(period, language, spoken_language_code)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    attempt = 0
    while True:
        try:
            response = client.get(url, headers=headers, follow_redirects=True)
        except httpx.TransportError as error:
            if attempt >= max_retries:
                raise
            delay = compute_backoff_seconds(
                attempt, base_delay=base_delay, max_delay=max_delay, jitter=jitter
            )
            logger.warning(
                "trending page request failed (%s); retrying in %.2fs (attempt=%d/%d)",
                error,
                delay,
                attempt + 1,
                max_retries,
            )
            sleep(delay)
            attempt += 1
            continue
        if response.status_code >= 500 and attempt < max_retries:
            delay = compute_backoff_seconds(
                attempt, base_delay=base_delay, max_delay=max_delay, jitter=jitter
            )
            logger.warning(
                "trending page returned %s; retrying in %.2fs (attempt=%d/%d)",
                response.status_code,
                delay,
                attempt + 1,
                max_retries,
            )
            sleep(delay)
            attempt += 1
            continue
        response.raise_for_status()
        logger.info("fetched trending page: %s (%d bytes)", url, len(response.content))
        return response.text
