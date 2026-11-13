from pathlib import Path

from src.core.account_profile import AccountProfile
from src.ui.catalog import resolve_game
from src.ui.layout import NAV_ITEMS, nav_items


def test_resolve_game():
    enabled = ['yugioh', 'magic', 'pokemon']
    assert resolve_game('pokemon', enabled) == 'pokemon'
    assert resolve_game('pokemon', ['yugioh', 'magic']) is None
    assert resolve_game('yugioh', enabled) is None
    assert resolve_game(None, enabled) == 'magic'
    assert resolve_game(None, ['yugioh']) is None


def test_nav_items_adds_catalog_only_with_other_games():
    assert nav_items(AccountProfile()) == NAV_ITEMS
    assert nav_items(AccountProfile(enabled_games=['yugioh', 'magic'])) == NAV_ITEMS + [('Catálogo', '/catalog')]


def test_routes_registered():
    source = Path('main.py').read_text(encoding='utf-8')
    for route in ("@ui.page('/catalog')", "@ui.page('/catalog/{game}')", "@ui.page('/games/{game}/collection')"):
        assert route in source


def test_new_collection_name_clash_ignores_case():
    from src.ui.catalog import collection_exists

    assert collection_exists('main.json', ['Main.json', 'otra.json'])
    assert not collection_exists('nueva.json', ['Main.json'])


def test_more_menu_includes_catalog_when_enabled():
    from src.ui.layout import menu_routes

    assert menu_routes({'/catalog': 'Catálogo'}) == ['/', '/catalog', '/import', '/csv', '/db_editor', '/settings']
    assert menu_routes({}) == ['/', '/import', '/csv', '/db_editor', '/settings']
