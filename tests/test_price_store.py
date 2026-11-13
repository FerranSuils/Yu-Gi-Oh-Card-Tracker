import threading

import pytest

from src.core.pricing_models import PriceQuote, PrintingPrice
from src.services.prices.base import PriceSource
from src.services.prices.registry import MARKETS, get_source, price_path
from src.services.prices.store import PriceStore

PRICES = {
    'p1': PrintingPrice(normal=PriceQuote(trend=1.5, low=1.0), foil=PriceQuote(trend=4.0)),
    'p2': PrintingPrice(normal=PriceQuote(trend=0.2), scope='card'),
}


class FakeSource(PriceSource):
    game = 'magic'
    market = 'cardmarket'

    def __init__(self, store, result):
        self.store = store
        self.result = result

    def fetch(self):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_round_trip(tmp_path):
    PriceStore(str(tmp_path / 'm.json')).replace(PRICES)
    store = PriceStore(str(tmp_path / 'm.json'))
    assert store.get('p1').foil.trend == 4.0 and store.get('p2').scope == 'card'
    assert store.get('nope') is None
    assert '"avg"' not in (tmp_path / 'm.json').read_text(encoding='utf-8')  # None values are not written


def test_info_without_loading(tmp_path):
    PriceStore(str(tmp_path / 'm.json')).replace(PRICES)
    store = PriceStore(str(tmp_path / 'm.json'))
    info = store.info()
    assert info['count'] == 2 and info['updated_at']
    assert store._prices is None
    assert PriceStore(str(tmp_path / 'none.json')).info() == {'count': 0, 'updated_at': None}


def test_corrupt_file_reads_as_empty(tmp_path):
    (tmp_path / 'm.json').write_text('{oops', encoding='utf-8')
    assert PriceStore(str(tmp_path / 'm.json')).load() == {}


def test_failed_fetch_keeps_file(tmp_path):
    store = PriceStore(str(tmp_path / 'm.json'))
    assert FakeSource(store, PRICES).refresh() == 2
    with pytest.raises(RuntimeError):
        FakeSource(store, RuntimeError('network down')).refresh()
    assert len(PriceStore(str(tmp_path / 'm.json')).load()) == 2


def test_empty_fetch_keeps_file(tmp_path):
    store = PriceStore(str(tmp_path / 'm.json'))
    FakeSource(store, PRICES).refresh()
    with pytest.raises(RuntimeError, match='no trajo precios'):
        FakeSource(store, {}).refresh()
    assert len(PriceStore(str(tmp_path / 'm.json')).load()) == 2


def test_concurrent_refresh_refused(tmp_path):
    store = PriceStore(str(tmp_path / 'm.json'))
    started, release = threading.Event(), threading.Event()

    class Slow(FakeSource):
        def fetch(self):
            started.set()
            release.wait(5)
            return PRICES

    source = Slow(store, PRICES)
    worker = threading.Thread(target=source.refresh)
    worker.start()
    started.wait(5)
    with pytest.raises(RuntimeError):
        source.refresh()
    release.set()
    worker.join(5)
    assert store.info()['count'] == 2


def test_registry():
    assert MARKETS == {'cardmarket': 'EUR', 'tcgplayer': 'USD'}
    import os
    assert os.path.normpath(price_path('magic', 'cardmarket')) == os.path.normpath('data/prices/magic-cardmarket.json')
    with pytest.raises(KeyError):
        get_source('nope', 'cardmarket')
