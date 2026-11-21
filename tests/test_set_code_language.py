"""The letters after the dash of a set code say the card's language (yugioh.fandom.com «Código de serie»)."""
import pytest

from src.core.utils import (extract_language_code, is_set_code_compatible, normalize_set_code,
                            transform_set_code)


@pytest.mark.parametrize('code, language', [
    ('PHSW-EN001', 'EN'), ('PHSW-FR001', 'FR'), ('PHSW-DE001', 'DE'), ('PHSW-IT001', 'IT'),
    ('PHSW-SP001', 'ES'), ('PHSW-PT001', 'PT'), ('PHSW-JP001', 'JP'), ('PHSW-KR001', 'KR'),
    ('SR10-SP033', 'ES'), ('SDGU-SP002', 'ES'), ('ORCS-SPSE1', 'ES'),
    # Old one-letter system
    ('SDY-006', 'EN'), ('SDY-E006', 'EN'), ('SDY-A006', 'EN'), ('DDY-F006', 'FR'), ('SDY-G006', 'DE'),
    ('MIY-I006', 'IT'), ('DIY-P006', 'PT'), ('BIY-S009', 'ES'), ('SDY-J006', 'JP'), ('SDY-K006', 'KR'),
])
def test_the_language_is_read_from_the_set_code(code, language):
    assert extract_language_code(code) == language


def test_a_spanish_card_is_the_same_printing_as_its_english_one():
    assert normalize_set_code('SR10-SP033') == normalize_set_code('SR10-EN033') == 'SR10-033'
    assert normalize_set_code('ORCS-SPSE1') == normalize_set_code('ORCS-ENSE1')


def test_spanish_codes_are_written_with_sp_not_es():
    assert transform_set_code('SR10-EN033', 'ES') == 'SR10-SP033'
    assert transform_set_code('SR10-SP033', 'EN') == 'SR10-EN033'
    assert transform_set_code('BIY-S009', 'EN') == 'BIY-E009'
    assert transform_set_code('SDY-E009', 'ES') == 'SDY-S009'


def test_a_spanish_code_only_fits_spanish():
    assert is_set_code_compatible('SR10-SP033', 'ES')
    assert not is_set_code_compatible('SR10-SP033', 'EN')
    assert not is_set_code_compatible('SR10-EN033', 'ES')


def test_the_scanner_accepts_spanish_codes_as_valid():
    from src.services.scanner.pipeline import localized_codes
    codes = localized_codes('SR10-EN033')
    assert 'SR10-SP033' in codes and 'SR10-ES033' not in codes
    assert 'BIY-S009' in localized_codes('BIY-E009')
