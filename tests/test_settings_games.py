from pathlib import Path

from src.ui.icons import icon_svg
from src.ui.settings_games import catalog_status_text, valid_email


def test_catalog_status_text():
    assert catalog_status_text({'count': 0, 'updated_at': None}) == 'Sin descargar'
    text = catalog_status_text({'count': 12345, 'updated_at': '2026-11-11T10:00:00+00:00'})
    assert '12.345 cartas' in text and '11/11/2026' in text


def test_valid_email():
    assert valid_email('tienda@example.com') and valid_email('')
    assert not valid_email('tienda@example') and not valid_email('nope')


def test_settings_page_calls_new_sections():
    source = Path('src/ui/settings.py').read_text(encoding='utf-8')
    assert 'render_games_section()' in source and 'render_shop_section()' in source
    assert source.index('render_shop_section()') < source.index("'Data management'")


def test_icons_are_inline_iconkit_svgs():
    svg = icon_svg('store')
    assert svg.startswith('<svg') and 'currentColor' in svg and 'oy-ik' in svg


def test_ui_resolves_account_before_worker_threads():
    # account_root() reads the session, which run.io_bound threads cannot see.
    for path in ('src/ui/settings_games.py', 'src/ui/catalog.py', 'src/ui/game_collection.py'):
        source = Path(path).read_text(encoding='utf-8')
        assert 'run.io_bound(save_profile, current)' not in source
        assert 'run.io_bound(game_collection_store.' not in source, path


def test_only_the_primary_account_manages_shared_catalogs(monkeypatch):
    import src.ui.settings_games as module

    monkeypatch.setattr(module, 'current_account_name', lambda: 'kkdbb')
    monkeypatch.setattr(module, 'uses_private_storage', lambda name: name == 'kkdbb')
    assert module.can_manage_catalogs() is False
    monkeypatch.setattr(module, 'current_account_name', lambda: 'admin')
    assert module.can_manage_catalogs() is True
