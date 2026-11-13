"""Game-neutral catalog and collection models.

Yu-Gi-Oh keeps its own models in ``models.py``. Every other game uses these,
with string ids, so its collections never reach the Yu-Gi-Oh views.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from src.core.models import CollectionEntry
from src.core.pricing_models import PricingRule


class CatalogPrinting(BaseModel):
    printing_id: str
    set_code: str
    set_name: str
    number: Optional[str] = None
    rarity: Optional[str] = None
    image_url: Optional[str] = None
    image_url_small: Optional[str] = None
    finishes: List[str] = []
    # Ids of this printing on each marketplace, e.g. {'cardmarket': '21390'}.
    market_ids: Dict[str, str] = {}


class CatalogCard(BaseModel):
    game: str
    card_id: str
    name: str
    printings: List[CatalogPrinting] = []
    attributes: dict[str, Any] = {}


class GameCollectionVariant(BaseModel):
    printing_id: str
    set_code: str
    number: Optional[str] = None
    rarity: Optional[str] = None
    finish: str = "nonfoil"
    entries: List[CollectionEntry] = []

    @property
    def total_quantity(self) -> int:
        return sum(e.quantity for e in self.entries)


class GameCollectionCard(BaseModel):
    card_id: str
    name: str
    variants: List[GameCollectionVariant] = []

    @property
    def total_quantity(self) -> int:
        return sum(v.total_quantity for v in self.variants)


class GameCollection(BaseModel):
    game: str
    name: str
    description: str = ""
    cards: List[GameCollectionCard] = []
    for_sale: bool = False
    pricing_rule: Optional[PricingRule] = None

    @property
    def total_cards(self) -> int:
        return sum(c.total_quantity for c in self.cards)
