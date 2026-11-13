import os
import threading

from src.core import collection_sync
from src.core.collection_sync import bump, path_lock, revision


def test_same_file_shares_one_reentrant_lock(tmp_path):
    a = str(tmp_path / 'c.json')
    b = os.path.join(str(tmp_path), '.', 'c.json')
    assert path_lock(a) is path_lock(b)
    with path_lock(a):
        with path_lock(b):  # re-entrant: the scheduler saves while holding it
            pass


def test_lock_blocks_another_thread(tmp_path):
    path = str(tmp_path / 'c.json')
    order = []
    with path_lock(path):
        worker = threading.Thread(target=lambda: (path_lock(path).acquire(), order.append('worker'),
                                                  path_lock(path).release()))
        worker.start()
        worker.join(0.2)
        order.append('holder')
    worker.join(2)
    assert order == ['holder', 'worker']


def test_revision_counts_external_writes(tmp_path):
    path = str(tmp_path / 'c.json')
    assert revision(path) == 0
    bump(path)
    bump(os.path.join(str(tmp_path), 'c.json'))
    assert revision(path) == 2


def test_scheduler_bumps_revision_of_repriced_collections(tmp_path):
    from src.core.account_profile import AccountProfile, save_profile
    from src.core.catalog_models import GameCollection, GameCollectionCard, GameCollectionVariant
    from src.core.game_collections import GameCollectionStore
    from src.core.models import CollectionEntry
    from src.core.pricing_models import PriceQuote, PricingRule, PrintingPrice
    from src.services.prices import scheduler

    root = str(tmp_path / 'a')
    save_profile(AccountProfile(), root)
    store = GameCollectionStore(lambda: root)
    store.save('magic', GameCollection(game='magic', name='V', for_sale=True, pricing_rule=PricingRule(
        auto_apply=True), cards=[GameCollectionCard(card_id='o', name='Bolt', variants=[GameCollectionVariant(
            printing_id='p1', set_code='m10', entries=[CollectionEntry()])])]), 'v.json')
    path = store.path('magic', 'v.json')
    before = revision(path)
    prices = {'p1': PrintingPrice(normal=PriceQuote(trend=2.0))}
    source = type('S', (), {'get': staticmethod(prices.get)})()
    assert scheduler.auto_reprice(root, get_source=lambda g, m: source) == 1
    assert revision(path) == before + 1


def test_revision_watcher_reports_external_writes_once(tmp_path):
    from src.core.collection_sync import RevisionWatcher

    current = {'path': str(tmp_path / 'a.json')}
    watcher = RevisionWatcher(lambda: current['path'])
    assert watcher.changed() is False          # first look only records the revision
    bump(current['path'])
    assert watcher.changed() is True
    assert watcher.changed() is False
    current['path'] = str(tmp_path / 'b.json')  # switching collection is not a change
    bump(current['path'])
    assert watcher.changed() is False
    current['path'] = None
    assert watcher.changed() is False
