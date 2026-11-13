"""Magic: The Gathering catalog from Scryfall's free bulk data."""

from __future__ import annotations

import gzip
import io
import json
import logging
from typing import Iterable

import requests

from src.core.catalog_models import CatalogCard, CatalogPrinting
from src.services.catalog.base import CatalogProvider
from src.services.catalog.registry import catalog_path
from src.services.catalog.store import CatalogStore

logger = logging.getLogger(__name__)

BULK_URL = 'https://api.scryfall.com/bulk-data'
# Scryfall asks every client for a User-Agent and an Accept header.
HEADERS = {'User-Agent': 'OpenYuGi/1.0', 'Accept': 'application/json'}


def _images(card: dict) -> dict:
    if card.get('image_uris'):
        return card['image_uris']
    faces = card.get('card_faces') or []
    if faces and faces[0].get('image_uris'):
        return faces[0]['image_uris']
    return {}


def cards_from_jsonl(lines: Iterable[str]) -> list[CatalogCard]:
    by_oracle: dict[str, CatalogCard] = {}
    for line in lines:
        line = (line or '').strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except ValueError:
            logger.warning('Skipping an unreadable Scryfall line')
            continue
        oracle_id = raw.get('oracle_id') if isinstance(raw, dict) else None
        if not oracle_id or not raw.get('id') or not raw.get('set'):
            continue
        card = by_oracle.get(oracle_id)
        if card is None:
            card = by_oracle[oracle_id] = CatalogCard(
                game='magic', card_id=oracle_id, name=raw.get('name', ''),
                attributes={'type_line': raw.get('type_line'), 'mana_cost': raw.get('mana_cost'),
                            'colors': raw.get('colors')},
            )
        images = _images(raw)
        card.printings.append(CatalogPrinting(
            printing_id=raw['id'], set_code=raw['set'], set_name=raw.get('set_name', raw['set']),
            number=raw.get('collector_number'), rarity=raw.get('rarity'),
            image_url=images.get('normal'), image_url_small=images.get('small'),
            finishes=list(raw.get('finishes') or []),
            market_ids={market: str(raw[f'{market}_id']) for market in ('cardmarket', 'tcgplayer')
                        if raw.get(f'{market}_id')},
        ))
    return list(by_oracle.values())


def _dump_lines(response, url: str):
    """Scryfall serves the dump as .jsonl.gz with Content-Type application/gzip and no
    Content-Encoding, so requests does not decompress it for us."""
    content_type = (getattr(response, 'headers', {}) or {}).get('Content-Type', '')
    if url.endswith('.gz') or 'gzip' in content_type:
        if hasattr(response.raw, 'decode_content'):
            response.raw.decode_content = True
        return io.TextIOWrapper(gzip.GzipFile(fileobj=response.raw), encoding='utf-8')
    return response.iter_lines(decode_unicode=True)


class MagicProvider(CatalogProvider):
    game = 'magic'
    display_name = 'Magic: The Gathering'

    def __init__(self, store: CatalogStore | None = None):
        self.store = store or CatalogStore(catalog_path(self.game))

    def fetch(self) -> list[CatalogCard]:
        listing = requests.get(BULK_URL, headers=HEADERS, timeout=30)
        listing.raise_for_status()
        entry = next(d for d in listing.json()['data'] if d.get('type') == 'default_cards')
        dump = requests.get(entry['jsonl_download_uri'], headers=HEADERS, stream=True, timeout=60)
        dump.raise_for_status()
        return cards_from_jsonl(_dump_lines(dump, entry['jsonl_download_uri']))
