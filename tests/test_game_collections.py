import pytest

from src.core.catalog_models import CatalogCard, CatalogPrinting, GameCollection
from src.core.game_collections import GameCollectionEditor, GameCollectionStore
from src.core.persistence import PersistenceManager

PRINTING = CatalogPrinting(printing_id='p-lea', set_code='lea', set_name='Alpha', number='161', rarity='common')
CARD = CatalogCard(game='magic', card_id='o-bolt', name='Lightning Bolt', printings=[PRINTING])


def _collection():
    return GameCollection(game='magic', name='Mis cartas')


def test_add_merges_into_matching_entry():
    col = _collection()
    GameCollectionEditor.apply_change(col, CARD, PRINTING, 'nonfoil', 2)
    GameCollectionEditor.apply_change(col, CARD, PRINTING, 'nonfoil', 3)
    GameCollectionEditor.apply_change(col, CARD, PRINTING, 'nonfoil', 1, condition='Played')
    GameCollectionEditor.apply_change(col, CARD, PRINTING, 'foil', 1)
    [card] = col.cards
    nonfoil, foil = card.variants
    assert [(e.condition, e.quantity) for e in nonfoil.entries] == [('Near Mint', 5), ('Played', 1)]
    assert foil.finish == 'foil' and foil.total_quantity == 1
    assert col.total_cards == 7


def test_removing_more_than_owned_deletes_variant_and_card():
    col = _collection()
    GameCollectionEditor.apply_change(col, CARD, PRINTING, 'nonfoil', 2)
    GameCollectionEditor.apply_change(col, CARD, PRINTING, 'nonfoil', -5)
    assert col.cards == [] and col.total_cards == 0
    GameCollectionEditor.apply_change(col, CARD, PRINTING, 'nonfoil', -1)
    assert col.cards == []


def test_store_round_trip_and_list(tmp_path):
    store = GameCollectionStore(lambda: str(tmp_path))
    col = _collection()
    GameCollectionEditor.apply_change(col, CARD, PRINTING, 'nonfoil', 2)
    store.save('magic', col, 'mis-cartas.json')
    assert store.list('magic') == ['mis-cartas.json']
    assert store.load('magic', 'mis-cartas.json') == col
    assert (tmp_path / 'games' / 'magic' / 'collections' / 'mis-cartas.json').is_file()
    store.delete('magic', 'mis-cartas.json')
    assert store.list('magic') == []


def test_store_rejects_path_traversal_and_yugioh(tmp_path):
    store = GameCollectionStore(lambda: str(tmp_path))
    with pytest.raises(ValueError):
        store.save('magic', _collection(), '../x.json')
    with pytest.raises(ValueError):
        store.list('yugioh')
    with pytest.raises(ValueError):
        store.list('../magic')


def test_store_isolates_accounts(tmp_path):
    alice = GameCollectionStore(lambda: str(tmp_path / 'a'))
    bob = GameCollectionStore(lambda: str(tmp_path / 'b'))
    alice.save('magic', _collection(), 'mis-cartas.json')
    assert bob.list('magic') == []
    with pytest.raises(FileNotFoundError):
        bob.load('magic', 'mis-cartas.json')


def test_persistence_does_not_list_game_collections(tmp_path):
    collections = tmp_path / 'collections'
    store = GameCollectionStore(lambda: str(collections))
    store.save('magic', _collection(), 'mis-cartas.json')
    manager = PersistenceManager(data_dir=str(collections), decks_dir=str(tmp_path / 'decks'))
    assert manager.list_collections() == []


def test_bound_store_keeps_account_root_in_worker_threads(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import src.core.game_collections as module

    main = threading.current_thread()
    # The session (and so the account) is only visible on the UI thread, as with run.io_bound.
    monkeypatch.setattr(module, 'account_root',
                        lambda: str(tmp_path / 'acct') if threading.current_thread() is main else str(tmp_path / 'data'))
    store = module.GameCollectionStore(lambda: module.account_root()).bound()
    with ThreadPoolExecutor(1) as pool:
        pool.submit(store.save, 'magic', _collection(), 'mis-cartas.json').result()
    assert (tmp_path / 'acct' / 'games' / 'magic' / 'collections' / 'mis-cartas.json').is_file()
    assert not (tmp_path / 'data').exists()
