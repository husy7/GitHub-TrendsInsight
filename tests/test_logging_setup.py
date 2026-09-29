"""Logging configuration smoke tests (AGENTS.md §11)."""

from __future__ import annotations

import logging

from trends.logging_setup import setup_logging


def test_setup_logging_uses_requested_level() -> None:
    setup_logging("debug")
    assert logging.getLogger().level == logging.DEBUG


def test_setup_logging_falls_back_to_info() -> None:
    setup_logging("not-a-level")
    assert logging.getLogger().level == logging.INFO
