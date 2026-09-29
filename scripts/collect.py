"""Collect one trending snapshot plus repository details.

用法:
    uv run python scripts/collect.py --period daily --language ""
"""

from __future__ import annotations

import argparse
import logging
import re
from collections.abc import Sequence
from pathlib import Path

import httpx

from trends.collector.github_api import GitHubApiClient
from trends.collector.rate_limit import CollectorError
from trends.collector.trending_page import fetch_trending_html, parse_trending_html
from trends.config import (
    TRENDING_PERIODS,
    Settings,
    get_settings,
    normalize_language,
    utc_snapshot_date,
)
from trends.logging_setup import setup_logging
from trends.storage.db import (
    get_engine,
    init_db,
    insert_repo_snapshots,
    insert_trending_snapshots,
    record_failed_repos,
)
from trends.storage.models import RepoSnapshot, TrendingSnapshot
from trends.storage.raw_store import prune_raw_responses, save_raw_response

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")


def safe_name(value: str) -> str:
    """Filesystem-safe fragment for raw response names."""
    return re.sub(r"[^0-9A-Za-z._-]+", "-", value) or "all"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect GitHub trending snapshots")
    parser.add_argument("--period", choices=list(TRENDING_PERIODS), default=None)
    parser.add_argument("--language", default=None, help="语言筛选值, 空字符串表示全部")
    parser.add_argument("--spoken-language-code", default="")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    return parser.parse_args(argv)


def run(args: argparse.Namespace, settings: Settings) -> int:
    period = args.period or settings.trending_period
    raw_language = args.language if args.language is not None else settings.trending_language
    language = normalize_language(raw_language)
    database_url = args.database_url or settings.database_url
    raw_dir = Path(args.raw_dir)
    snapshot_date = utc_snapshot_date()

    if not settings.github_token.strip():
        raise CollectorError("GITHUB_TOKEN is missing: set it in .env before collecting")

    engine = get_engine(database_url)
    init_db(engine)

    with httpx.Client(timeout=settings.http_timeout) as http_client:
        html = fetch_trending_html(
            http_client,
            period=period,
            language=language,
            spoken_language_code=args.spoken_language_code,
            max_retries=settings.max_retries,
            base_delay=settings.base_delay,
            max_delay=settings.max_delay,
        )
    save_raw_response(
        raw_dir,
        snapshot_date,
        f"trending_{period}_{safe_name(language)}",
        html.encode("utf-8"),
    )

    entries = parse_trending_html(html, period=period, language=language)
    if not entries:
        raise CollectorError("trending page returned no repositories: check selectors or network")

    trending_rows = [
        TrendingSnapshot(
            snapshot_date=snapshot_date,
            period=period,
            language=language,
            rank=entry.rank,
            repo_full_name=entry.repo_full_name,
            stars=entry.stars,
            forks=entry.forks,
            description=entry.description,
            url=entry.url,
        )
        for entry in entries
    ]
    inserted = insert_trending_snapshots(engine, trending_rows)
    logger.info(
        "trending_snapshots inserted=%d/%d (snapshot_date=%s, period=%s, language=%r)",
        inserted,
        len(trending_rows),
        snapshot_date,
        period,
        language,
    )

    repo_rows: list[RepoSnapshot] = []
    with GitHubApiClient(
        token=settings.github_token,
        timeout=settings.http_timeout,
        max_retries=settings.max_retries,
        base_delay=settings.base_delay,
        max_delay=settings.max_delay,
    ) as api:
        for entry in entries:
            details = api.get_repo(entry.repo_full_name, snapshot_date=snapshot_date)
            payload = api.raw_payload(entry.repo_full_name)
            if payload is not None:
                save_raw_response(
                    raw_dir,
                    snapshot_date,
                    f"repo_{safe_name(entry.repo_full_name)}",
                    payload,
                    subdirectory="repos",
                )
            if details is None:
                continue
            repo_rows.append(
                RepoSnapshot(
                    repo_full_name=details.repo_full_name,
                    snapshot_date=snapshot_date,
                    stars=details.stars,
                    forks=details.forks,
                    open_issues=details.open_issues,
                    language=details.language,
                    topics_json=details.topics_json,
                )
            )
        failures = api.failed_repos
        rate_limit = api.rate_limit

    stored = insert_repo_snapshots(engine, repo_rows)
    record_failed_repos(engine, failures)
    logger.info(
        "repo_snapshots inserted=%d/%d, failed_repos=%d, requests=%d, rate_limit_remaining=%s",
        stored,
        len(repo_rows),
        len(failures),
        rate_limit.requests,
        rate_limit.latest.remaining,
    )

    pruned = prune_raw_responses(raw_dir)
    if pruned:
        logger.info("pruned %d expired raw directories", len(pruned))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: returns a process exit code, never raises."""
    args = parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level)
    try:
        return run(args, settings)
    except CollectorError as error:
        logger.error("collector stopped: %s", error)
        return 1
    except httpx.HTTPError as error:
        logger.error("network failure while collecting: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
