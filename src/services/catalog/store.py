"""One game's compact catalog on disk, loaded lazily and searched in memory."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Optional

from src.core.catalog_models import CatalogCard

logger = logging.getLogger(__name__)


def _write_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.catalog-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            file.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


class CatalogStore:
    def __init__(self, path: str):
        self.path = path
        self.meta_path = path + '.meta.json'
        self._lock = threading.RLock()
        self._cards: Optional[list[CatalogCard]] = None
        self._by_id: dict[str, CatalogCard] = {}

    def load(self) -> list[CatalogCard]:
        with self._lock:
            if self._cards is None:
                self._cards = self._read()
                self._by_id = {card.card_id: card for card in self._cards}
            return self._cards

    def _read(self) -> list[CatalogCard]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, 'r', encoding='utf-8') as file:
                return [CatalogCard(**item) for item in json.load(file)]
        except Exception as exc:
            logger.error('Catalog %s is unreadable: %s', self.path, exc)
            return []

    def unload(self) -> None:
        """Drop the in-memory copy, e.g. before a download builds a new one."""
        with self._lock:
            self._cards = None
            self._by_id = {}

    def replace(self, cards: list[CatalogCard]) -> None:
        with self._lock:
            directory = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(directory, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.catalog-', dir=directory)
            try:
                # One card at a time: the Magic catalog is ~50 MB of JSON.
                with os.fdopen(fd, 'w', encoding='utf-8') as file:
                    file.write('[')
                    for index, card in enumerate(cards):
                        if index:
                            file.write(',')
                        file.write(card.model_dump_json())
                    file.write(']')
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.remove(temporary)
            meta = {'count': len(cards), 'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
            _write_atomic(self.meta_path, json.dumps(meta))
            self._cards = None
            self._by_id = {}

    def info(self) -> dict:
        """Count and date from the small metadata file, without loading the catalog."""
        if not os.path.exists(self.path) or not os.path.exists(self.meta_path):
            return {'count': 0, 'updated_at': None}
        try:
            with open(self.meta_path, 'r', encoding='utf-8') as file:
                meta = json.load(file)
            return {'count': int(meta.get('count') or 0), 'updated_at': meta.get('updated_at')}
        except Exception:
            return {'count': 0, 'updated_at': None}

    def search(self, query: str, set_code: str | None = None, rarity: str | None = None,
               limit: int = 60) -> list[CatalogCard]:
        needle = (query or '').strip().casefold()
        results = []
        for card in sorted(self.load(), key=lambda c: c.name.casefold()):
            if needle and needle not in card.name.casefold():
                continue
            if set_code or rarity:
                if not any((not set_code or p.set_code == set_code) and (not rarity or p.rarity == rarity)
                           for p in card.printings):
                    continue
            results.append(card)
            if len(results) >= limit:
                break
        return results

    def get(self, card_id: str) -> CatalogCard | None:
        self.load()
        return self._by_id.get(card_id)

    def sets(self) -> list[tuple[str, str]]:
        found: dict[str, str] = {}
        for card in self.load():
            for printing in card.printings:
                found.setdefault(printing.set_code, printing.set_name)
        return sorted(found.items(), key=lambda item: item[1].casefold())
