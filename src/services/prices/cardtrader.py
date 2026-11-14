"""CardTrader prices for Yu-Gi-Oh: the cheapest Near Mint listing in euros, per printing.

Official API (https://api.cardtrader.com/api/v2) with the token of the person running the server
(OPENYUGI_CARDTRADER_TOKEN, from their CardTrader profile settings). Limits: 200 requests per
10 seconds in all, 10 per second on the marketplace: one expansion per request, paced.
The token is only ever sent to api.cardtrader.com and never appears in errors, logs or reprs.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

from src.core.pricing_models import PriceQuote, PrintingPrice, to_price
from src.services.prices.base import PriceSource
from src.services.prices.registry import price_path
from src.services.prices.store import PriceStore

logger = logging.getLogger(__name__)
API = 'https://api.cardtrader.com/api/v2'
TIMEOUT = 40
PACE_SECONDS = 0.15  # under 10 requests a second
TOKEN_ENV = 'OPENYUGI_CARDTRADER_TOKEN'
NEAR_MINT_OR_BETTER = {'Near Mint', 'Mint'}
CURRENCY = 'EUR'


class CardTraderError(Exception):
    """Something CardTrader refused or that could not reach it, worded for the person."""


def blueprint_key(collector_number: str, rarity: str) -> str:
    # Same key as the collections' printing id (set code : rarity).
    return f'{collector_number}:{rarity}'


class CardTraderClient:
    def __init__(self, token: str, http=None):
        self._token = token
        self._http = http or requests

    def __repr__(self) -> str:
        return 'CardTraderClient(…)'

    def _get(self, path: str, params: Optional[dict] = None):
        time.sleep(PACE_SECONDS)
        try:
            reply = self._http.request('GET', f'{API}{path}', params=params, timeout=TIMEOUT,
                                       headers={'Authorization': f'Bearer {self._token}', 'User-Agent': 'OpenYuGi/1.0'})
        except requests.RequestException:
            raise CardTraderError('No se pudo conectar con CardTrader.') from None
        if reply.status_code == 401:
            raise CardTraderError('El token de CardTrader no es válido o se ha revocado.')
        if reply.status_code == 429:
            raise CardTraderError('CardTrader pide ir más despacio (demasiadas peticiones). Se reintentará.')
        if reply.status_code != 200:
            raise CardTraderError(f'CardTrader respondió con un error ({reply.status_code}).')
        try:
            return reply.json()
        except ValueError:
            raise CardTraderError('CardTrader devolvió una respuesta ilegible.') from None

    def yugioh_game_id(self) -> int:
        for game in self._get('/games') or []:
            name = f"{game.get('name', '')} {game.get('display_name', '')}".lower()
            if 'yu-gi-oh' in name or 'yugioh' in name:
                return int(game['id'])
        raise CardTraderError('CardTrader no lista Yu-Gi-Oh.')

    def expansions(self, game_id: int) -> list:
        return [e for e in self._get('/expansions') or [] if e.get('game_id') == game_id]

    def blueprints(self, expansion_id: int) -> list:
        return self._get('/blueprints/export', {'expansion_id': expansion_id}) or []

    def products(self, expansion_id: int) -> dict:
        body = self._get('/marketplace/products', {'expansion_id': expansion_id})
        return body if isinstance(body, dict) else {}


def cheapest_near_mint(listings: list) -> Optional[float]:
    best = None
    for item in listings or []:
        price = item.get('price') or {}
        if price.get('currency') != CURRENCY:
            continue
        if (item.get('properties_hash') or {}).get('condition') not in NEAR_MINT_OR_BETTER:
            continue
        euros = to_price((price.get('cents') or 0) / 100)
        if euros is not None and (best is None or euros < best):
            best = euros
    return best


class YugiohCardtraderSource(PriceSource):
    game = 'yugioh'
    market = 'cardtrader'

    def __init__(self, client: CardTraderClient, store: PriceStore | None = None):
        self.client = client
        self.store = store or PriceStore(price_path(self.game, self.market))

    def fetch(self) -> dict[str, PrintingPrice]:
        game = self.client.yugioh_game_id()
        prices: dict[str, PrintingPrice] = {}
        for expansion in self.client.expansions(game):
            blueprints = {}
            for blueprint in self.client.blueprints(expansion['id']):
                fixed = blueprint.get('fixed_properties') or {}
                code = fixed.get('collector_number')
                if code:
                    blueprints[str(blueprint['id'])] = (str(code), str(fixed.get('yugioh_rarity') or ''))
            if not blueprints:
                continue
            for blueprint_id, listings in self.client.products(expansion['id']).items():
                found = blueprints.get(str(blueprint_id))
                price = cheapest_near_mint(listings)
                if not found or price is None:
                    continue
                code, rarity = found
                quote = PrintingPrice(normal=PriceQuote(low=price, trend=price))
                if rarity:
                    prices[blueprint_key(code, rarity)] = quote
                current = prices.get(code)  # by code alone: the cheapest of its rarities
                if current is None or price < current.normal.low:
                    prices[code] = quote
        return prices


def build_source(token: Optional[str] = None) -> Optional[YugiohCardtraderSource]:
    token = (os.environ.get(TOKEN_ENV, '') if token is None else token).strip()
    return YugiohCardtraderSource(CardTraderClient(token)) if token else None


_shared: Optional[PriceStore] = None


def shared_store() -> PriceStore:
    """The downloaded CardTrader prices, loaded once and reused by every page."""
    global _shared
    if _shared is None:
        _shared = PriceStore(price_path('yugioh', 'cardtrader'))
    return _shared


def lowest_for_card(card_sets, store: PriceStore) -> Optional[float]:
    """The cheapest CardTrader price among the printings of one card, for the card detail."""
    best = None
    for card_set in card_sets or []:
        for key in (blueprint_key(card_set.set_code, card_set.set_rarity), card_set.set_code):
            price = store.get(key)
            if price and price.normal and price.normal.low is not None:
                best = price.normal.low if best is None else min(best, price.normal.low)
    return best
