import pytest

from src.core.catalog_models import CatalogCard, CatalogPrinting
from src.services.catalog.base import CatalogProvider
from src.services.catalog.registry import get_provider
from src.services.catalog.store import CatalogStore


def _card(card_id, name, set_code='aaa', rarity='common'):
    return CatalogCard(game='magic', card_id=card_id, name=name, printings=[
        CatalogPrinting(printing_id=f'{card_id}-p', set_code=set_code, set_name=f'Set {set_code}', rarity=rarity)])


CARDS = [
    _card('1', 'Lightning Bolt', 'lea', 'common'),
    _card('2', 'Æther Vial', 'dst', 'uncommon'),
    _card('3', 'Black Lotus', 'lea', 'rare'),
]


class FakeProvider(CatalogProvider):
    game = 'magic'
    display_name = 'Fake'

    def __init__(self, store, result):
        self.store = store
        self.result = result

    def fetch(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_replace_then_load_round_trip(tmp_path):
    store = CatalogStore(str(tmp_path / 'magic.json'))
    store.replace(CARDS)
    again = CatalogStore(str(tmp_path / 'magic.json'))
    assert [c.name for c in again.load()] == ['Lightning Bolt', 'Æther Vial', 'Black Lotus']
    assert again.info()['count'] == 3 and again.info()['updated_at']


def test_refresh_failure_keeps_previous_catalog(tmp_path):
    store = CatalogStore(str(tmp_path / 'magic.json'))
    assert FakeProvider(store, CARDS).refresh() == 3
    with pytest.raises(RuntimeError):
        FakeProvider(store, RuntimeError('network down')).refresh()
    assert len(CatalogStore(str(tmp_path / 'magic.json')).load()) == 3


def test_corrupt_file_reads_as_empty(tmp_path):
    path = tmp_path / 'magic.json'
    path.write_text('{not json', encoding='utf-8')
    store = CatalogStore(str(path))
    assert store.load() == []
    assert store.info()['count'] == 0


def test_search_filters_by_set_and_rarity(tmp_path):
    store = CatalogStore(str(tmp_path / 'magic.json'))
    store.replace(CARDS)
    assert {c.name for c in store.search('', set_code='lea')} == {'Lightning Bolt', 'Black Lotus'}
    assert [c.name for c in store.search('', set_code='lea', rarity='rare')] == ['Black Lotus']
    assert store.sets() == [('lea', 'Set lea'), ('dst', 'Set dst')] or store.sets() == [('dst', 'Set dst'), ('lea', 'Set lea')]
    assert store.get('2').name == 'Æther Vial' and store.get('nope') is None


def test_search_is_case_insensitive_and_handles_empty_query(tmp_path):
    store = CatalogStore(str(tmp_path / 'magic.json'))
    store.replace(CARDS)
    assert [c.name for c in store.search('æther')] == ['Æther Vial']
    assert [c.name for c in store.search('BOLT')] == ['Lightning Bolt']
    assert len(store.search('', limit=2)) == 2
    assert store.search('[(*') == []


def test_get_provider_unknown_game_raises():
    with pytest.raises(KeyError):
        get_provider('no-such-game')


def test_empty_fetch_never_wipes_the_catalog(tmp_path):
    store = CatalogStore(str(tmp_path / 'magic.json'))
    FakeProvider(store, CARDS).refresh()
    with pytest.raises(RuntimeError):
        FakeProvider(store, []).refresh()
    assert len(CatalogStore(str(tmp_path / 'magic.json')).load()) == 3


def test_info_reads_metadata_without_loading_cards(tmp_path):
    CatalogStore(str(tmp_path / 'magic.json')).replace(CARDS)
    store = CatalogStore(str(tmp_path / 'magic.json'))
    assert store.info()['count'] == 3
    assert FakeProvider(store, CARDS).is_available()
    assert store._cards is None


def test_second_refresh_while_one_runs_is_refused(tmp_path):
    import threading

    store = CatalogStore(str(tmp_path / 'magic.json'))
    started, release = threading.Event(), threading.Event()

    class Slow(FakeProvider):
        def fetch(self):
            started.set()
            release.wait(5)
            return CARDS

    provider = Slow(store, CARDS)
    worker = threading.Thread(target=provider.refresh)
    worker.start()
    started.wait(5)
    with pytest.raises(RuntimeError):
        provider.refresh()
    release.set()
    worker.join(5)
    assert store.info()['count'] == 3
