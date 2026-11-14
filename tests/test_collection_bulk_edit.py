import pytest

from src.core.models import Collection, CollectionCard, CollectionEntry, CollectionVariant
from src.services.collection_editor import CollectionEditor


def _entry(qty=1, lang='EN', cond='Near Mint', first=False, place=None, price=None):
    return CollectionEntry(quantity=qty, language=lang, condition=cond, first_edition=first,
                           storage_location=place, list_price=price)


def _collection():
    return Collection(name='main', cards=[
        CollectionCard(card_id=1, name='Alpha', variants=[
            CollectionVariant(variant_id='a1', set_code='LOB-EN001', rarity='Ultra Rare',
                              entries=[_entry(2, place='Box A'), _entry(1, cond='Played')]),
            CollectionVariant(variant_id='a2', set_code='SDK-001', rarity='Common', entries=[_entry(3)]),
        ]),
        CollectionCard(card_id=2, name='Beta', variants=[
            CollectionVariant(variant_id='b1', set_code='LOB-EN002', rarity='Rare', entries=[_entry(4, place='Box A')]),
        ]),
    ])


def _total(collection):
    return sum(e.quantity for c in collection.cards for v in c.variants for e in v.entries)


def test_a_whole_card_target_covers_every_copy_of_it():
    entries = CollectionEditor.select_entries(_collection(), [(1, None, None, None, None)])
    assert sum(e.quantity for _, _, e in entries) == 6


def test_a_row_target_only_covers_its_variant_language_condition_and_edition():
    entries = CollectionEditor.select_entries(_collection(), [(1, 'a1', 'EN', 'Near Mint', False)])
    assert [e.quantity for _, _, e in entries] == [2]


def test_removing_the_selection_leaves_the_rest_and_cleans_up_empty_cards():
    col = _collection()
    removed = CollectionEditor.bulk_remove(col, [(2, None, None, None, None), (1, 'a2', 'EN', 'Near Mint', False)])
    assert removed == 7
    assert [c.card_id for c in col.cards] == [1]
    assert [v.variant_id for v in col.cards[0].variants] == ['a1']


def test_assigning_a_storage_moves_every_selected_copy_and_merges_with_what_is_already_there():
    col = _collection()
    moved = CollectionEditor.bulk_assign_storage(col, [(1, 'a1', 'EN', 'Near Mint', False)], 'Box B')
    assert moved == 2
    CollectionEditor.bulk_assign_storage(col, [(2, None, None, None, None)], 'Box B')
    CollectionEditor.bulk_assign_storage(col, [(1, 'a1', 'EN', 'Near Mint', False)], 'Box A')
    entries = col.cards[0].variants[0].entries
    assert sorted((e.storage_location, e.quantity) for e in entries if e.condition == 'Near Mint') == [('Box A', 2)]
    assert _total(col) == 10


def test_assigning_no_storage_clears_the_place():
    col = _collection()
    CollectionEditor.bulk_assign_storage(col, [(2, None, None, None, None)], None)
    assert col.cards[1].variants[0].entries[0].storage_location is None


def test_a_merged_entry_keeps_the_sale_price_of_the_one_it_joins():
    col = _collection()
    col.cards[1].variants[0].entries.append(_entry(1, place='Box B', price=9.5))
    CollectionEditor.bulk_assign_storage(col, [(2, 'b1', 'EN', 'Near Mint', False)], 'Box B')
    entries = col.cards[1].variants[0].entries
    assert len(entries) == 1 and entries[0].quantity == 5 and entries[0].list_price == 9.5


def test_setting_a_quantity_changes_exactly_that_entry_and_zero_removes_it():
    col = _collection()
    CollectionEditor.set_entry_quantity(col, 1, 'a1', 'EN', 'Near Mint', False, 'Box A', 7)
    assert col.cards[0].variants[0].entries[0].quantity == 7
    CollectionEditor.set_entry_quantity(col, 1, 'a1', 'EN', 'Near Mint', False, 'Box A', 0)
    assert [e.condition for e in col.cards[0].variants[0].entries] == ['Played']


