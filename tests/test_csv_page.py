from pathlib import Path

import pytest

from src.core.catalog_models import CatalogCard, CatalogPrinting
from src.core.models import CollectionEntry
from src.services.csv_suite import EntryRow, ImportRow, MatchedRow


def test_route_and_menu():
    from src.ui.layout import NAV_ITEMS, menu_routes

    assert "@ui.page('/csv')" in Path('main.py').read_text(encoding='utf-8')
    assert ('CSV', '/csv') in NAV_ITEMS
    assert menu_routes({}) == ['/', '/import', '/csv', '/db_editor', '/settings']
    assert menu_routes({'/catalog': 'Catálogo'}) == ['/', '/catalog', '/import', '/csv', '/db_editor', '/settings']


def test_icons_are_self_hosted():
    for name in ('upload', 'arrow-merge', 'edit', 'table-grid'):
        assert Path('static/icons', f'{name}.svg').is_file()


def test_export_filename():
    from src.ui.csv_suite import export_filename

    assert export_filename('Mi colección') == 'Mi colección-cardmarket.csv'
    assert export_filename('a/b\\c:d*?"<>|') == 'a_b_c_d______-cardmarket.csv'
    assert export_filename('  ') == 'coleccion-cardmarket.csv'


def test_match_summary_counts_rows_and_cards():
    from src.ui.csv_suite import match_summary

    matched = [MatchedRow(ImportRow(line=2, quantity=3), 'ok'), MatchedRow(ImportRow(line=3, quantity=2), 'ok'),
               MatchedRow(ImportRow(line=4), 'sin casar', 'No está en el catálogo'),
               MatchedRow(ImportRow(line=5), 'ambigua', '2 impresiones'),
               MatchedRow(ImportRow(line=6), 'error', 'Cantidad no válida')]
    assert match_summary(matched) == {'ok': 2, 'sin casar': 1, 'ambigua': 1, 'error': 1, 'cards': 5}
    assert match_summary([]) == {'ok': 0, 'sin casar': 0, 'ambigua': 0, 'error': 0, 'cards': 0}


def test_matched_to_table():
    from src.ui.csv_suite import matched_to_table

    card = CatalogCard(game='magic', card_id='o', name='Lightning Bolt')
    printing = CatalogPrinting(printing_id='p', set_code='m10', set_name='Magic 2010', number='146', rarity='common')
    row = ImportRow(line=2, quantity=3, name='bolt', condition='Excellent', language='ES', foil=True, price=1.5)
    assert matched_to_table(MatchedRow(row, 'ok', '', card, printing)) == {
        'line': 2, 'quantity': 3, 'name': 'Lightning Bolt', 'set': 'M10 · 146', 'condition': 'Excellent',
        'language': 'ES', 'price': '1.50', 'status': 'ok', 'reason': ''}
    lost = ImportRow(line=3, name='Nope', set_code='XXX')
    assert matched_to_table(MatchedRow(lost, 'sin casar', 'No está en el catálogo')) == {
        'line': 3, 'quantity': 1, 'name': 'Nope', 'set': 'XXX', 'condition': 'Near Mint', 'language': 'EN',
        'price': '', 'status': 'sin casar', 'reason': 'No está en el catálogo'}


def test_entry_to_table():
    from src.ui.csv_suite import entry_to_table

    item = EntryRow('1', 'Bolt', 'p', 'm10', '146', 'common', 'foil', None,
                    CollectionEntry(condition='Good', language='DE', quantity=4, list_price=2.0,
                                    storage_location='Caja 1', first_edition=True))
    assert entry_to_table(5, item) == {
        'id': 5, 'name': 'Bolt', 'set': 'M10', 'rarity': 'common', 'finish': 'foil', 'language': 'DE',
        'first': 'Sí', 'storage': 'Caja 1', 'quantity': 4, 'condition': 'Good', 'price': 2.0}


def test_parse_price():
    from src.ui.csv_suite import parse_price

    assert parse_price('') is None and parse_price(None) is None
    assert parse_price('1,50') == 1.5 and parse_price(2) == 2.0 and parse_price(' 3.25 € ') == 3.25
    for bad in ('abc', '-1', 'nan', 'inf'):
        with pytest.raises(ValueError, match='Precio no válido'):
            parse_price(bad)


def test_one_shot_ignores_repeated_clicks():
    import asyncio

    from src.ui.csv_suite import one_shot

    runs = []
    outcomes = iter([False, True])

    async def action():
        runs.append(1)
        await asyncio.sleep(0)
        return next(outcomes)

    guarded = one_shot(action)

    async def scenario():
        await asyncio.gather(guarded(), guarded())  # double click while the first is running
        assert len(runs) == 1                       # it failed, so the button works again
        await guarded()
        assert len(runs) == 2
        await guarded()                             # it succeeded: a late click does nothing
        assert len(runs) == 2

    asyncio.run(scenario())
