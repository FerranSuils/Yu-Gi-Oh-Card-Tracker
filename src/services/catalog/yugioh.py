"""Read-only view of the existing Yu-Gi-Oh database through the catalog interface.

The Yu-Gi-Oh pages keep using ``ygo_service`` directly; this adapter only feeds
game-neutral features.
"""

from __future__ import annotations

import os

from src.core.catalog_models import CatalogCard, CatalogPrinting
from src.core.models import ApiCard
from src.services.catalog.base import CatalogProvider
from src.services.catalog.registry import catalog_path
from src.services.catalog.store import CatalogStore


def catalog_card_from_api(card: ApiCard) -> CatalogCard:
    image = card.card_images[0] if card.card_images else None
    return CatalogCard(
        game='yugioh', card_id=str(card.id), name=card.name,
        printings=[CatalogPrinting(
            printing_id=s.variant_id or f'{s.set_code}:{s.set_rarity}', set_code=s.set_code,
            set_name=s.set_name, rarity=s.set_rarity,
            image_url=image.image_url if image else None,
            image_url_small=image.image_url_small if image else None,
        ) for s in card.card_sets],
        attributes={'type': card.type, 'attribute': card.attribute, 'race': card.race},
    )


class YugiohProvider(CatalogProvider):
    game = 'yugioh'
    display_name = 'Yu-Gi-Oh!'

    def __init__(self, store: CatalogStore | None = None):
        self.store = store or CatalogStore(catalog_path(self.game))

    def fetch(self) -> list[CatalogCard]:
        # Rebuilds from the local database only; downloading it stays in Settings > Data management.
        from src.services.ygo_api import parse_cards_data, ygo_service

        if not os.path.exists(ygo_service._get_db_file('en')):
            raise RuntimeError('La base de cartas de Yu-Gi-Oh aún no está descargada.')
        return [catalog_card_from_api(card) for card in parse_cards_data(ygo_service._read_db_file('en'))]
