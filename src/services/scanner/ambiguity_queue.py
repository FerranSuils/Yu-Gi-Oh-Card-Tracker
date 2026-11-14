"""Scans that need a person's decision wait here, so a new one never replaces the dialog that is open.

A PDF of a hundred cards can leave many ambiguous results while it is still being read: they are shown
one after another once the scanner has finished.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, Optional


class AmbiguityQueue:
    def __init__(self):
        self._waiting: Deque[Dict[str, Any]] = deque()
        self._open = False

    def push(self, result: Dict[str, Any]) -> None:
        self._waiting.append(result)

    def __len__(self) -> int:
        return len(self._waiting)

    def busy(self) -> bool:
        """A dialog is open right now."""
        return self._open

    def pending(self) -> int:
        """Results still to be decided, including the one being shown."""
        return len(self._waiting) + (1 if self._open else 0)

    def next_to_show(self, scanner_idle: bool) -> Optional[Dict[str, Any]]:
        """The next result to open a dialog for: only when the scanner is idle and no dialog is open."""
        if self._open or not scanner_idle or not self._waiting:
            return None
        self._open = True
        return self._waiting.popleft()

    def closed(self) -> None:
        """The dialog was confirmed or cancelled."""
        self._open = False
