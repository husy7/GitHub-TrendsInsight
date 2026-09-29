"""Raw gzip store and 90-day retention (AGENTS.md §7.4)."""

from __future__ import annotations

import gzip
from datetime import date
from pathlib import Path

from trends.storage.raw_store import (
    iter_snapshot_date_directories,
    prune_raw_responses,
    save_raw_response,
    snapshot_date_directory,
)


def test_save_raw_response_writes_readable_gzip(tmp_path: Path) -> None:
    path = save_raw_response(tmp_path, "2026-09-29", "trending_daily_all", b"<html></html>")
    assert path.name == "trending_daily_all.gz"
    assert gzip.decompress(path.read_bytes()) == b"<html></html>"


def test_save_raw_response_supports_subdirectory(tmp_path: Path) -> None:
    path = save_raw_response(tmp_path, "2026-09-29", "repo_a__b", b"{}", subdirectory="repos")
    assert path.parent == tmp_path / "2026-09-29" / "repos"
    assert path.exists()


def test_snapshot_date_directory_is_created(tmp_path: Path) -> None:
    directory = snapshot_date_directory(tmp_path, "2026-09-29")
    assert directory.is_dir()


def test_iter_snapshot_date_directories_skips_other_names(tmp_path: Path) -> None:
    snapshot_date_directory(tmp_path, "2026-09-29")
    (tmp_path / "not-a-date").mkdir()
    (tmp_path / "loose-file.txt").write_text("x", encoding="utf-8")
    found = iter_snapshot_date_directories(tmp_path)
    assert [day.isoformat() for day, _path in found] == ["2026-09-29"]


def test_iter_snapshot_date_directories_on_missing_root(tmp_path: Path) -> None:
    assert iter_snapshot_date_directories(tmp_path / "missing") == []


def test_prune_raw_responses_removes_only_expired_days(tmp_path: Path) -> None:
    expired = save_raw_response(tmp_path, "2026-06-01", "old", b"1")
    fresh = save_raw_response(tmp_path, "2026-09-29", "new", b"2")
    unrelated = tmp_path / "not-a-date"
    unrelated.mkdir()

    removed = prune_raw_responses(tmp_path, today=date(2026, 9, 29))

    assert [path.name for path in removed] == ["2026-06-01"]
    assert not expired.exists()
    assert fresh.exists()
    assert unrelated.exists()


def test_prune_raw_responses_keeps_boundary_day(tmp_path: Path) -> None:
    boundary = save_raw_response(tmp_path, "2026-07-01", "boundary", b"1")
    removed = prune_raw_responses(tmp_path, today=date(2026, 9, 29))
    assert removed == []
    assert boundary.exists()


def test_prune_raw_responses_on_missing_root(tmp_path: Path) -> None:
    assert prune_raw_responses(tmp_path / "missing", today=date(2026, 9, 29)) == []


def test_prune_raw_responses_uses_custom_retention(tmp_path: Path) -> None:
    save_raw_response(tmp_path, "2026-09-27", "recent", b"1")
    removed = prune_raw_responses(tmp_path, retention_days=1, today=date(2026, 9, 29))
    assert [path.name for path in removed] == ["2026-09-27"]
