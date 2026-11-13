import json
import os
from datetime import datetime, timedelta, timezone

from src.core.account_profile import AccountProfile, save_profile
from src.core.catalog_models import GameCollection, GameCollectionCard, GameCollectionVariant
from src.core.game_collections import GameCollectionStore
from src.core.models import CollectionEntry
from src.core.pricing_models import PriceQuote, PricingRule, PrintingPrice
from src.services.prices import scheduler

NOW = datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc)


class FakeSource:
    def __init__(self, game, market, age_hours=None, fail=False, prices=None):
        self.game, self.market, self.fail = game, market, fail
        self.updated = None if age_hours is None else (NOW - timedelta(hours=age_hours)).isoformat()
        self.prices = prices or {}
        self.refreshed = 0
        self.store = self

    def info(self):
        return {'count': 1 if self.updated else 0, 'updated_at': self.updated}

    def refresh(self):
        self.refreshed += 1
        if self.fail:
            raise RuntimeError('down')
        return 1

    def get(self, printing_id):
        return self.prices.get(printing_id)


def test_account_roots(tmp_path):
    (tmp_path / 'users' / 'ana').mkdir(parents=True)
    (tmp_path / 'users' / 'bob').mkdir()
    (tmp_path / 'users' / 'file.txt').write_text('x')
    roots = scheduler.account_roots(str(tmp_path))
    assert roots == [str(tmp_path), os.path.join(str(tmp_path), 'users', 'ana'),
                     os.path.join(str(tmp_path), 'users', 'bob')]


def test_due_sources_waits_until_five_and_skips_fresh_and_unused_markets():
    old_cm = FakeSource('magic', 'cardmarket', age_hours=21)
    fresh_cm = FakeSource('pokemon', 'cardmarket', age_hours=2)
    never = FakeSource('yugioh', 'cardmarket')
    tcg = FakeSource('magic', 'tcgplayer', age_hours=30)
    all_sources = [old_cm, fresh_cm, never, tcg]
    assert scheduler.due_sources(NOW.replace(hour=4), {'cardmarket'}, all_sources) == []
    assert scheduler.due_sources(NOW, {'cardmarket'}, all_sources) == [old_cm, never]
    assert scheduler.due_sources(NOW, {'cardmarket', 'tcgplayer'}, all_sources) == [old_cm, never, tcg]


def _magic_collection(auto_apply=True, for_sale=True):
    return GameCollection(game='magic', name='Venta', for_sale=for_sale,
                          pricing_rule=PricingRule(auto_apply=auto_apply), cards=[
        GameCollectionCard(card_id='o', name='Bolt', variants=[
            GameCollectionVariant(printing_id='p1', set_code='m10', entries=[CollectionEntry(quantity=1)])])])


def _price(value):
    return {'p1': PrintingPrice(normal=PriceQuote(trend=value))}


def test_auto_reprice_uses_each_accounts_root_and_market(tmp_path):
    root_a, root_b = str(tmp_path / 'a'), str(tmp_path / 'b')
    save_profile(AccountProfile(enabled_games=['yugioh', 'magic']), root_a)
    save_profile(AccountProfile(enabled_games=['yugioh', 'magic'], price_market='tcgplayer'), root_b)
    store_a, store_b = GameCollectionStore(lambda: root_a), GameCollectionStore(lambda: root_b)
    store_a.save('magic', _magic_collection(), 'venta.json')
    store_a.save('magic', _magic_collection(auto_apply=False), 'manual.json')
    store_b.save('magic', _magic_collection(), 'venta.json')
    os.makedirs(os.path.join(root_b, 'games', 'magic', 'collections'), exist_ok=True)
    with open(os.path.join(root_b, 'games', 'magic', 'collections', 'broken.json'), 'w') as f:
        f.write('{broken')

    lookup = {('magic', 'cardmarket'): FakeSource('magic', 'cardmarket', prices=_price(2.0)),
              ('magic', 'tcgplayer'): FakeSource('magic', 'tcgplayer', prices=_price(3.0))}
    get = lambda game, market: lookup[(game, market)]

    assert scheduler.auto_reprice(root_a, get_source=get) == 1
    assert scheduler.auto_reprice(root_b, get_source=get) == 1

    def price(store, name):
        return store.load('magic', name).cards[0].variants[0].entries[0].list_price
    assert price(store_a, 'venta.json') == 2.0
    assert price(store_a, 'manual.json') is None
    assert price(store_b, 'venta.json') == 3.0


def test_auto_reprice_yugioh_collections(tmp_path):
    root = str(tmp_path / 'r')
    os.makedirs(os.path.join(root, 'collections'))
    data = {'name': 'Y', 'for_sale': True, 'pricing_rule': {'auto_apply': True}, 'cards': [
        {'card_id': 1, 'name': 'BEWD', 'variants': [
            {'variant_id': 'v1', 'set_code': 'LOB', 'rarity': 'UR', 'entries': [{'quantity': 1}]}]}]}
    with open(os.path.join(root, 'collections', 'y.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f)
    source = FakeSource('yugioh', 'cardmarket', prices={'v1': PrintingPrice(normal=PriceQuote(trend=4.0))})
    assert scheduler.auto_reprice(root, get_source=lambda g, m: source) == 1
    with open(os.path.join(root, 'collections', 'y.json'), encoding='utf-8') as f:
        assert json.load(f)['cards'][0]['variants'][0]['entries'][0]['list_price'] == 4.0


def test_run_daily_keeps_going_when_a_source_fails(tmp_path):
    ok = FakeSource('magic', 'cardmarket', age_hours=30)
    bad = FakeSource('pokemon', 'cardmarket', age_hours=30, fail=True)
    summary = scheduler.run_daily(NOW, base=str(tmp_path), all_sources=[bad, ok], get_source=lambda g, m: ok)
    assert ok.refreshed == 1 and bad.refreshed == 1
    assert summary['refreshed'] == ['magic-cardmarket']
    assert 'pokemon-cardmarket' in summary['errors']


def test_run_daily_skips_reprice_when_nothing_was_refreshed(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(scheduler, 'auto_reprice', lambda root, get_source=None: called.append(root) or 0)
    scheduler.run_daily(NOW.replace(hour=3), base=str(tmp_path), all_sources=[])
    assert called == []
