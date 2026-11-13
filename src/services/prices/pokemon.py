"""Pokémon prices from the free pokemontcg.io API (Cardmarket EUR and TCGplayer USD)."""

from __future__ import annotations

import json
import logging
import os
import time

import requests

from src.core.pricing_models import PriceQuote, PrintingPrice, to_price
from src.services.prices.base import PriceSource
from src.services.prices.registry import price_path
from src.services.catalog.store import _write_atomic
from src.services.prices.store import PriceStore

logger = logging.getLogger(__name__)

API_URL = 'https://api.pokemontcg.io/v2/cards'
HEADERS = {'User-Agent': 'OpenYuGi/1.0', 'Accept': 'application/json'}
PAGE_SIZE = 100  # 250-card pages fail far more often than 100-card ones
# The API often answers 500/502 and sometimes is down for minutes; back off before giving up.
ATTEMPTS = 12
PAUSE_SECONDS = 1.0
PARTIAL_MAX_AGE = 24 * 3600  # older progress is thrown away: prices would be too mixed

CARDMARKET_NORMAL = {'low': 'lowPrice', 'avg': 'averageSellPrice', 'trend': 'trendPrice',
                     'avg1': 'avg1', 'avg7': 'avg7', 'avg30': 'avg30'}
CARDMARKET_FOIL = {'low': 'reverseHoloLow', 'avg': 'reverseHoloSell', 'trend': 'reverseHoloTrend',
                   'avg1': 'reverseHoloAvg1', 'avg7': 'reverseHoloAvg7', 'avg30': 'reverseHoloAvg30'}


def _quote(values: dict, mapping: dict) -> PriceQuote | None:
    quote = PriceQuote(**{metric: to_price(values.get(field)) for metric, field in mapping.items()})
    return quote if any(v is not None for v in quote.model_dump().values()) else None


def _tcgplayer_quote(values: dict | None) -> PriceQuote | None:
    if not values:
        return None
    return _quote(values, {'trend': 'market', 'avg': 'mid', 'low': 'low'})


def pokemon_cards_to_prices(cards: list[dict], market: str) -> dict[str, PrintingPrice]:
    prices: dict[str, PrintingPrice] = {}
    for card in cards:
        if not card.get('id'):
            continue
        if market == 'cardmarket':
            values = (card.get('cardmarket') or {}).get('prices') or {}
            normal, foil = _quote(values, CARDMARKET_NORMAL), _quote(values, CARDMARKET_FOIL)
        else:
            finishes = (card.get('tcgplayer') or {}).get('prices') or {}
            normal = _tcgplayer_quote(finishes.get('normal')) or _tcgplayer_quote(finishes.get('holofoil'))
            foil = _tcgplayer_quote(finishes.get('holofoil')) or _tcgplayer_quote(finishes.get('reverseHolofoil'))
        if normal or foil:
            prices[card['id']] = PrintingPrice(normal=normal, foil=foil)
    return prices


class _PokemonSource(PriceSource):
    game = 'pokemon'

    def __init__(self, store: PriceStore | None = None):
        self.store = store or PriceStore(price_path(self.game, self.market))

    def _page(self, page: int) -> list[dict]:
        url = f'{API_URL}?page={page}&pageSize={PAGE_SIZE}&select=id,cardmarket,tcgplayer'
        last = None
        for attempt in range(ATTEMPTS):
            try:
                response = requests.get(url, headers=HEADERS, timeout=90)
                if response.status_code == 200:
                    return response.json().get('data') or []
                last = f'HTTP {response.status_code}'
            except requests.RequestException as exc:
                last = str(exc)
            time.sleep(min(5 * 2 ** attempt, 60))  # outages last minutes: wait up to ~9 min per page
        raise RuntimeError(f'pokemontcg.io no respondió (página {page}): {last}')

    @property
    def _partial_path(self) -> str:
        return self.store.path + '.partial.json'

    def _load_partial(self) -> tuple[list[dict], int]:
        """Pages already downloaded by an earlier, interrupted run (kept for a day)."""
        try:
            with open(self._partial_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
            if time.time() - float(data.get('started', 0)) < PARTIAL_MAX_AGE:
                return list(data.get('cards') or []), int(data.get('next_page') or 1)
        except (OSError, ValueError, TypeError):
            pass
        return [], 1

    def _save_partial(self, cards: list[dict], next_page: int, started: float) -> None:
        try:
            _write_atomic(self._partial_path, json.dumps(
                {'started': started, 'next_page': next_page, 'cards': cards}, separators=(',', ':')))
        except OSError as exc:
            logger.warning('Could not keep Pokémon download progress: %s', exc)

    def fetch(self) -> dict[str, PrintingPrice]:
        # The API has outages of several minutes, so a full download can take more than one try:
        # keep the pages fetched so far and resume from the first missing page next time.
        cards, page = self._load_partial()
        started = time.time() if page == 1 else self._started_of_partial()
        while True:
            try:
                batch = self._page(page)
            except RuntimeError:
                self._save_partial(cards, page, started)
                raise
            if not batch:
                break
            cards.extend(batch)
            page += 1
            time.sleep(PAUSE_SECONDS)
        try:
            os.remove(self._partial_path)
        except OSError:
            pass
        return pokemon_cards_to_prices(cards, self.market)

    def _started_of_partial(self) -> float:
        try:
            with open(self._partial_path, 'r', encoding='utf-8') as file:
                return float(json.load(file).get('started') or time.time())
        except (OSError, ValueError, TypeError):
            return time.time()


class PokemonCardmarketSource(_PokemonSource):
    market = 'cardmarket'


class PokemonTcgplayerSource(_PokemonSource):
    market = 'tcgplayer'
