from src.core.models import CollectionEntry
from src.services.repricing import EntryRef, RepriceRow
from src.ui.components.pricing_bar import format_money, price_status_text, row_to_table_dict


def test_format_money():
    assert format_money(12.5, 'cardmarket') == '12,50 €'
    assert format_money(1234.5, 'cardmarket') == '1.234,50 €'
    assert format_money(12.5, 'tcgplayer') == '$12.50'
    assert format_money(1234.5, 'tcgplayer') == '$1,234.50'
    assert format_money(None, 'cardmarket') == '—'


def test_price_status_text():
    assert price_status_text({'count': 0, 'updated_at': None}) == 'Sin descargar'
    assert price_status_text({'count': 12345, 'updated_at': '2026-11-11T04:00:00+00:00'}) == \
        '12.345 precios · actualizado 11/11/2026'


def test_row_to_table_dict():
    ref = EntryRef(card_id='1', name='Bolt', printing_id='p', set_code='m10', rarity='common', finish='foil',
                   entry=CollectionEntry(condition='Excellent', quantity=3, list_price=1.0))
    row = RepriceRow(ref, market=2.0, current=1.0, new=1.8, delta=0.8, status='cambia')
    data = row_to_table_dict(7, row, 'cardmarket', reference=2.4, scope='card')
    assert data == {'id': 7, 'name': 'Bolt', 'set': 'm10', 'finish': 'foil', 'condition': 'Excellent',
                    'quantity': 3, 'market': '2,00 €', 'current': '1,00 €', 'new': '1,80 €',
                    'delta': '+0,80 €', 'status': 'cambia', 'reference': '$2.40', 'locked': False,
                    'note': 'precio por carta'}
    row.delta = -0.5
    assert row_to_table_dict(7, row, 'tcgplayer', None, 'printing')['delta'] == '-$0.50'
