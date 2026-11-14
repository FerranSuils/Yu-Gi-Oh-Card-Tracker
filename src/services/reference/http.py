"""Polite HTTP helper shared by the reference adapters (blocking; use run.io_bound)."""

import threading
import time

import requests

USER_AGENT = 'OpenYuGi/1.0'
MIN_INTERVAL = 1.0  # seconds between requests to the same host
TIMEOUT = 20

_lock = threading.Lock()
_last: dict[str, float] = {}


def polite_get(url: str, host: str, **kwargs):
    """GET with the OpenYuGi User-Agent and at most one request per second per host."""
    with _lock:
        wait = _last.get(host, 0) + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.monotonic()
    headers = {'User-Agent': USER_AGENT, **kwargs.pop('headers', {})}
    return requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
