import json
from pathlib import Path

import pytest

from src.core.config import SUPPORTED_LANGUAGES, ConfigManager


def _manager_with_language(tmp_path, language):
    config_file = tmp_path / 'config.json'
    config_file.write_text(json.dumps({'language': language}), encoding='utf-8')
    return ConfigManager(str(config_file))


@pytest.mark.parametrize('language', ['es', 'ja', '', None, 42])
def test_unsupported_language_falls_back_to_english(tmp_path, language):
    # YGOPRODeck answers 400 for these, and a new account then lands on an error.
    assert _manager_with_language(tmp_path, language).get_language() == 'en'


@pytest.mark.parametrize('language', ['en', 'de', 'fr', 'it', 'pt', 'FR'])
def test_supported_language_is_kept(tmp_path, language):
    assert _manager_with_language(tmp_path, language).get_language() == language


def test_settings_offer_exactly_the_supported_languages():
    assert SUPPORTED_LANGUAGES == ('en', 'de', 'fr', 'it', 'pt')


def test_favicon_points_at_a_file_that_exists():
    # NiceGUI reads ui.run(favicon=...) as a file path. '/brand/mark.svg' is the
    # URL, not the file, and made /favicon.ico answer 500.
    source = Path('main.py').read_text(encoding='utf-8')
    assert "favicon='static/brand/mark.svg'" in source
    assert Path('static/brand/mark.svg').is_file()
