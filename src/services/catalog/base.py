"""Interface every game catalog implements."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from src.core.catalog_models import CatalogCard
from src.services.catalog.store import CatalogStore


class CatalogProvider(ABC):
    game: str
    display_name: str
    store: CatalogStore

    @abstractmethod
    def fetch(self) -> list[CatalogCard]:
        """Download the full catalog. Raise on any failure."""

    _refresh_guard = threading.Lock()
    _refreshing: set = set()

    def refresh(self) -> int:
        with CatalogProvider._refresh_guard:
            if self.game in CatalogProvider._refreshing:
                raise RuntimeError('Ya se está descargando este catálogo.')
            CatalogProvider._refreshing.add(self.game)
        try:
            # Free the old copy first; fetch() runs before any write, so a failure keeps the stored file.
            self.store.unload()
            cards = self.fetch()
            if not cards:
                raise RuntimeError('La descarga no trajo ninguna carta; se conserva el catálogo anterior.')
            self.store.replace(cards)
            return len(cards)
        finally:
            with CatalogProvider._refresh_guard:
                CatalogProvider._refreshing.discard(self.game)

    def is_available(self) -> bool:
        return self.store.info()['count'] > 0

    def search(self, query: str, set_code: str | None = None, rarity: str | None = None,
               limit: int = 60) -> list[CatalogCard]:
        return self.store.search(query, set_code=set_code, rarity=rarity, limit=limit)

    def get(self, card_id: str) -> CatalogCard | None:
        return self.store.get(card_id)

    def sets(self) -> list[tuple[str, str]]:
        return self.store.sets()
