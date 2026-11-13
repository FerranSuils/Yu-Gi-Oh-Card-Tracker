"""Interface every market price source implements."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from src.core.pricing_models import PrintingPrice
from src.services.prices.store import PriceStore


class PriceSource(ABC):
    game: str
    market: str
    store: PriceStore

    @abstractmethod
    def fetch(self) -> dict[str, PrintingPrice]:
        """Download every price, keyed by printing id. Raise on any failure."""

    _refresh_guard = threading.Lock()
    _refreshing: set = set()

    def refresh(self) -> int:
        key = (self.game, self.market)
        with PriceSource._refresh_guard:
            if key in PriceSource._refreshing:
                raise RuntimeError('Ya se están descargando estos precios.')
            PriceSource._refreshing.add(key)
        try:
            prices = self.fetch()  # before any write: a failure keeps the stored file
            if not prices:
                raise RuntimeError('La descarga no trajo precios; se conservan los anteriores.')
            self.store.replace(prices)
            return len(prices)
        finally:
            with PriceSource._refresh_guard:
                PriceSource._refreshing.discard(key)

    def get(self, printing_id: str) -> PrintingPrice | None:
        return self.store.get(printing_id)
