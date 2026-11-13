from unittest.mock import MagicMock, patch

import pytest

from src.core.catalog_models import CatalogCard, CatalogPrinting
from src.services.prices.magic import MagicCardmarketSource, guide_to_prices, scryfall_lines_to_prices
from src.services.prices.pokemon import PokemonCardmarketSource, pokemon_cards_to_prices
from src.services.prices.store import PriceStore
from src.services.prices.yugioh import ygo_to_prices

GUIDE = {'version': 1, 'createdAt': '2026-11-11T02:00:00+0100', 'priceGuides': [
    {'idProduct': 21390, 'idCategory': 1, 'avg': 1.2, 'low': 0.5, 'trend': 1.1, 'avg1': 1.0, 'avg7': 1.3,
     'avg30': 1.25, 'avg-foil': 5.0, 'low-foil': 3.0, 'trend-foil': 4.5, 'avg1-foil': None,
     'avg7-foil': 4.8, 'avg30-foil': 4.9},
    {'idProduct': 99999, 'idCategory': 1, 'avg': 9.0, 'low': 8.0, 'trend': 9.5},
    {'idProduct': 5, 'idCategory': 1, 'avg': 0, 'low': 0, 'trend': 0},
]}


def test_guide_to_prices_maps_metrics_and_skips_unknown_products():
    prices = guide_to_prices(GUIDE, {'21390': ['p-m10', 'p-m10-promo'], '5': ['p-zero']})
    assert set(prices) == {'p-m10', 'p-m10-promo'}
    m10 = prices['p-m10']
    assert (m10.normal.low, m10.normal.avg, m10.normal.trend, m10.normal.avg30) == (0.5, 1.2, 1.1, 1.25)
    assert (m10.foil.avg, m10.foil.trend, m10.foil.avg1) == (5.0, 4.5, None)
    assert m10.scope == 'printing'


def test_scryfall_lines_to_prices_reads_usd():
    lines = ['{"id": "p1", "prices": {"usd": "1.50", "usd_foil": "6.00", "eur": "1.10"}}',
             '{"id": "p2", "prices": {"usd": null, "usd_foil": null}}',
             'not json', '']
    prices = scryfall_lines_to_prices(lines)
    assert set(prices) == {'p1'}
    assert prices['p1'].normal.trend == 1.5 and prices['p1'].foil.trend == 6.0


def test_magic_cardmarket_without_market_ids_raises():
    catalog = MagicMock()
    catalog.store.load.return_value = [CatalogCard(game='magic', card_id='o', name='Bolt', printings=[
        CatalogPrinting(printing_id='p', set_code='lea', set_name='Alpha')])]
    source = MagicCardmarketSource(store=PriceStore('unused.json'), catalog=catalog)
    with pytest.raises(RuntimeError, match='Vuelve a descargar el catálogo de Magic'):
        source.fetch()


def test_magic_cardmarket_fetch_joins_by_market_ids():
    catalog = MagicMock()
    catalog.store.load.return_value = [CatalogCard(game='magic', card_id='o', name='Bolt', printings=[
        CatalogPrinting(printing_id='p-m10', set_code='m10', set_name='M10', market_ids={'cardmarket': '21390'})])]
    response = MagicMock(status_code=200)
    response.json.return_value = GUIDE
    with patch('src.services.prices.magic.requests.get', return_value=response) as get:
        prices = MagicCardmarketSource(store=PriceStore('unused.json'), catalog=catalog).fetch()
    assert 'price_guide_1.json' in get.call_args[0][0]
    assert prices['p-m10'].normal.trend == 1.1


POKEMON = [
    {'id': 'pl3-1',
     'tcgplayer': {'prices': {'holofoil': {'low': 40.95, 'mid': 66.49, 'market': 41.05},
                              'reverseHolofoil': {'low': 41.54, 'mid': 89.99, 'market': 54.65}}},
     'cardmarket': {'prices': {'averageSellPrice': 6.89, 'lowPrice': 0.99, 'trendPrice': 8.48, 'avg1': 4.0,
                               'avg7': 5.31, 'avg30': 7.38, 'reverseHoloSell': 6.7, 'reverseHoloLow': 3.39,
                               'reverseHoloTrend': 7.77, 'reverseHoloAvg1': 3.99, 'reverseHoloAvg7': 7.54,
                               'reverseHoloAvg30': 10.5}}},
    {'id': 'base1-1', 'tcgplayer': {'prices': {'normal': {'low': 1.0, 'mid': 2.0, 'market': 1.5}}},
     'cardmarket': {'prices': {'averageSellPrice': 1.0, 'lowPrice': 0.5, 'trendPrice': 0.9,
                               'reverseHoloTrend': 0.0, 'reverseHoloSell': 0.0, 'reverseHoloLow': 0.0}}},
    {'id': 'none-1'},
]


