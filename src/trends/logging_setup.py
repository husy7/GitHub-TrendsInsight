"""Logging configuration shared by the script entry points."""

from __future__ import annotations

import logging
import sys
import time

_LOG_FORMAT = "%(asctime)sZ | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def setup_logging(level: str) -> None:
    """Configure root logging with a UTC ISO8601 timestamp format.

    Called once by every script entry point (`scripts/collect.py`,
    `scripts/analyze.py`). Unknown levels fall back to `INFO`.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.strip().upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
        stream=sys.stdout,
        force=True,
    )
    # 统一使用 UTC, 与 `snapshot_date` 的 UTC 约定保持一致。
    logging.Formatter.converter = time.gmtime
    logging.getLogger(__name__).debug("logging configured at level=%s", level)
