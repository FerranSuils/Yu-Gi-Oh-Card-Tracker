import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from src.core.models import ApiCard
from src.services.catalog import game_ids
from src.services.catalog.pokemon import BASE_URL, PokemonProvider
from src.services.catalog.store import CatalogStore
from src.services.catalog.yugioh import catalog_card_from_api

FIXTURES = Path(__file__).parent / 'fixtures' / 'catalog'


def _response(payload=None, status=200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f'{status}')
    return response


def _fake_get(url, **kwargs):
    if url == f'{BASE_URL}/sets/en.json':
        return _response(json.loads((FIXTURES / 'pokemon_sets.json').read_text(encoding='utf-8')))
    if url == f'{BASE_URL}/cards/en/base1.json':
        return _response(json.loads((FIXTURES / 'pokemon_base1.json').read_text(encoding='utf-8')))
    return _response(status=404)


def _fetch(tmp_path):
    with patch('src.services.catalog.pokemon.requests.get', side_effect=_fake_get):
        return PokemonProvider(CatalogStore(str(tmp_path / 'pokemon.json'))).fetch()


def test_pokemon_maps_card_fields(tmp_path):
    [card] = _fetch(tmp_path)
    assert (card.game, card.card_id, card.name) == ('pokemon', 'base1-4', 'Charizard')
    [printing] = card.printings
    assert (printing.printing_id, printing.set_code, printing.set_name, printing.number, printing.rarity) == (
        'base1-4', 'base1', 'Base', '4', 'Rare Holo')
    assert printing.image_url.endswith('4_hires.png') and printing.image_url_small.endswith('4.png')
    assert card.attributes == {'supertype': 'Pokémon', 'subtypes': ['Stage 2'], 'hp': '120', 'types': ['Fire']}


def test_pokemon_skips_missing_set_file(tmp_path):
    assert [c.card_id for c in _fetch(tmp_path)] == ['base1-4']


def test_yugioh_converts_api_card():
    api = ApiCard(id=89631139, name='Blue-Eyes White Dragon', type='Normal Monster', frameType='normal',
                  desc='Legendary.', card_images=[{'id': 89631139, 'image_url': 'https://i/89631139.jpg',
                                                   'image_url_small': 'https://i/s/89631139.jpg'}],
                  card_sets=[{'set_name': 'Legend of Blue Eyes', 'set_code': 'LOB-EN001', 'set_rarity': 'Ultra Rare'},
                             {'set_name': 'Starter Deck Kaiba', 'set_code': 'SDK-001', 'set_rarity': 'Ultra Rare',
                              'variant_id': 'v-sdk'}])
    card = catalog_card_from_api(api)
    assert (card.game, card.card_id, card.name) == ('yugioh', '89631139', 'Blue-Eyes White Dragon')
    assert [p.printing_id for p in card.printings] == ['LOB-EN001:Ultra Rare', 'v-sdk']
    assert card.printings[0].image_url == 'https://i/89631139.jpg'


def test_registered_games_in_order():
    assert game_ids() == ['yugioh', 'magic', 'pokemon']