def test_pokemon_cardmarket_maps_reverse_holo_to_foil():
    prices = pokemon_cards_to_prices(POKEMON, 'cardmarket')
    assert set(prices) == {'pl3-1', 'base1-1'}
    pl3 = prices['pl3-1']
    assert (pl3.normal.avg, pl3.normal.low, pl3.normal.trend, pl3.normal.avg7) == (6.89, 0.99, 8.48, 5.31)
    assert (pl3.foil.avg, pl3.foil.low, pl3.foil.trend, pl3.foil.avg30) == (6.7, 3.39, 7.77, 10.5)
    assert prices['base1-1'].foil is None


def test_pokemon_tcgplayer_uses_holofoil_when_there_is_no_normal():
    prices = pokemon_cards_to_prices(POKEMON, 'tcgplayer')
    pl3 = prices['pl3-1']
    assert (pl3.normal.trend, pl3.normal.avg, pl3.normal.low) == (41.05, 66.49, 40.95)
    assert pl3.foil.trend == 41.05  # holofoil wins over reverse holo for the foil quote
    base = prices['base1-1']
    assert base.normal.trend == 1.5 and base.foil is None


def test_pokemon_fetch_paginates_and_retries(tmp_path):
    pages = [MagicMock(status_code=502), MagicMock(status_code=200), MagicMock(status_code=200)]
    pages[1].json.return_value = {'data': POKEMON[:1]}
    pages[2].json.return_value = {'data': []}
    with patch('src.services.prices.pokemon.requests.get', side_effect=pages) as get, \
            patch('src.services.prices.pokemon.time.sleep'):
        prices = PokemonCardmarketSource(store=PriceStore(str(tmp_path / 'p.json'))).fetch()
    assert set(prices) == {'pl3-1'}
    assert get.call_count == 3
    assert 'page=1' in get.call_args_list[0][0][0] and 'page=2' in get.call_args_list[2][0][0]


def test_pokemon_fetch_gives_up_after_repeated_errors(tmp_path):
    with patch('src.services.prices.pokemon.requests.get', return_value=MagicMock(status_code=500)), \
            patch('src.services.prices.pokemon.time.sleep'):
        with pytest.raises(RuntimeError):
            PokemonCardmarketSource(store=PriceStore(str(tmp_path / 'p.json'))).fetch()


YGO_DB = [{'id': 89631139, 'name': 'Blue-Eyes', 'card_sets': [
    {'variant_id': 'v-lob', 'set_code': 'LOB-EN001', 'set_rarity': 'Ultra Rare', 'set_price': '25.10'},
    {'set_code': 'SDK-001', 'set_rarity': 'Ultra Rare', 'set_price': '0'}],
    'card_prices': [{'cardmarket_price': '1.20', 'tcgplayer_price': '2.00'}]}]
MANUAL = {'89631139': {'v-lob': {'cardmarket': {'2026-10-01': 30.0, '2026-11-01': 35.5}}}}


def test_ygo_cardmarket_is_per_card_unless_captured():
    prices = ygo_to_prices(YGO_DB, 'cardmarket', MANUAL)
    assert prices['SDK-001:Ultra Rare'].normal.trend == 1.2
    assert prices['SDK-001:Ultra Rare'].scope == 'card'
    assert prices['v-lob'].normal.trend == 35.5 and prices['v-lob'].scope == 'printing'
    assert ygo_to_prices(YGO_DB, 'cardmarket', {})['v-lob'].scope == 'card'


def test_ygo_tcgplayer_uses_set_price_per_printing():
    prices = ygo_to_prices(YGO_DB, 'tcgplayer', MANUAL)
    assert set(prices) == {'v-lob'}
    assert prices['v-lob'].normal.trend == 25.1 and prices['v-lob'].scope == 'printing'


def test_pokemon_fetch_resumes_after_an_outage(tmp_path):
    store = PriceStore(str(tmp_path / 'pokemon-cardmarket.json'))
    ok_page = MagicMock(status_code=200)
    ok_page.json.return_value = {'data': POKEMON[:1]}
    second = MagicMock(status_code=200)
    second.json.return_value = {'data': POKEMON[1:2]}
    empty = MagicMock(status_code=200)
    empty.json.return_value = {'data': []}
    down = MagicMock(status_code=502)
    from src.services.prices import pokemon as module
    with patch.object(module, 'ATTEMPTS', 2), patch('src.services.prices.pokemon.time.sleep'):
        with patch('src.services.prices.pokemon.requests.get', side_effect=[ok_page, down, down]):
            with pytest.raises(RuntimeError):
                PokemonCardmarketSource(store=store).fetch()
        with patch('src.services.prices.pokemon.requests.get', side_effect=[second, empty]) as get:
            prices = PokemonCardmarketSource(store=store).fetch()
    assert 'page=2' in get.call_args_list[0][0][0]  # resumed, page 1 not downloaded again
    assert set(prices) == {'pl3-1', 'base1-1'}
    assert not (tmp_path / 'pokemon-cardmarket.json.partial.json').exists()
