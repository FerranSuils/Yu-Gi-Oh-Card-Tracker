import pytest

from src.services.prices import cardtrader
from src.services.prices.cardtrader import CardTraderClient, CardTraderError, YugiohCardtraderSource, blueprint_key

TOKEN = 'ct_' + 'a' * 30


class Reply:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body


class FakeHttp:
    """Answers the few CardTrader endpoints the source uses, like the documented API."""

    def __init__(self, products=None, status=200):
        self.calls = []
        self.status = status
        self.products = products if products is not None else {
            '11': [
                {'id': 1, 'blueprint_id': 11, 'price': {'cents': 450, 'currency': 'EUR'},
                 'properties_hash': {'condition': 'Near Mint'}},
                {'id': 2, 'blueprint_id': 11, 'price': {'cents': 300, 'currency': 'EUR'},
                 'properties_hash': {'condition': 'Played'}},
                {'id': 3, 'blueprint_id': 11, 'price': {'cents': 380, 'currency': 'EUR'},
                 'properties_hash': {'condition': 'Near Mint'}},
                {'id': 4, 'blueprint_id': 11, 'price': {'cents': 100, 'currency': 'USD'},
                 'properties_hash': {'condition': 'Near Mint'}},
            ],
            '12': [{'id': 5, 'blueprint_id': 12, 'price': {'cents': 90, 'currency': 'EUR'},
                    'properties_hash': {'condition': 'Moderately Played'}}],
        }

    def request(self, method, url, headers=None, params=None, data=None, timeout=None):
        path = url.split('/api/v2')[1]
        self.calls.append((method, path, params or {}, headers or {}))
        if self.status != 200:
            return Reply({'error': 'x'}, self.status)
        if path == '/games':
            return Reply([{'id': 1, 'name': 'Magic'}, {'id': 5, 'name': 'Yu-Gi-Oh!', 'display_name': 'Yu-Gi-Oh!'}])
        if path == '/expansions':
            return Reply([{'id': 1, 'game_id': 1, 'code': 'm21'}, {'id': 70, 'game_id': 5, 'code': 'lob'}])
        if path == '/blueprints/export':
            return Reply([
                {'id': 11, 'name': 'Blue-Eyes White Dragon', 'game_id': 5, 'expansion_id': 70,
                 'fixed_properties': {'collector_number': 'LOB-EN001', 'yugioh_rarity': 'Ultra Rare'}},
                {'id': 12, 'name': 'Dark Magician', 'game_id': 5, 'expansion_id': 70,
                 'fixed_properties': {'collector_number': 'LOB-EN005', 'yugioh_rarity': 'Ultra Rare'}},
                {'id': 13, 'name': 'Booster Box', 'game_id': 5, 'expansion_id': 70, 'fixed_properties': {}},
            ])
        if path == '/marketplace/products':
            return Reply(self.products)
        raise AssertionError(path)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(cardtrader.time, 'sleep', lambda s: None)


def _source(tmp_path, http):
    from src.services.prices.store import PriceStore
    return YugiohCardtraderSource(CardTraderClient(TOKEN, http=http), store=PriceStore(str(tmp_path / 'ct.json')))


def test_the_cheapest_near_mint_euro_listing_is_the_price_of_a_printing(tmp_path):
    prices = _source(tmp_path, FakeHttp()).fetch()
    price = prices[blueprint_key('LOB-EN001', 'Ultra Rare')]
    assert price.normal.low == 3.80 and price.normal.trend == 3.80
    assert price.scope == 'printing'


def test_listings_that_are_worse_than_near_mint_or_in_other_currencies_are_ignored(tmp_path):
    prices = _source(tmp_path, FakeHttp()).fetch()
    assert blueprint_key('LOB-EN005', 'Ultra Rare') not in prices  # only a Moderately Played copy


def test_blueprints_without_a_collector_number_are_skipped(tmp_path):
    prices = _source(tmp_path, FakeHttp()).fetch()
    assert set(prices) == {blueprint_key('LOB-EN001', 'Ultra Rare'), 'LOB-EN001'}


def test_the_code_alone_also_finds_the_price_when_the_rarity_is_spelled_differently(tmp_path):
    prices = _source(tmp_path, FakeHttp()).fetch()
    assert prices['LOB-EN001'].normal.low == 3.80


def test_requests_carry_the_token_and_our_user_agent_and_only_the_yugioh_game_is_asked(tmp_path):
    http = FakeHttp()
    _source(tmp_path, http).fetch()
    assert all(c[3]['Authorization'] == f'Bearer {TOKEN}' and c[3]['User-Agent'] == 'OpenYuGi/1.0' for c in http.calls)
    assert any(c[1] == '/expansions' for c in http.calls)
    assert [c[2] for c in http.calls if c[1] == '/blueprints/export'] == [{'expansion_id': 70}]


def test_a_bad_token_or_rate_limit_fails_with_a_clear_message_and_never_shows_the_token(tmp_path):
    for status, text in ((401, 'token'), (429, 'demasiadas')):
        with pytest.raises(CardTraderError) as error:
            _source(tmp_path, FakeHttp(status=status)).fetch()
        assert text in str(error.value).lower() and TOKEN not in str(error.value)


def test_without_a_token_the_source_is_not_built():
    assert cardtrader.build_source(token='') is None
    assert repr(CardTraderClient(TOKEN, http=FakeHttp())) == 'CardTraderClient(…)'


def test_the_daily_download_includes_cardtrader_only_when_a_token_registered_it(tmp_path):
    from datetime import datetime
    from src.services.prices import registry, scheduler
    now = datetime(2026, 11, 14, 6, 0).astimezone()
    source = _source(tmp_path, FakeHttp())
    assert 'cardtrader' not in scheduler.markets_in_use([str(tmp_path)])
    registry.register(source)
    try:
        markets = scheduler.markets_in_use([str(tmp_path)])
        assert 'cardtrader' in markets
        assert source in scheduler.due_sources(now, markets, [source])
    finally:
        registry.SOURCES.pop(('yugioh', 'cardtrader'), None)


def test_the_card_screens_show_cardtrader_and_no_longer_coolstuffinc():
    detail = open('src/ui/components/single_card_view.py', encoding='utf-8').read()
    assert "info_label('CardTrader'" in detail
    for path in ('src/ui/components/single_card_view.py', 'src/ui/collection.py', 'src/ui/browse_sets.py'):
        assert 'coolstuffinc' not in open(path, encoding='utf-8').read().lower().replace('coolstuffinc_price: optional', '')
