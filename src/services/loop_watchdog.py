"""Tells us when the server's event loop stops answering, and what every thread was doing.

The IIS logs show moments where the app accepts a connection but does not answer for 20 s or
more, with nothing in app.log. A watchdog thread pings the loop; when the answer takes longer
than the threshold it logs the delay and the stacks of all threads, once per stall.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import traceback
from typing import Callable, Optional

logger = logging.getLogger(__name__)
STACK_FRAMES = 8


def thread_stacks(skip_ident: Optional[int] = None) -> str:
    names = {t.ident: t.name for t in threading.enumerate()}
    parts = []
    for ident, frame in sys._current_frames().items():
        if ident == skip_ident:
            continue
        lines = ''.join(traceback.format_stack(frame)[-STACK_FRAMES:])
        parts.append(f'--- {names.get(ident, ident)} ---\n{lines}')
    return '\n'.join(parts)


def log_stall(delay: float, stacks: str) -> None:
    logger.warning('Event loop stalled for %.1f s. Threads:\n%s', delay, stacks)


class LoopWatchdog:
    def __init__(self, loop: asyncio.AbstractEventLoop, threshold: float = 5.0, interval: float = 1.0,
                 report: Callable[[float, str], None] = log_stall):
        self._loop = loop
        self._threshold = threshold
        self._interval = interval
        self._report = report
        self._stopped = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name='loop-watchdog', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def _run(self) -> None:
        reported = False
        while not self._stopped.wait(self._interval):
            answered = threading.Event()
            started = time.perf_counter()
            try:
                self._loop.call_soon_threadsafe(answered.set)
            except RuntimeError:  # the loop is closed: the app is stopping
                return
            while not answered.wait(0.05):
                waited = time.perf_counter() - started
                if waited >= self._threshold and not reported:
                    reported = True
                    # Captured while the loop is still stuck: that is what points at the culprit.
                    self._report(waited, thread_stacks(skip_ident=threading.get_ident()))
                if self._stopped.is_set():
                    return
            reported = False
