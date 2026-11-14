"""Generic local store for reference data scraped or fetched from external sites.

Layout: ``<root>/<source>/records.json`` (key -> record) and
``<root>/<source>/changes.json`` (newest-first change log, capped).

A record is ``{source, key, first_seen, fetched_at, data}``. ``upsert`` reports
whether the data is ``'new'``, ``'changed'`` or ``'same'`` compared with the last
capture. Writes are atomic (temp file + ``os.replace``). Blocking file I/O: call
from ``run.io_bound`` in UI code.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

DEFAULT_ROOT = os.path.join('data', 'reference')
_SOURCE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
_ISO = '%Y-%m-%dT%H:%M:%S'


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text('utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError(f'Fichero de referencia corrupto: {path} ({exc})') from exc


class ReferenceStore:
    def __init__(self, root, source: str, now: Callable[[], datetime] = datetime.now,
                 max_changes: int = 500):
        if not _SOURCE_RE.match(source or ''):
            raise ValueError(f'Nombre de fuente no válido: {source!r}')
        self.source = source
        self.dir = Path(root) / source
        self._now = now
        self._max_changes = max_changes
        self._lock = threading.RLock()
        self._records_path = self.dir / 'records.json'
        self._changes_path = self.dir / 'changes.json'
        self._records: dict[str, dict] = _load(self._records_path, {})
        self._changes: list[dict] = _load(self._changes_path, [])

    def _stamp(self) -> str:
        return self._now().strftime(_ISO)

    def upsert(self, key: str, data: Any) -> str:
        summary = self.upsert_many({key: data})
        return next(kind for kind, keys in summary.items() if keys)

    def upsert_many(self, items: dict[str, Any]) -> dict[str, list[str]]:
        """Upsert several records with a single disk write."""
        try:
            json.dumps(items)
        except TypeError as exc:
            raise TypeError(f'Los datos deben ser JSON serializables: {exc}') from exc
        summary: dict[str, list[str]] = {'new': [], 'changed': [], 'same': []}
        with self._lock:
            stamp = self._stamp()
            for key, data in items.items():
                data = json.loads(json.dumps(data))
                current = self._records.get(key)
                if current is None:
                    kind = 'new'
                    self._records[key] = {'source': self.source, 'key': key, 'first_seen': stamp,
                                          'fetched_at': stamp, 'data': data}
                    self._changes.insert(0, {'at': stamp, 'key': key, 'kind': 'new'})
                elif current['data'] != data:
                    kind = 'changed'
                    self._changes.insert(0, {'at': stamp, 'key': key, 'kind': 'changed',
                                             'before': current['data']})
                    current['data'] = data
                    current['fetched_at'] = stamp
                else:
                    kind = 'same'
                    current['fetched_at'] = stamp
                summary[kind].append(key)
            del self._changes[self._max_changes:]
            _atomic_write(self._records_path, self._records)
            _atomic_write(self._changes_path, self._changes)
        return summary

    def get(self, key: str) -> Optional[dict]:
        return self._records.get(key)

    def all(self) -> list[dict]:
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)

    def changes(self, since: Optional[datetime] = None) -> list[dict]:
        """Change log, newest first; optionally only entries at or after ``since``."""
        if since is None:
            return list(self._changes)
        cutoff = since.strftime(_ISO)
        return [c for c in self._changes if c['at'] >= cutoff]
