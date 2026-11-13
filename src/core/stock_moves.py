"""Shared mechanics for selling a pile and putting it back. Only the collection editors call these."""

from __future__ import annotations

from typing import Callable

from src.core.models import CollectionEntry
from src.core.sales_models import OutOfStock, SaleLine


def _find(collection, line: SaleLine, card_id, is_variant: Callable):
    card = next((c for c in collection.cards if c.card_id == card_id), None)
    variant = next((v for v in card.variants if is_variant(v)), None) if card else None
    entry = None
    if variant:
        entry = next((e for e in variant.entries
                      if (e.condition, e.language, e.first_edition, e.storage_location) == line.pile()), None)
    return card, variant, entry


def take(collection, line: SaleLine, card_id, is_variant: Callable) -> None:
    if line.kind != 'stock':
        return
    card, variant, entry = _find(collection, line, card_id, is_variant)
    available = entry.quantity if entry else 0
    if available < line.quantity:
        raise OutOfStock(line, available)
    entry.quantity -= line.quantity
    if entry.quantity <= 0:
        variant.entries.remove(entry)
    if not variant.entries:
        card.variants.remove(variant)
    if not card.variants:
        collection.cards.remove(card)


def give_back(collection, line: SaleLine, card_id, is_variant: Callable, new_card: Callable,
              new_variant: Callable) -> None:
    if line.kind != 'stock':
        return
    card, variant, entry = _find(collection, line, card_id, is_variant)
    if card is None:
        card = new_card()
        collection.cards.append(card)
    if variant is None:
        variant = new_variant()
        card.variants.append(variant)
    if entry is None:
        variant.entries.append(CollectionEntry(
            condition=line.condition, language=line.language, first_edition=line.first_edition,
            storage_location=line.storage_location, quantity=line.quantity, list_price=line.list_price,
            price_locked=line.price_locked))
    else:
        entry.quantity += line.quantity
