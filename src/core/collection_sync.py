"""Coordinates writers of the same collection file inside this process.

The nightly reprice and an open collection page both load, change and save
whole collection files. One re-entrant lock per file keeps their writes from
interleaving, and a revision counter tells open pages that the file changed
under them, so they reload instead of saving their older copy over it.

A page that misses that signal is stopped at the save itself: every loaded copy
remembers which write of the file it came from, and saving a copy that is no
longer the latest raises StaleCollectionError instead of undoing newer changes.
"""

from __future__ import annotations

import os
import threading
import weakref

_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_revisions: dict[str, int] = {}
_writes: dict[str, int] = {}
_loaded: dict[int, tuple[str, int]] = {}  # id(collection) -> (file, write count it was read at)


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def path_lock(path: str) -> threading.RLock:
    key = _key(path)
    with _guard:
        lock = _locks.get(key)
        if lock is None:
            lock = _locks[key] = threading.RLock()
        return lock


def bump(path: str) -> int:
    """Record a write made outside the page that shows the file."""
    key = _key(path)
    with _guard:
        _revisions[key] = _revisions.get(key, 0) + 1
        return _revisions[key]


def revision(path: str) -> int:
    with _guard:
        return _revisions.get(_key(path), 0)


class RevisionWatcher:
    """Tells a page when the file it shows was rewritten by someone else."""

    def __init__(self, get_path):
        self._get_path = get_path
        self._path = None
        self._seen = 0

    def changed(self) -> bool:
        path = self._get_path()
        if not path:
            self._path = None
            return False
        current = revision(path)
        if path != self._path:
            self._path, self._seen = path, current
            return False
        if current != self._seen:
            self._seen = current
            return True
        return False


class StaleCollectionError(Exception):
    """The file was saved by someone else after this copy was loaded."""

    def __init__(self, message: str = 'La colección se ha cambiado desde otra ventana. '
                                      'Este cambio no se ha guardado; se recarga la página.'):
        super().__init__(message)


def remember(collection, path: str) -> None:
    """Note that ``collection`` holds the current contents of ``path``."""
    key = _key(path)
    with _guard:
        if id(collection) not in _loaded:
            weakref.finalize(collection, _loaded.pop, id(collection), None)
        _loaded[id(collection)] = (key, _writes.get(key, 0))


def ensure_fresh(collection, path: str) -> None:
    """Raise if ``collection`` was read from ``path`` before its latest write.
    Copies that were never read from this file (new or copied collections) pass."""
    key = _key(path)
    with _guard:
        seen = _loaded.get(id(collection))
        if seen is not None and seen[0] == key and seen[1] != _writes.get(key, 0):
            raise StaleCollectionError()


def written(collection, path: str) -> None:
    """Record a write of ``collection`` to ``path``; it is now the latest copy."""
    key = _key(path)
    with _guard:
        _writes[key] = _writes.get(key, 0) + 1
    remember(collection, path)
