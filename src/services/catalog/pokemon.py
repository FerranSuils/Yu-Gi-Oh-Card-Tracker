"""Pokémon TCG catalog from the public PokemonTCG/pokemon-tcg-data repository."""

from __future__ import annotations

import logging

import requests

from src.core.catalog_models import CatalogCard, CatalogPrinting
from src.services.catalog.base import CatalogProvider
from src.services.catalog.registry import catalog_path
from src.services.catalog.store import CatalogStore

logger = logging.getLogger(__name__)

BASE_URL = 'https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master'
HEADERS = {'User-Agent': 'OpenYuGi/1.0'}


def _card(raw: dict, set_id: str, set_name: str) -> CatalogCard:
    images = raw.get('images') or {}
    return CatalogCard(
        game='pokemon', card_id=raw['id'], name=raw.get('name', ''),
        printings=[CatalogPrinting(
            printing_id=raw['id'], set_code=set_id, set_name=set_name, number=raw.get('number'),
            rarity=raw.get('rarity'), image_url=images.get('large'), image_url_small=images.get('small'),
        )],
        attributes={key: raw.get(key) for key in ('supertype', 'subtypes', 'hp', 'types')},
    )


class PokemonProvider(CatalogProvider):
    game = 'pokemon'
    display_name = 'Pokémon TCG'

    def __init__(self, store: CatalogStore | None = None):
        self.store = store or CatalogStore(catalog_path(self.game))

    def fetch(self) -> list[CatalogCard]:
        listing = requests.get(f'{BASE_URL}/sets/en.json', headers=HEADERS, timeout=30)
        listing.raise_for_status()
        cards: list[CatalogCard] = []
        for card_set in listing.json():
            response = requests.get(f"{BASE_URL}/cards/en/{card_set['id']}.json", headers=HEADERS, timeout=30)
            if response.status_code == 404:
                logger.warning('Pokémon set %s has no card file; skipping it', card_set['id'])
                continue
            response.raise_for_status()
            cards.extend(_card(raw, card_set['id'], card_set.get('name', card_set['id']))
                         for raw in response.json() if raw.get('id'))
        return cards
