import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.services.catalog.magic import MagicProvider, cards_from_jsonl
from src.services.catalog.store import CatalogStore

FIXTURES = Path(__file__).parent / 'fixtures' / 'catalog'
LINES = (FIXTURES / 'scryfall_default.jsonl').read_text(encoding='utf-8').splitlines()


def test_groups_printings_by_oracle_id():
    bolt = next(c for c in cards_from_jsonl(LINES) if c.card_id == 'o-bolt')
    assert bolt.game == 'magic' and bolt.name == 'Lightning Bolt'
    assert [(p.printing_id, p.set_code, p.number) for p in bolt.printings] == [('p-lea', 'lea', '161'), ('p-m10', 'm10', '146')]
    assert bolt.printings[1].finishes == ['nonfoil', 'foil']
    assert bolt.attributes == {'type_line': 'Instant', 'mana_cost': '{R}', 'colors': ['R']}


def test_double_faced_card_uses_first_face_image():
    delver = next(c for c in cards_from_jsonl(LINES) if c.card_id == 'o-delver')
    assert delver.printings[0].image_url == 'https://img/n/dfc-front.jpg'
    assert delver.printings[0].image_url_small == 'https://img/s/dfc-front.jpg'


def test_skips_bad_lines_and_cards_without_oracle_id():
    assert sorted(c.card_id for c in cards_from_jsonl(LINES)) == ['o-bolt', 'o-delver']


def test_fetch_uses_default_cards_jsonl_with_headers(tmp_path):
    bulk = MagicMock()
    bulk.json.return_value = json.loads((FIXTURES / 'scryfall_bulk.json').read_text(encoding='utf-8'))
    dump = MagicMock()
    dump.iter_lines.return_value = iter(LINES)
    with patch('src.services.catalog.magic.requests.get', side_effect=[bulk, dump]) as get:
        cards = MagicProvider(CatalogStore(str(tmp_path / 'magic.json'))).fetch()
    assert len(cards) == 2
    first, second = get.call_args_list
    assert first.args[0] == 'https://api.scryfall.com/bulk-data'
    assert second.args[0] == 'https://data.scryfall.io/default-cards.jsonl'
    assert second.kwargs['stream'] is True
    for call in (first, second):
        assert call.kwargs['headers']['User-Agent'] == 'OpenYuGi/1.0'
        assert call.kwargs['headers']['Accept'] == 'application/json'


def test_fetch_decompresses_the_gzip_dump(tmp_path):
    # Scryfall serves default-cards-*.jsonl.gz as application/gzip without Content-Encoding.
    import gzip
    import io

    bulk = MagicMock()
    bulk.json.return_value = {'data': [{'type': 'default_cards',
                                        'jsonl_download_uri': 'https://data.scryfall.io/default-cards.jsonl.gz'}]}
    dump = MagicMock()
    dump.headers = {'Content-Type': 'application/gzip'}
    dump.raw = io.BytesIO(gzip.compress('\n'.join(LINES).encode('utf-8')))
    with patch('src.services.catalog.magic.requests.get', side_effect=[bulk, dump]):
        cards = MagicProvider(CatalogStore(str(tmp_path / 'magic.json'))).fetch()
    assert sorted(c.card_id for c in cards) == ['o-bolt', 'o-delver']


def test_cards_from_jsonl_keeps_market_ids():
    cards = {c.card_id: c for c in cards_from_jsonl((FIXTURES / 'scryfall_default.jsonl').read_text(encoding='utf-8').splitlines())}
    printings = {p.printing_id: p for p in cards['o-bolt'].printings}
    assert printings['p-m10'].market_ids == {'cardmarket': '21390', 'tcgplayer': '33459'}
    assert printings['p-lea'].market_ids == {}


def test_old_catalog_json_loads_without_market_ids():
    from src.core.catalog_models import CatalogPrinting

    assert CatalogPrinting(printing_id='x', set_code='s', set_name='S').market_ids == {}