def test_transfer_moves_the_selection_to_the_other_collection_and_adds_to_what_it_has():
    source, target = _collection(), Collection(name='other', cards=[
        CollectionCard(card_id=2, name='Beta', variants=[
            CollectionVariant(variant_id='b1', set_code='LOB-EN002', rarity='Rare', entries=[_entry(1, place='Box A')])])])
    moved = CollectionEditor.transfer(source, target, [(2, None, None, None, None), (1, 'a2', 'EN', 'Near Mint', False)])
    assert moved == 7
    assert [c.card_id for c in source.cards] == [1]
    assert _total(target) == 8
    beta = next(c for c in target.cards if c.card_id == 2)
    assert beta.variants[0].entries[0].quantity == 5
    alpha = next(c for c in target.cards if c.card_id == 1)
    assert alpha.variants[0].set_code == 'SDK-001'


def test_transfer_to_the_same_collection_does_nothing():
    col = _collection()
    assert CollectionEditor.transfer(col, col, [(1, None, None, None, None)]) == 0
    assert _total(col) == 10


def test_changing_condition_language_and_edition_changes_every_selected_stack():
    col = _collection()
    changed = CollectionEditor.bulk_set_attributes(col, [(1, 'a1', None, None, None)], condition='Played',
                                                   language='ES', first_edition=True)
    assert changed == 3
    entries = col.cards[0].variants[0].entries
    assert sorted((e.condition, e.language, e.first_edition, e.quantity) for e in entries) == [
        ('Played', 'ES', True, 1), ('Played', 'ES', True, 2)]


def test_stacks_that_become_equal_in_the_same_place_are_merged():
    col = _collection()
    col.cards[1].variants[0].entries.append(_entry(1, cond='Played', place='Box A'))
    CollectionEditor.bulk_set_attributes(col, [(2, 'b1', None, None, None)], condition='Played')
    entries = col.cards[1].variants[0].entries
    assert len(entries) == 1 and entries[0].quantity == 5


def test_fields_left_as_none_are_not_touched():
    col = _collection()
    CollectionEditor.bulk_set_attributes(col, [(2, None, None, None, None)], condition='Played')
    entry = col.cards[1].variants[0].entries[0]
    assert (entry.condition, entry.language, entry.first_edition, entry.storage_location) == ('Played', 'EN', False, 'Box A')


def test_changing_the_rarity_moves_the_copies_to_the_variant_of_that_rarity_and_creates_it():
    col = _collection()
    lookup = lambda card_id, set_code, rarity: ('v-new', None) if rarity == 'Secret Rare' else None
    moved, skipped = CollectionEditor.bulk_set_rarity(col, [(2, None, None, None, None)], 'Secret Rare', lookup)
    assert (moved, skipped) == (4, 0)
    variants = {v.variant_id: v for v in col.cards[1].variants}
    assert set(variants) == {'v-new'} and variants['v-new'].rarity == 'Secret Rare'
    assert variants['v-new'].set_code == 'LOB-EN002' and variants['v-new'].entries[0].quantity == 4


def test_cards_that_have_no_such_rarity_in_their_set_are_skipped_and_counted():
    col = _collection()
    moved, skipped = CollectionEditor.bulk_set_rarity(col, [(1, None, None, None, None)], 'Starlight Rare',
                                                      lambda *a: None)
    assert (moved, skipped) == (0, 6)
    assert [v.variant_id for v in col.cards[0].variants] == ['a1', 'a2']


def test_a_rarity_change_merges_into_a_variant_that_already_exists():
    col = _collection()
    col.cards[1].variants.append(CollectionVariant(variant_id='b2', set_code='LOB-EN002', rarity='Secret Rare',
                                                   entries=[_entry(1, place='Box A')]))
    CollectionEditor.bulk_set_rarity(col, [(2, 'b1', None, None, None)], 'Secret Rare', lambda *a: ('b2', None))
    assert [v.variant_id for v in col.cards[1].variants] == ['b2']
    assert col.cards[1].variants[0].entries[0].quantity == 5
