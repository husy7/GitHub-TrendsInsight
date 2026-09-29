"""Gzip raw-response store under `data/raw/` with a 90-day retention policy."""

from __future__ import annotations

import gzip
import logging
import shutil
from datetime import date, timedelta
from pathlib import Path

from trends.config import RAW_RETENTION_DAYS

logger = logging.getLogger(__name__)

SNAPSHOT_DATE_FORMAT = "%Y-%m-%d"


def snapshot_date_directory(raw_dir: Path, snapshot_date: str) -> Path:
    """Return (and create) the per-day directory inside `data/raw/`."""
    directory = Path(raw_dir) / snapshot_date
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_raw_response(
    raw_dir: Path,
    snapshot_date: str,
    name: str,
    payload: bytes,
    *,
    subdirectory: str | None = None,
) -> Path:
    """Write `payload` as `<name>.gz` and return the written path."""
    directory = snapshot_date_directory(raw_dir, snapshot_date)
    if subdirectory:
        directory = directory / subdirectory
        directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.gz"
    with gzip.open(path, "wb") as handle:
        handle.write(payload)
    logger.debug("raw response written to %s (%d bytes)", path, len(payload))
    return path


def iter_snapshot_date_directories(raw_dir: Path) -> list[tuple[date, Path]]:
    """Yield parsed `(snapshot_date, path)` pairs for valid day directories."""
    root = Path(raw_dir)
    if not root.is_dir():
        return []
    found: list[tuple[date, Path]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            parsed = date.fromisoformat(entry.name)
        except ValueError:
            logger.warning("skipping unrecognized raw directory: %s", entry)
            continue
        found.append((parsed, entry))
    return found


def prune_raw_responses(
    raw_dir: Path,
    *,
    retention_days: int = RAW_RETENTION_DAYS,
    today: date | None = None,
) -> list[Path]:
    """Delete day directories older than `retention_days` and return them.

    Only directories directly under `raw_dir` whose name parses as an ISO
    `snapshot_date` are considered, so unrelated files are never touched.
    """
    reference = today or date.today()
    cutoff = reference - timedelta(days=retention_days)
    removed: list[Path] = []
    for snapshot_day, path in iter_snapshot_date_directories(raw_dir):
        if snapshot_day >= cutoff:
            continue
        shutil.rmtree(path)
        removed.append(path)
        logger.info("pruned raw responses older than %s: %s", cutoff.isoformat(), path)
    return removed
