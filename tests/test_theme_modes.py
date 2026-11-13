import re

from src.ui import theme


def test_light_tokens_are_unchanged():
    # Dark mode must not touch the light desk.
    for token in ('--oy-bg: #f3ede2;', '--oy-surface: #fbf7f0;', '--oy-text: #1e1a15;', '--oy-accent: #9c2f24;'):
        assert token in theme.GLOBAL_CSS
    assert 'data-oy-theme' not in theme.GLOBAL_CSS


def test_dark_tokens_apply_when_chosen_and_when_the_system_asks():
    head = theme.THEME_HEAD
    assert 'html[data-oy-theme="dark"] {' in head
    media = head[head.index('@media (prefers-color-scheme: dark)'):]
    assert 'html[data-oy-theme="auto"] {' in media
    assert '--oy-bg: #16130f;' in head
    # ui.colors() sets Quasar's palette inline on <body>; dark needs !important.
    assert '--q-primary: #f1ebe0 !important;' in head


def test_light_choice_has_no_dark_rules():
    assert 'html[data-oy-theme="light"] {' not in theme.THEME_HEAD


def test_switch_offers_system_light_and_dark():
    html = theme.THEME_SWITCH_HTML
    assert re.findall(r'data-mode="(\w+)"', html) == ['auto', 'light', 'dark']
    for label in ('Sistema', 'Claro', 'Oscuro'):
        assert f'aria-label="{label}"' in html
    assert html.count("window.oySetTheme(") == 3


def test_stored_choice_defaults_to_system():
    script = theme.THEME_HEAD
    assert f"var KEY = '{theme.THEME_STORAGE_KEY}';" in script
    assert "return MODES.indexOf(value) >= 0 ? value : 'auto';" in script
