import json

from src.core.account_profile import AccountProfile, load_profile
from src.core.catalog_models import GameCollection, GameCollectionCard, GameCollectionVariant
from src.core.game_collections import GameCollectionEditor
from src.core.models import Collection, CollectionEntry
from src.core.persistence import PersistenceManager
from src.core.pricing_models import PricingRule
from src.services.collection_editor import CollectionEditor
from src.services.repricing import iter_priced_entries

OLD_YGO = {
    'name': 'Old', 'description': '',
    'cards': [{'card_id': 89631139, 'name': 'Blue-Eyes White Dragon', 'variants': [
        {'variant_id': 'v-lob', 'set_code': 'LOB-EN001', 'rarity': 'Ultra Rare', 'image_id': 89631139,
         'entries': [{'condition': 'Near Mint', 'language': 'EN', 'first_edition': True, 'quantity': 2,
                      'storage_location': 'Box A', 'purchase_price': 5.0, 'market_value': 0.0}]}]}],
    'storage_definitions': [{'name': 'Box A', 'type': 'Box', 'description': 'shelf'}],
}


def test_old_ygo_collection_round_trip(tmp_path):
    (tmp_path / 'old.json').write_text(json.dumps(OLD_YGO), encoding='utf-8')
    manager = PersistenceManager(data_dir=str(tmp_path))
    collection = manager.load_collection('old.json')
    assert collection.for_sale is False and collection.pricing_rule is None
    entry = collection.cards[0].variants[0].entries[0]
    assert entry.list_price is None and entry.price_locked is False
    collection.pricing_rule = PricingRule(percent=90)
    manager.save_collection(collection, 'old.json')
    again = json.loads((tmp_path / 'old.json').read_text(encoding='utf-8'))
    assert again['storage_definitions'] == [{'name': 'Box A', 'type': 'Box', 'description': 'shelf',
                                             'image_path': None, 'set_code': None}]
    assert again['cards'][0]['variants'][0]['entries'][0]['storage_location'] == 'Box A'
    assert again['pricing_rule']['percent'] == 90


def test_old_game_collection_loads():
    old = {'game': 'magic', 'name': 'Old', 'cards': [{'card_id': 'o', 'name': 'Bolt', 'variants': [
        {'printing_id': 'p', 'set_code': 'lea', 'entries': [{'quantity': 1}]}]}]}
    collection = GameCollection(**old)
    assert collection.for_sale is False and collection.pricing_rule is None
    assert collection.cards[0].variants[0].entries[0].list_price is None


def test_profile_default_market(tmp_path):
    assert AccountProfile().price_market == 'cardmarket'
    assert load_profile(str(tmp_path)).price_market == 'cardmarket'


def test_set_list_price_rounds_and_locks():
    entry = CollectionEntry()
    assert CollectionEditor.set_list_price(entry, 1.234) is True
    assert entry.list_price == 1.23 and entry.price_locked is False
    assert CollectionEditor.set_list_price(entry, 1.23) is False
    assert GameCollectionEditor.set_list_price(entry, 1.23, locked=True) is True
    assert entry.price_locked is True
    assert CollectionEditor.set_list_price(entry, None) is True and entry.list_price is None


def test_iter_priced_entries_both_games(tmp_path):
    (tmp_path / 'old.json').write_text(json.dumps(OLD_YGO), encoding='utf-8')
    ygo = PersistenceManager(data_dir=str(tmp_path)).load_collection('old.json')
    refs = list(iter_priced_entries(ygo))
    assert len(refs) == 1
    assert (refs[0].card_id, refs[0].printing_id, refs[0].finish, refs[0].set_code) == \
        ('89631139', 'v-lob', 'nonfoil', 'LOB-EN001')
    assert refs[0].entry is ygo.cards[0].variants[0].entries[0]

    game = GameCollection(game='magic', name='M', cards=[GameCollectionCard(card_id='o', name='Bolt', variants=[
        GameCollectionVariant(printing_id='p1', set_code='m10', finish='foil', entries=[CollectionEntry()])])])
    refs = list(iter_priced_entries(game))
    assert (refs[0].card_id, refs[0].name, refs[0].printing_id, refs[0].finish) == ('o', 'Bolt', 'p1', 'foil')


def test_move_card_keeps_sale_price_and_lock():
    from src.core.models import ApiCard, Collection, CollectionCard, CollectionVariant

    api = ApiCard(id=1, name='BEWD', type='Normal Monster', frameType='normal', desc='')
    entry = CollectionEntry(quantity=3, storage_location='Box A', list_price=12.5, price_locked=True)
    collection = Collection(name='C', cards=[CollectionCard(card_id=1, name='BEWD', variants=[
        CollectionVariant(variant_id='v1', set_code='LOB-EN001', rarity='Ultra Rare', entries=[entry])])])
    assert CollectionEditor.move_card(collection, api, 'LOB-EN001', 'Ultra Rare', 'EN', 'Near Mint', False,
                                      'Box A', 'Binder', quantity=2, variant_id='v1')
    moved = next(e for e in collection.cards[0].variants[0].entries if e.storage_location == 'Binder')
    assert moved.quantity == 2 and moved.list_price == 12.5 and moved.price_locked is True


def test_move_card_into_existing_entry_keeps_target_price():
    from src.core.models import ApiCard, Collection, CollectionCard, CollectionVariant

    api = ApiCard(id=1, name='BEWD', type='Normal Monster', frameType='normal', desc='')
    source = CollectionEntry(quantity=1, storage_location='Box A', list_price=12.5)
    target = CollectionEntry(quantity=1, storage_location='Binder', list_price=9.0)
    collection = Collection(name='C', cards=[CollectionCard(card_id=1, name='BEWD', variants=[
        CollectionVariant(variant_id='v1', set_code='LOB-EN001', rarity='Ultra Rare', entries=[source, target])])])
    CollectionEditor.move_card(collection, api, 'LOB-EN001', 'Ultra Rare', 'EN', 'Near Mint', False,
                               'Box A', 'Binder', quantity=1, variant_id='v1')
    entries = collection.cards[0].variants[0].entries
    assert len(entries) == 1 and entries[0].quantity == 2 and entries[0].list_price == 9.0
