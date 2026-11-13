"""Magic prices: Cardmarket's official daily guide and Scryfall's TCGplayer USD."""

from __future__ import annotations

import json
import logging
from typing import Iterable

import requests

from src.core.pricing_models import PriceQuote, PrintingPrice, to_price
from src.services.prices.base import PriceSource
from src.services.prices.registry import price_path
from src.services.prices.store import PriceStore

logger = logging.getLogger(__name__)

GUIDE_URL = 'https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json'
HEADERS = {'User-Agent': 'OpenYuGi/1.0', 'Accept': 'application/json'}
METRICS = ('low', 'avg', 'trend', 'avg1', 'avg7', 'avg30')


def _quote(values: dict) -> PriceQuote | None:
    quote = PriceQuote(**{metric: to_price(values.get(metric)) for metric in METRICS})
    return quote if any(getattr(quote, metric) is not None for metric in METRICS) else None


def guide_to_prices(guide: dict, cm_to_printing: dict[str, list[str]]) -> dict[str, PrintingPrice]:
    """Cardmarket price guide rows, keyed by the catalog printings that share each product."""
    prices: dict[str, PrintingPrice] = {}
    for row in guide.get('priceGuides') or []:
        printings = cm_to_printing.get(str(row.get('idProduct')))
        if not printings:
            continue
        normal = _quote(row)
        foil = _quote({metric: row.get(f'{metric}-foil') for metric in METRICS})
        if normal is None and foil is None:
            continue
        for printing_id in printings:
            prices[printing_id] = PrintingPrice(normal=normal, foil=foil)
    return prices


def scryfall_lines_to_prices(lines: Iterable[str]) -> dict[str, PrintingPrice]:
    prices: dict[str, PrintingPrice] = {}
    for line in lines:
        line = (line or '').strip().rstrip(',')
        if not line or line in ('[', ']'):
            continue
        try:
            raw = json.loads(line)
        except ValueError:
            continue
        if not isinstance(raw, dict) or not raw.get('id'):
            continue
        usd = to_price((raw.get('prices') or {}).get('usd'))
        usd_foil = to_price((raw.get('prices') or {}).get('usd_foil'))
        if usd is None and usd_foil is None:
            continue
        prices[raw['id']] = PrintingPrice(normal=PriceQuote(trend=usd) if usd else None,
                                          foil=PriceQuote(trend=usd_foil) if usd_foil else None)
    return prices


def _magic_catalog():
    from src.services.catalog import get_provider

    return get_provider('magic')


class MagicCardmarketSource(PriceSource):
    game = 'magic'
    market = 'cardmarket'

    def __init__(self, store: PriceStore | None = None, catalog=None):
        self.store = store or PriceStore(price_path(self.game, self.market))
        self._catalog = catalog

    def fetch(self) -> dict[str, PrintingPrice]:
        catalog = self._catalog or _magic_catalog()
        cm_to_printing: dict[str, list[str]] = {}
        for card in catalog.store.load():
            for printing in card.printings:
                product = printing.market_ids.get('cardmarket')
                if product:
                    cm_to_printing.setdefault(product, []).append(printing.printing_id)
        if not cm_to_printing:
            raise RuntimeError('Vuelve a descargar el catálogo de Magic: le faltan los ids de Cardmarket.')
        response = requests.get(GUIDE_URL, headers=HEADERS, timeout=120)
        response.raise_for_status()
        return guide_to_prices(response.json(), cm_to_printing)


class MagicTcgplayerSource(PriceSource):
    game = 'magic'
    market = 'tcgplayer'

    def __init__(self, store: PriceStore | None = None):
        self.store = store or PriceStore(price_path(self.game, self.market))

    def fetch(self) -> dict[str, PrintingPrice]:
        from src.services.catalog.magic import BULK_URL, HEADERS as SCRYFALL_HEADERS, _dump_lines

        listing = requests.get(BULK_URL, headers=SCRYFALL_HEADERS, timeout=30)
        listing.raise_for_status()
        entry = next(d for d in listing.json()['data'] if d.get('type') == 'default_cards')
        url = entry.get('jsonl_download_uri') or entry['download_uri']
        dump = requests.get(url, headers=SCRYFALL_HEADERS, stream=True, timeout=60)
        dump.raise_for_status()
        return scryfall_lines_to_prices(_dump_lines(dump, url))
