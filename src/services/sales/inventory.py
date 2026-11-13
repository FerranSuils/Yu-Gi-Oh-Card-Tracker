"""Everything an account can sell, read from all its collections, and the stock moves of a ticket."""

from __future__ import annotations

import logging
from contextlib import ExitStack
from typing import Iterable, List, Optional

from src.core.collection_sync import bump, path_lock
from src.core.game_collections import GameCollectionEditor
from src.core.sales_models import OutOfStock, SaleLine, to_cents
from src.services.collection_editor import CollectionEditor

logger = logging.getLogger(__name__)


class StockUnreadable(Exception):
    """A collection file is there but cannot be read, so nobody knows what is on those shelves."""


def _cents(price) -> int:
    try:
        return to_cents(price)
    except ValueError:
        return 0


def line_key(line: SaleLine) -> tuple:
    """Identifies the physical pile a stock line points at."""
    return (line.game, line.collection, line.card_id, line.variant_id, line.finish, *line.pile())


def search(items: List[SaleLine], text: str, limit: int = 50) -> List[SaleLine]:
    """Piles whose name, set, number or rarity hold every word typed."""
    words = (text or '').casefold().split()
    found = []
    for item in items:
        haystack = ' '.join(filter(None, (item.name, item.set_code, item.number, item.rarity))).casefold()
        if all(word in haystack for word in words):
            found.append(item)
            if len(found) >= limit:
                break
    return found


class Inventory:
    """Reads and moves stock of the account signed in when it is built. Build it on the UI thread."""

    def __init__(self, persistence, games):
        # Charging runs in worker threads, where nobody is signed in: fix the account now.
        self._persistence = persistence.bound()
        self._games = games

    # --- files -------------------------------------------------------------------------------

    def _path(self, game: str, filename: str) -> str:
        if game == 'yugioh':
            return self._persistence.collection_path(filename)
        return self._games.path(game, filename)

    def _load(self, game: str, filename: str):
        if game == 'yugioh':
            return self._persistence.load_collection(filename)
        return self._games.load(game, filename)

    def _save(self, game: str, collection, filename: str) -> None:
        if game == 'yugioh':
            self._persistence.save_collection(collection, filename)
        else:
            self._games.save(game, collection, filename)
        bump(self._path(game, filename))  # open pages showing this file reload

    def _list(self, game: str) -> List[str]:
        try:
            return sorted(self._persistence.list_collections() if game == 'yugioh' else self._games.list(game))
        except (OSError, ValueError):
            return []

    # --- reading -----------------------------------------------------------------------------

    def collections(self, game: str) -> List[str]:
        """The collection files of a game, by name."""
        return self._list(game)

    def items(self, games: Iterable[str], strict: bool = False) -> List[SaleLine]:
        """One line per pile in stock; ``quantity`` is what the pile holds.

        A file that cannot be read is skipped, unless ``strict``: whoever is about to tell somebody else
        what is on the shelves must not take a missing file for empty shelves."""
        lines: List[SaleLine] = []
        for game in games:
            for filename in self._list(game):
                try:
                    collection = self._load(game, filename)
                except Exception as error:
                    logger.warning('Mostrador: no se pudo leer %s/%s: %s', game, filename, type(error).__name__)
                    if strict:
                        raise StockUnreadable(filename) from None
                    continue
                lines.extend(self._lines(game, filename, collection))
        lines.sort(key=lambda line: (line.name.casefold(), line.set_code, line.condition))
        return lines

    @staticmethod
    def _lines(game: str, filename: str, collection) -> List[SaleLine]:
        lines = []
        for card in collection.cards:
            for variant in card.variants:
                ygo = game == 'yugioh'
                for entry in variant.entries:
                    if entry.quantity < 1:
                        continue
                    lines.append(SaleLine(
                        game=game, collection=filename, card_id=str(card.card_id), name=card.name,
                        set_code=variant.set_code or '', number=None if ygo else variant.number,
                        rarity=variant.rarity or '',
                        variant_id=variant.variant_id if ygo else variant.printing_id,
                        finish='' if ygo else variant.finish, image_id=variant.image_id if ygo else None,
                        condition=entry.condition, language=entry.language, first_edition=entry.first_edition,
                        storage_location=entry.storage_location, quantity=entry.quantity,
                        unit_cents=_cents(entry.list_price), list_price=entry.list_price,
                        price_locked=entry.price_locked))
        return lines

    # --- moving ------------------------------------------------------------------------------

    def take(self, lines: List[SaleLine]) -> None:
        """Sell every stock line or none: a short pile raises OutOfStock and nothing is saved."""
        self._move(lines, taking=True)

    def give_back(self, lines: List[SaleLine]) -> None:
        self._move(lines, taking=False)

    def _move(self, lines: List[SaleLine], taking: bool) -> None:
        groups: dict[tuple, List[SaleLine]] = {}
        for line in lines:
            if line.kind == 'stock':
                groups.setdefault((line.game, line.collection), []).append(line)
        if not groups:
            return
        files = sorted(groups, key=lambda key: self._path(*key))
        with ExitStack() as stack:
            for key in files:  # always in the same order, so two tickets cannot deadlock
                stack.enter_context(path_lock(self._path(*key)))
            changed = []
            for game, filename in files:
                collection = self._open(game, filename, groups[(game, filename)][0], taking)
                editor = CollectionEditor if game == 'yugioh' else GameCollectionEditor
                for line in groups[(game, filename)]:
                    (editor.take_stock if taking else editor.return_stock)(collection, line)
                changed.append((game, filename, collection))
            saved = []
            try:
                for game, filename, collection in changed:
                    self._save(game, collection, filename)
                    saved.append((game, filename))
            except Exception:
                self._undo(saved, groups, taking)
                raise

    def _open(self, game: str, filename: str, line: SaleLine, taking: bool):
        try:
            return self._load(game, filename)
        except FileNotFoundError:
            if taking:
                raise OutOfStock(line, 0) from None
            return self._new(game, filename)

    @staticmethod
    def _new(game: str, filename: str):
        """A returned card whose collection was deleted goes to a collection of that name again."""
        name = filename.rsplit('.', 1)[0]
        if game == 'yugioh':
            from src.core.models import Collection
            return Collection(name=name)
        from src.core.catalog_models import GameCollection
        return GameCollection(game=game, name=name)

    def _undo(self, saved: List[tuple], groups: dict, taking: bool) -> None:
        """A later file failed to save: put the files already written back as they were."""
        for game, filename in saved:
            try:
                collection = self._load(game, filename)
                editor = CollectionEditor if game == 'yugioh' else GameCollectionEditor
                for line in groups[(game, filename)]:
                    (editor.return_stock if taking else editor.take_stock)(collection, line)
                self._save(game, collection, filename)
            except Exception as error:
                logger.error('Mostrador: no se pudo deshacer el movimiento en %s/%s: %s', game, filename,
                             type(error).__name__)
