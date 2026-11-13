from src.core.catalog_models import (
    CatalogCard,
    GameCollection,
    GameCollectionCard,
    GameCollectionVariant,
)
from src.core.models import CollectionEntry


def test_game_collection_round_trips_through_json():
    col = GameCollection(game='magic', name='Mis cartas', cards=[GameCollectionCard(
        card_id='o1', name='Lightning Bolt', variants=[GameCollectionVariant(
            printing_id='p1', set_code='lea', entries=[CollectionEntry(quantity=3)])])])
    again = GameCollection(**col.model_dump(mode='json'))
    assert again == col and again.total_cards == 3
    assert again.cards[0].variants[0].finish == 'nonfoil'


def test_catalog_card_defaults():
    card = CatalogCard(game='pokemon', card_id='base1-4', name='Charizard')
    assert card.printings == [] and card.attributes == {}
