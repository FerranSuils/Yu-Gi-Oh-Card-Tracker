"""Collections for every game except Yu-Gi-Oh, stored per account and per game."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Callable, Optional

from src.core.account_scope import account_root
from src.core.catalog_models import (
    CatalogCard,
    CatalogPrinting,
    GameCollection,
    GameCollectionCard,
    GameCollectionVariant,
)
from src.core.collection_sync import ensure_fresh, path_lock, remember, written
from src.core.models import CollectionEntry
from src.core.pricing_models import apply_list_price
from src.core import stock_moves
from src.core.sales_models import SaleLine
from src.core.persistence import sanitize_collection_filename


def _check_game(game: str) -> str:
    from src.services.catalog import game_ids

    if game == 'yugioh':
        raise ValueError('Yu-Gi-Oh collections live in the Yu-Gi-Oh pages')
    if game not in game_ids():
        raise ValueError(f'Unknown game: {game!r}')
    return game


class GameCollectionStore:
    def __init__(self, root_resolver: Callable[[], str] = account_root):
        self._root = root_resolver

    def bound(self) -> 'GameCollectionStore':
        """A store fixed to the current account. Call it on the UI thread, before run.io_bound:
        worker threads cannot see the session, so they would resolve the primary account."""
        root = self._root()
        return GameCollectionStore(lambda: root)

    def _dir(self, game: str) -> str:
        return os.path.join(self._root(), 'games', _check_game(game), 'collections')

    def _path(self, game: str, filename: str) -> str:
        return os.path.join(self._dir(game), sanitize_collection_filename(filename))

    def path(self, game: str, filename: str) -> str:
        """The file behind one collection, for collection_sync."""
        return self._path(game, filename)

    def list(self, game: str) -> list[str]:
        directory = self._dir(game)
        if not os.path.isdir(directory):
            return []
        return sorted(f for f in os.listdir(directory) if f.endswith('.json'))

    def load(self, game: str, filename: str) -> GameCollection:
        path = self._path(game, filename)
        with open(path, 'r', encoding='utf-8') as file:
            collection = GameCollection(**json.load(file))
        remember(collection, path)
        return collection

    def save(self, game: str, collection: GameCollection, filename: str) -> None:
        path = self._path(game, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with path_lock(path):
            ensure_fresh(collection, path)  # an older copy must not undo a newer save
            fd, temporary = tempfile.mkstemp(prefix='.collection-', dir=os.path.dirname(path))
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as file:
                    json.dump(collection.model_dump(mode='json'), file, ensure_ascii=False, indent=2)
                os.replace(temporary, path)
                written(collection, path)
            finally:
                if os.path.exists(temporary):
                    os.remove(temporary)

    def delete(self, game: str, filename: str) -> None:
        path = self._path(game, filename)
        if os.path.exists(path):
            os.remove(path)


class GameCollectionEditor:
    """The only way to change the cards in a GameCollection."""

    @staticmethod
    def set_list_price(entry: CollectionEntry, price: Optional[float], locked: Optional[bool] = None) -> bool:
        """Set an entry's sale price and lock. Returns True if it changed."""
        return apply_list_price(entry, price, locked)

    @staticmethod
    def take_stock(collection: GameCollection, line: SaleLine) -> None:
        """Sell the copies of a ticket line. Raises OutOfStock, changing nothing, if the pile is short."""
        stock_moves.take(collection, line, line.card_id,
                         lambda v: v.printing_id == line.variant_id and v.finish == line.finish)

    @staticmethod
    def return_stock(collection: GameCollection, line: SaleLine) -> None:
        """Put a sold line back, rebuilding the card, variant and pile if the sale emptied them."""
        stock_moves.give_back(
            collection, line, line.card_id,
            lambda v: v.printing_id == line.variant_id and v.finish == line.finish,
            lambda: GameCollectionCard(card_id=line.card_id, name=line.name),
            lambda: GameCollectionVariant(printing_id=line.variant_id, set_code=line.set_code, number=line.number,
                                          rarity=line.rarity or None, finish=line.finish or 'nonfoil'))

    @staticmethod
    def apply_change(collection: GameCollection, card: CatalogCard, printing: CatalogPrinting, finish: str,
                     delta: int, condition: str = 'Near Mint', language: str = 'EN', first_edition: bool = False,
                     storage_location: Optional[str] = None) -> None:
        if delta == 0:
            return
        owned = next((c for c in collection.cards if c.card_id == card.card_id), None)
        if owned is None:
            if delta < 0:
                return
            owned = GameCollectionCard(card_id=card.card_id, name=card.name)
            collection.cards.append(owned)
        variant = next((v for v in owned.variants if v.printing_id == printing.printing_id and v.finish == finish),
                       None)
        if variant is None:
            if delta < 0:
                return
            variant = GameCollectionVariant(printing_id=printing.printing_id, set_code=printing.set_code,
                                            number=printing.number, rarity=printing.rarity, finish=finish)
            owned.variants.append(variant)
        key = (condition, language, first_edition, storage_location)
        entry = next((e for e in variant.entries
                      if (e.condition, e.language, e.first_edition, e.storage_location) == key), None)
        if entry is None:
            if delta > 0:
                variant.entries.append(CollectionEntry(condition=condition, language=language,
                                                       first_edition=first_edition, quantity=delta,
                                                       storage_location=storage_location))
        else:
            entry.quantity += delta
            if entry.quantity <= 0:
                variant.entries.remove(entry)
        if not variant.entries:
            owned.variants.remove(variant)
        if not owned.variants:
            collection.cards.remove(owned)


game_collection_store = GameCollectionStore()
