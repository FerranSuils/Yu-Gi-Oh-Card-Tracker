"""The key a shop's own website or scripts read its data with. Only its SHA-256 is ever stored."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from typing import Dict, List, Optional

from src.services.sales.store import _write
from src.services.shop.files import root_lock, shop_path

logger = logging.getLogger(__name__)

FILE = 'api.json'
KEY = re.compile(r'oy_[0-9a-f]{48}')
_HASH = re.compile(r'[0-9a-f]{64}')
RESCAN_SECONDS = 5.0

_guard = threading.Lock()
_index: Dict[str, str] = {}       # key hash -> account folder
_scanned: Dict[str, float] = {}   # base folder -> when it was last walked


def forget() -> None:
    with _guard:
        _index.clear()
        _scanned.clear()


def digest(key: str) -> str:
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def _stored(root: str) -> Optional[dict]:
    try:
        with open(shop_path(root, FILE), 'r', encoding='utf-8') as file:
            data = json.load(file)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get('hash'), str) or not _HASH.fullmatch(data['hash']):
        return None
    return data


def _drop(root: str) -> None:
    for known in [h for h, r in _index.items() if r == root]:
        del _index[known]


def create(root: str) -> str:
    """A fresh key, returned this once. Any earlier key of the account stops working."""
    key = 'oy_' + secrets.token_hex(24)
    with root_lock(root):
        _write(shop_path(root, FILE), {'hash': digest(key), 'hint': key[-4:]})
    with _guard:
        _drop(root)
        _index[digest(key)] = root
    return key


def revoke(root: str) -> None:
    with root_lock(root):
        path = shop_path(root, FILE)
        if os.path.exists(path):
            os.remove(path)
    with _guard:
        _drop(root)


def hint(root: str) -> Optional[str]:
    """The last four characters of the account's key, or None when it has none."""
    data = _stored(root)
    if data is None:
        return None
    tail = data.get('hint')
    return tail if isinstance(tail, str) and re.fullmatch(r'[0-9a-f]{4}', tail) else ''


def _scan(base: str) -> Dict[str, str]:
    from src.services.prices.scheduler import account_roots

    found = {}
    for root in account_roots(base):
        data = _stored(root)
        if data:
            found[data['hash']] = root
    return found


def account_for(key, base: str = 'data') -> Optional[str]:
    """The account folder a key reads. Wrong guesses cost one disk walk every few seconds."""
    if not isinstance(key, str) or not KEY.fullmatch(key):
        return None
    wanted = digest(key)
    with _guard:
        root = _index.get(wanted)
        if root is None and time.monotonic() - _scanned.get(base, float('-inf')) >= RESCAN_SECONDS:
            _scanned[base] = time.monotonic()
            try:
                _index.update(_scan(base))
            except OSError as error:
                logger.error('API: no se pudieron leer las cuentas: %s', type(error).__name__)
            root = _index.get(wanted)
        if root is None:
            return None
        current = _stored(root)   # the file is the truth: the key may have been regenerated or revoked
        if current is None or not hmac.compare_digest(current['hash'], wanted):
            _index.pop(wanted, None)
            return None
        return root


class Limiter:
    """At most `limit` requests per key in a sliding window. In memory: a restart forgets."""

    def __init__(self, limit: int = 60, seconds: float = 60):
        self._limit = limit
        self._seconds = seconds
        self._lock = threading.Lock()
        self._seen: Dict[str, List[float]] = {}

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            for other in [k for k, times in self._seen.items() if not times or now - times[-1] >= self._seconds]:
                del self._seen[other]
            recent = [t for t in self._seen.get(key, []) if now - t < self._seconds]
            if len(recent) >= self._limit:
                self._seen[key] = recent
                return False
            self._seen[key] = recent + [now]
            return True
