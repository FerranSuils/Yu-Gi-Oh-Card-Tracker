"""Sale prices from market prices: rules, preview and apply."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterator, Literal, Optional, Union

from src.core.catalog_models import GameCollection
from src.core.game_collections import GameCollectionEditor
from src.core.models import Collection, CollectionEntry
from src.core.pricing_models import PriceQuote, PricingRule, PrintingPrice
from src.services.collection_editor import CollectionEditor

AnyCollection = Union[Collection, GameCollection]


@dataclass
class EntryRef:
    """One physical stack of cards, with what is needed to price it."""
    card_id: str
    name: str
    printing_id: str
    set_code: str
    rarity: Optional[str]
    finish: str
    entry: CollectionEntry


def iter_priced_entries(collection: AnyCollection) -> Iterator[EntryRef]:
    """Every entry of a Yu-Gi-Oh or other-game collection, in collection order."""
    is_game = isinstance(collection, GameCollection)
    for card in collection.cards:
        for variant in card.variants:
            printing_id = variant.printing_id if is_game else variant.variant_id
            finish = variant.finish if is_game else 'nonfoil'
            for entry in variant.entries:
                yield EntryRef(card_id=str(card.card_id), name=card.name, printing_id=printing_id,
                               set_code=variant.set_code, rarity=variant.rarity, finish=finish, entry=entry)


# --- Rules -----------------------------------------------------------------

FALLBACK_METRICS = ('trend', 'avg', 'low')
Status = Literal['cambia', 'igual', 'bloqueada', 'sin precio', 'por carta']
PriceLookup = Callable[[str], Optional[PrintingPrice]]


def quote_for(price: Optional[PrintingPrice], finish: str) -> Optional[PriceQuote]:
    """Foil-like finishes use the foil quote when there is one; everything else uses normal."""
    if price is None:
        return None
    if finish and finish != 'nonfoil' and price.foil is not None:
        return price.foil
    return price.normal


def base_price(rule: PricingRule, quote: Optional[PriceQuote]) -> Optional[float]:
    if quote is None:
        return None
    for metric in (rule.metric, *FALLBACK_METRICS):
        value = getattr(quote, metric)
        if value is not None:
            return value
    return None


def _round(price: float, rounding: str) -> float:
    price = round(price, 2)
    if rounding == 'step_005':
        return round(round(price * 20) / 20, 2)
    if rounding == 'x49_x99':
        whole = math.floor(price)
        return next(c for c in (round(whole + 0.49, 2), round(whole + 0.99, 2), round(whole + 1.49, 2))
                    if c >= price)
    return price


def compute_price(rule: PricingRule, quote: Optional[PriceQuote], condition: str) -> Optional[float]:
    base = base_price(rule, quote)
    if base is None:
        return None
    factor = rule.condition_factors.get(condition, 100.0)
    price = base * rule.percent / 100 * factor / 100 + rule.fixed
    return round(max(_round(price, rule.rounding), rule.min_price), 2)


def validate_rule(rule: PricingRule) -> list[str]:
    errors = []
    if rule.percent <= 0:
        errors.append('El porcentaje tiene que ser mayor que 0.')
    if rule.min_price < 0:
        errors.append('El precio mínimo no puede ser negativo.')
    for condition, factor in rule.condition_factors.items():
        if factor < 0:
            errors.append(f'El factor de «{condition}» no puede ser negativo.')
    return errors


# --- Preview and apply -----------------------------------------------------

@dataclass
class RepriceRow:
    ref: EntryRef
    market: Optional[float]
    current: Optional[float]
    new: Optional[float]
    delta: Optional[float]
    status: Status


def preview(collection: AnyCollection, prices: PriceLookup, rule: PricingRule) -> list[RepriceRow]:
    rows = []
    for ref in iter_priced_entries(collection):
        price = prices(ref.printing_id)
        quote = quote_for(price, ref.finish)
        market = base_price(rule, quote)
        current = ref.entry.list_price
        if ref.entry.price_locked:
            rows.append(RepriceRow(ref, market, current, current, None, 'bloqueada'))
            continue
        if price is not None and price.scope == 'card' and not rule.use_card_prices and market is not None:
            rows.append(RepriceRow(ref, market, current, current, None, 'por carta'))
            continue
        new = compute_price(rule, quote, ref.entry.condition)
        if new is None:
            rows.append(RepriceRow(ref, market, current, None, None, 'sin precio'))
            continue
        delta = None if current is None else round(new - current, 2)
        rows.append(RepriceRow(ref, market, current, new, delta, 'igual' if current == new else 'cambia'))
    return rows


def apply(collection: AnyCollection, rows: list[RepriceRow]) -> int:
    """Write the 'cambia' rows through the collection's editor. Returns how many changed."""
    editor = GameCollectionEditor if isinstance(collection, GameCollection) else CollectionEditor
    return sum(1 for row in rows
               if row.status == 'cambia' and editor.set_list_price(row.ref.entry, row.new))


def collection_values(collection: AnyCollection, prices: PriceLookup) -> tuple[float, float]:
    """(market value = Σ quantity × trend, sale value = Σ quantity × list price)."""
    market = sale = 0.0
    for ref in iter_priced_entries(collection):
        quote = quote_for(prices(ref.printing_id), ref.finish)
        trend = base_price(PricingRule(metric='trend'), quote)
        if trend is not None:
            market += ref.entry.quantity * trend
        if ref.entry.list_price is not None:
            sale += ref.entry.quantity * ref.entry.list_price
    return round(market, 2), round(sale, 2)
