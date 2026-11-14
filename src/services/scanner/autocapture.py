"""Continuous capture on the live scan page: look at the camera every few seconds while cards are slid under it."""

from __future__ import annotations

from typing import Any

INTERVALS = (2, 3, 5, 10)    # seconds between looks
DEFAULT_INTERVAL = 3


def clean_interval(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL
    return seconds if seconds in INTERVALS else DEFAULT_INTERVAL


def interval_label(seconds: int) -> str:
    return f'Cada {seconds} s'


def should_capture(scanner_idle: bool) -> bool:
    """Never queue a new card while the last one is still being read: the queue would only grow."""
    return bool(scanner_idle)
