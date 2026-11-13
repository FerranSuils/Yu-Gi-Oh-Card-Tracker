"""Market prices and the rules that turn them into sale prices."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

Metric = Literal['trend', 'avg', 'low', 'avg1', 'avg7', 'avg30']
Rounding = Literal['none', 'x49_x99', 'step_005']

DEFAULT_CONDITION_FACTORS: Dict[str, float] = {
    'Mint': 100, 'Near Mint': 100, 'Excellent': 90, 'Good': 80,
    'Light Played': 70, 'Played': 60, 'Poor': 40, 'Damaged': 30,
}


def to_price(value: Any) -> Optional[float]:
    """A positive price, or None for empty, zero, negative or unreadable values."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:  # NaN or not a price
        return None
    return number


class PriceQuote(BaseModel):
    """Prices in the market's own currency."""
    low: Optional[float] = None
    avg: Optional[float] = None
    trend: Optional[float] = None
    avg1: Optional[float] = None
    avg7: Optional[float] = None
    avg30: Optional[float] = None


class PrintingPrice(BaseModel):
    normal: Optional[PriceQuote] = None
    foil: Optional[PriceQuote] = None
    # 'card' means the source only knows one price for every printing of the card.
    scope: Literal['printing', 'card'] = 'printing'


class PricingRule(BaseModel):
    metric: Metric = 'trend'
    percent: float = 100.0
    fixed: float = 0.0
    min_price: float = 0.10
    rounding: Rounding = 'none'
    condition_factors: Dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_CONDITION_FACTORS))
    auto_apply: bool = False
    # Card-level prices (one price for every printing, e.g. Yu-Gi-Oh on Cardmarket) are only a
    # reference unless the seller opts in: a rare printing would get the cheapest reprint's price.
    use_card_prices: bool = False


def apply_list_price(entry, price: Optional[float], locked: Optional[bool] = None) -> bool:
    """Set an entry's sale price (2 decimals) and lock flag. True when anything changed.

    Callers go through CollectionEditor / GameCollectionEditor.set_list_price.
    """
    new_price = None if price is None else round(float(price), 2)
    changed = entry.list_price != new_price
    entry.list_price = new_price
    if locked is not None and entry.price_locked != locked:
        entry.price_locked = locked
        changed = True
    return changed
