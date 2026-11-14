"""Which cards of the collection are ticked while the user picks several at once."""

from __future__ import annotations

from typing import List

from src.services.collection_editor import BulkTarget


def bulk_target(item) -> BulkTarget:
    """What a ticked card stands for: a collector row is one stack of a printing, a player card is every copy."""
    if hasattr(item, 'variant_id'):
        return (item.api_card.id, item.variant_id, item.language, item.condition, item.first_edition)
    return (item.api_card.id, None, None, None, None)


class BulkSelection:
    def __init__(self):
        self.active = False
        self._chosen: dict = {}

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False
        self._chosen.clear()

    def clear(self) -> None:
        self._chosen.clear()

    def has(self, item) -> bool:
        return bulk_target(item) in self._chosen

    def toggle(self, item) -> None:
        if not item.is_owned:
            return
        target = bulk_target(item)
        if target in self._chosen:
            del self._chosen[target]
        else:
            self._chosen[target] = True

    def select_all(self, items) -> None:
        for item in items:
            if item.is_owned:
                self._chosen.setdefault(bulk_target(item), True)

    def count(self) -> int:
        return len(self._chosen)

    def targets(self) -> List[BulkTarget]:
        return list(self._chosen)
