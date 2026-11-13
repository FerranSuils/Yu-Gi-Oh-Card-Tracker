from pathlib import Path

import pytest

from src.core.account_profile import AccountProfile
from src.core.sales_models import SaleLine
from src.services.sales import decklist
from src.services.sales.decklist import Wanted
from src.services.shop.kiosk import KioskOrders


def _pile(name, cents, quantity=1, **more):
    values = dict(name=name, card_id=name.lower(), variant_id=f'{name}-{cents}', collection='main.json',
                  unit_cents=cents, quantity=quantity)
    values.update(more)
    return SaleLine(**values)


# --- reading the list ------------------------------------------------------------------------

def test_a_line_is_a_number_and_a_name_or_just_a_name():
    text = '3 Dark Hole\n3x Raigeki\n2X  Pot of Greed \nMonster Reborn\n'
    assert decklist.parse(text) == [Wanted(name='Dark Hole', quantity=3), Wanted(name='Raigeki', quantity=3),
                                    Wanted(name='Pot of Greed', quantity=2), Wanted(name='Monster Reborn', quantity=1)]


def test_blank_lines_comments_and_section_titles_are_left_out():
    text = '\n// main\n# side\n   \nMain Deck:\n1 Dark Hole\r\n  // 3 Raigeki\n'
    assert decklist.parse(text) == [Wanted(name='Dark Hole', quantity=1)]


def test_the_same_card_twice_adds_up_whatever_its_capitals():
    assert decklist.parse('2 Dark Hole\n1 dark  hole') == [Wanted(name='Dark Hole', quantity=3)]


def test_a_name_that_starts_with_a_number_glued_to_it_is_a_name():
    assert decklist.parse('3-Hump Lacooda\n2 7 Colored Fish') == [
        Wanted(name='3-Hump Lacooda', quantity=1), Wanted(name='7 Colored Fish', quantity=2)]


@pytest.mark.parametrize('text', ['0 Dark Hole', '3', '3x', 'x', ''])
def test_lines_that_ask_for_nothing_are_left_out(text):
    assert decklist.parse(text) == []


def test_absurd_lists_are_cut_to_size():
    assert decklist.parse('99999999999999999999 Dark Hole') == [Wanted(name='Dark Hole', quantity=decklist.MAX_COPIES)]
    assert len(decklist.parse('\n'.join(f'1 Card {n}' for n in range(1000)))) == decklist.MAX_CARDS
    assert len(decklist.parse('1 ' + 'a' * 5000)[0].name) <= decklist.MAX_NAME
    assert decklist.parse(None) == []


# --- against the stock -----------------------------------------------------------------------

def test_the_cheapest_copies_are_taken_first():
    items = [_pile('Dark Hole', 500, 2), _pile('Dark Hole', 150, 1), _pile('Raigeki', 900, 5)]
    found, = decklist.match([Wanted(name='dark hole', quantity=2)], items)
    assert (found.name, found.wanted, found.in_stock, found.missing) == ('dark hole', 2, 3, 0)
    assert [(line.unit_cents, line.quantity) for line in found.lines] == [(150, 1), (500, 1)]
    assert found.cents == 650


def test_what_is_not_there_is_counted_as_missing():
    items = [_pile('Dark Hole', 150, 1)]
    some, none = decklist.match([Wanted(name='Dark Hole', quantity=3), Wanted(name='Raigeki', quantity=2)], items)
    assert (some.in_stock, some.missing, some.cents) == (1, 2, 150)
    assert (none.in_stock, none.missing, none.lines, none.cents) == (0, 2, [], 0)


def test_stock_without_price_or_that_is_not_a_card_does_not_count():
    items = [_pile('Dark Hole', 0, 4), SaleLine(kind='custom', name='Dark Hole', unit_cents=300)]
    found, = decklist.match([Wanted(name='Dark Hole', quantity=1)], items)
    assert (found.in_stock, found.missing) == (0, 1)


def test_any_game_counts_and_where_it_is_kept_does_not_matter():
    items = [_pile('Lightning Bolt', 200, 1, game='magic', storage_location='Caja 1'),
             _pile('Lightning Bolt', 200, 2, game='magic', storage_location='Caja 2')]
    found, = decklist.match([Wanted(name='Lightning Bolt', quantity=3)], items)
    assert found.missing == 0 and sum(line.quantity for line in found.lines) == 3
    assert all(line.storage_location is None and line.game == 'magic' for line in found.lines)


def test_two_lines_never_take_the_same_copy():
    items = [_pile('Dark Hole', 150, 1)]
    first, second = decklist.match([Wanted(name='Dark Hole', quantity=1), Wanted(name='DARK HOLE', quantity=1)], items)
    assert (first.missing, second.missing) == (0, 1)


def test_matching_does_not_touch_the_stock_it_was_given():
    items = [_pile('Dark Hole', 150, 3)]
    decklist.match([Wanted(name='Dark Hole', quantity=2)], items)
    assert items[0].quantity == 3


def test_an_apostrophe_is_an_apostrophe():
    items = [_pile("Solemn Judgment's Echo", 100, 1)]
    found, = decklist.match([Wanted(name='Solemn Judgment’s Echo', quantity=1)], items)
    assert found.missing == 0


# --- to the counter --------------------------------------------------------------------------

def test_what_is_available_becomes_a_list_the_counter_can_load(tmp_path):
    items = [_pile('Dark Hole', 500, 2), _pile('Dark Hole', 150, 1), _pile('Raigeki', 900, 5)]
    found = decklist.match(decklist.parse('3 Dark Hole\n1 Raigeki\n2 Pot of Greed'), items)
    lines = decklist.available_lines(found)
    assert [(line.name, line.quantity, line.unit_cents) for line in lines] == [
        ('Dark Hole', 1, 150), ('Dark Hole', 2, 500), ('Raigeki', 1, 900)]
    assert decklist.total_cents(found) == 150 + 1000 + 900
    order = KioskOrders(str(tmp_path)).add('Mazo de Ana', lines)
    assert sum(line.quantity for line in order.lines) == 4


def test_nothing_available_is_an_empty_list():
    assert decklist.available_lines(decklist.match([Wanted(name='Raigeki', quantity=1)], [])) == []


# --- the page --------------------------------------------------------------------------------

def test_the_deck_list_shows_in_shop_mode_only_and_is_private():
    from src.services.auth_middleware import is_public_path
    from src.ui.layout import SHOP_ROUTES, nav_items

    assert '/lista' not in dict((route, label) for label, route in nav_items(AccountProfile()))
    shop_nav = dict((route, label) for label, route in nav_items(AccountProfile(shop_mode=True)))
    assert shop_nav['/lista'] == 'Lista de mazo'
    assert '/lista' in SHOP_ROUTES
    assert not is_public_path('/lista')
    assert "@ui.page('/lista')" in Path('main.py').read_text(encoding='utf-8')


def test_the_page_uses_self_hosted_icons_and_says_what_is_missing():
    from src.ui.decklist import ICONS, missing_text

    assert ICONS
    for name in ICONS:
        assert Path('static/icons', f'{name}.svg').is_file(), name
    assert missing_text(0) == ''
    assert missing_text(1) == 'Falta 1'
    assert missing_text(3) == 'Faltan 3'
