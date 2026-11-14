"""Yu-Gi-Oh prices from the local card database (YGOPRODeck) and manual Cardmarket captures."""

from __future__ import annotations

import os

from src.core.pricing_models import PriceQuote, PrintingPrice, to_price
from src.services.prices.base import PriceSource
from src.services.prices.registry import price_path
from src.services.prices.store import PriceStore


def _printing_id(card_set: dict) -> str:
    # Same key as the catalog adapter and the collections' variant_id.
    return card_set.get('variant_id') or f"{card_set.get('set_code')}:{card_set.get('set_rarity')}"


def _latest_manual(manual: dict, card_id: str, printing_id: str) -> float | None:
    history = ((manual.get(card_id) or {}).get(printing_id) or {}).get('cardmarket') or {}
    for day in sorted(history, reverse=True):
        price = to_price(history[day])
        if price is not None:
            return price
    return None


def ygo_to_prices(db: list[dict], market: str, manual: dict) -> dict[str, PrintingPrice]:
    """Cardmarket is one price per card (YGOPRODeck) unless a printing was captured by hand;
    TCGplayer has a price per printing where YGOPRODeck knows it, else the card's price."""
    prices: dict[str, PrintingPrice] = {}
    for card in db:
        card_id = str(card.get('id'))
        card_prices = (card.get('card_prices') or [{}])[0] or {}
        per_card = to_price(card_prices.get('cardmarket_price'))
        per_card_usd = to_price(card_prices.get('tcgplayer_price'))
        for card_set in card.get('card_sets') or []:
            printing_id = _printing_id(card_set)
            if market == 'cardmarket':
                captured = _latest_manual(manual, card_id, printing_id)
                if captured is not None:
                    prices[printing_id] = PrintingPrice(normal=PriceQuote(trend=captured))
                elif per_card is not None:
                    prices[printing_id] = PrintingPrice(normal=PriceQuote(trend=per_card), scope='card')
            else:
                price = to_price(card_set.get('set_price'))
                if price is not None:
                    prices[printing_id] = PrintingPrice(normal=PriceQuote(trend=price))
                elif per_card_usd is not None:
                    # YGOPRODeck leaves most printings at 0: use the card's own price rather than "worth nothing".
                    prices[printing_id] = PrintingPrice(normal=PriceQuote(trend=per_card_usd), scope='card')
    return prices


class _YugiohSource(PriceSource):
    game = 'yugioh'

    def __init__(self, store: PriceStore | None = None):
        self.store = store or PriceStore(price_path(self.game, self.market))

    def fetch(self) -> dict[str, PrintingPrice]:
        from src.services.pricing_service import pricing_service
        from src.services.ygo_api import ygo_service

        if not os.path.exists(ygo_service._get_db_file('en')):
            raise RuntimeError('La base de cartas de Yu-Gi-Oh aún no está descargada.')
        return ygo_to_prices(ygo_service._read_db_file('en'), self.market, pricing_service.daily_pricing)


class YugiohCardmarketSource(_YugiohSource):
    market = 'cardmarket'


class YugiohTcgplayerSource(_YugiohSource):
    market = 'tcgplayer'
