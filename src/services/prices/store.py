"""One game and market's daily prices on disk, loaded lazily."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

from src.core.pricing_models import PrintingPrice
from src.services.catalog.store import _write_atomic

logger = logging.getLogger(__name__)


class PriceStore:
    def __init__(self, path: str):
        self.path = path
        self.meta_path = path + '.meta.json'
        self._lock = threading.RLock()
        self._prices: Optional[dict[str, PrintingPrice]] = None

    def load(self) -> dict[str, PrintingPrice]:
        with self._lock:
            if self._prices is None:
                self._prices = self._read()
            return self._prices

    def _read(self) -> dict[str, PrintingPrice]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, 'r', encoding='utf-8') as file:
                return {key: PrintingPrice(**value) for key, value in json.load(file).items()}
        except Exception as exc:
            logger.error('Prices %s are unreadable: %s', self.path, exc)
            return {}

    def get(self, printing_id: str) -> PrintingPrice | None:
        return self.load().get(printing_id)

    def unload(self) -> None:
        with self._lock:
            self._prices = None

    def replace(self, prices: dict[str, PrintingPrice]) -> None:
        with self._lock:
            data = {key: value.model_dump(exclude_none=True) for key, value in prices.items()}
            _write_atomic(self.path, json.dumps(data, separators=(',', ':')))
            meta = {'count': len(prices), 'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
            _write_atomic(self.meta_path, json.dumps(meta))
            self._prices = None

    def info(self) -> dict:
        """Count and date from the metadata file, without loading the prices."""
        if not os.path.exists(self.path) or not os.path.exists(self.meta_path):
            return {'count': 0, 'updated_at': None}
        try:
            with open(self.meta_path, 'r', encoding='utf-8') as file:
                meta = json.load(file)
            return {'count': int(meta.get('count') or 0), 'updated_at': meta.get('updated_at')}
        except Exception:
            return {'count': 0, 'updated_at': None}
