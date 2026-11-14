from types import SimpleNamespace as NS

from src.services.bulk_selection import BulkSelection, bulk_target


def _row(card_id=1, variant='v1', lang='EN', cond='Near Mint', first=False, owned=True):
    return NS(api_card=NS(id=card_id), variant_id=variant, language=lang, condition=cond,
              first_edition=first, is_owned=owned)


def _card(card_id=1, owned=True):
    return NS(api_card=NS(id=card_id), is_owned=owned, owned_quantity=2)


def test_a_collector_row_is_targeted_by_all_five_fields_and_a_player_card_by_its_id_only():
    assert bulk_target(_row(3, 'x', 'ES', 'Played', True)) == (3, 'x', 'ES', 'Played', True)
    assert bulk_target(_card(7)) == (7, None, None, None, None)


def test_toggling_selects_and_unselects_and_counts():
    sel = BulkSelection()
    sel.toggle(_row(1))
    sel.toggle(_row(2))
    assert sel.count() == 2 and sel.has(_row(1))
    sel.toggle(_row(1))
    assert sel.count() == 1 and not sel.has(_row(1))


def test_cards_the_user_does_not_own_cannot_be_selected():
    sel = BulkSelection()
    sel.toggle(_row(1, owned=False))
    sel.select_all([_row(2, owned=False), _row(3)])
    assert sel.count() == 1 and sel.has(_row(3))


def test_select_all_adds_the_given_cards_and_keeps_what_was_already_chosen():
    sel = BulkSelection()
    sel.toggle(_row(1))
    sel.select_all([_row(2), _row(3)])
    assert sel.count() == 3


def test_leaving_selection_mode_forgets_the_choice():
    sel = BulkSelection()
    sel.start()
    sel.toggle(_row(1))
    sel.stop()
    assert not sel.active and sel.count() == 0


def test_targets_come_back_in_the_order_they_were_chosen():
    sel = BulkSelection()
    sel.toggle(_row(5))
    sel.toggle(_row(2))
    assert [t[0] for t in sel.targets()] == [5, 2]


def test_the_collection_page_never_calls_a_bare_icon_because_locals_named_icon_shadow_it():
    import re
    source = open('src/ui/collection.py', encoding='utf-8').read()
    assert not re.search(r'(?<![\w.])icon\(', source)
