import json
from datetime import date, datetime
from pathlib import Path

from src.services.reference import novedades, ygoprodeck_sets
from src.services.reference.store import ReferenceStore

FIX = Path(__file__).parent / 'fixtures'


def seeded(tmp_path):
    store = ReferenceStore(tmp_path, 'ygoprodeck_sets', now=lambda: datetime(2026, 11, 14, 8))
    store.upsert_many(ygoprodeck_sets.parse_cardsets(
        json.loads((FIX / 'ygoprodeck_cardsets_sample.json').read_text('utf-8'))))
    return store


def test_empty_store_gives_empty_view(tmp_path):
    view = novedades.build_view(tmp_path, today=date(2026, 11, 14))
    assert view['upcoming'] == [] and view['recent'] == [] and view['last_update'] is None


def test_view_has_days_left_and_spanish_dates(tmp_path):
    seeded(tmp_path)
    view = novedades.build_view(tmp_path, today=date(2026, 11, 14))
    first = view['upcoming'][0]
    assert first['set_code'] == 'GLVI'
    assert first['days_left'] == 19
    assert first['date_label'] == '3 dic 2026'
    assert view['last_update'] == '2026-11-14T08:00:00'
    assert view['recent'] and view['recent'][0]['label']


def test_undated_set_has_no_date_label():
    assert novedades.format_date(None) == 'Sin fecha'
    assert novedades.format_date('2027-03-19') == '19 mar 2027'
