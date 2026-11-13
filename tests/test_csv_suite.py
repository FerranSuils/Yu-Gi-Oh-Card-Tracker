import csv
import io

import pytest

from src.core.catalog_models import (CatalogCard, CatalogPrinting, GameCollection, GameCollectionCard,
                                     GameCollectionVariant)
from src.core.models import ApiCard, ApiCardSet, Collection, CollectionCard, CollectionEntry, CollectionVariant
from src.services.csv_suite import (EXPORT_COLUMNS, CatalogIndex, ImportRow, apply_import, edit_entry, export_rows,
                                    guess_mapping, list_entries, match_rows, merge_collections, parse_rows,
                                    read_table, to_csv)

BOLT = CatalogCard(game='magic', card_id='o-bolt', name='Lightning Bolt', printings=[
    CatalogPrinting(printing_id='p-m10', set_code='m10', set_name='Magic 2010', number='146', rarity='common',
                    finishes=['nonfoil', 'foil'], market_ids={'cardmarket': '21390'}),
    CatalogPrinting(printing_id='p-lea', set_code='lea', set_name='Alpha', number='161', rarity='common',
                    finishes=['nonfoil'], market_ids={'cardmarket': '5000'}),
])
MACE = CatalogCard(game='magic', card_id='o-mace', name='+2 Mace', printings=[
    CatalogPrinting(printing_id='p-mace', set_code='afr', set_name='Forgotten Realms', number='1', rarity='common')])
PIKA_A = CatalogCard(game='pokemon', card_id='base1-58', name='Pikachu', printings=[
    CatalogPrinting(printing_id='base1-58', set_code='base1', set_name='Base', number='58', rarity='Common')])
PIKA_B = CatalogCard(game='pokemon', card_id='base2-60', name='Pikachu', printings=[
    CatalogPrinting(printing_id='base2-60', set_code='base2', set_name='Jungle', number='60', rarity='Common')])

BEWD_API = ApiCard(id=89631139, name='Blue-Eyes White Dragon', type='Normal Monster', frameType='normal', desc='',
                   card_sets=[
                       ApiCardSet(variant_id='v-lob', set_name='Legend of Blue Eyes', set_code='LOB-EN001',
                                  set_rarity='Ultra Rare', card_image_id=89631139),
                       ApiCardSet(variant_id='v-sdk', set_name='Starter Deck Kaiba', set_code='SDK-001',
                                  set_rarity='Ultra Rare', card_image_id=89631139),
                       ApiCardSet(variant_id='v-sdk-c', set_name='Starter Deck Kaiba', set_code='SDK-001',
                                  set_rarity='Common', card_image_id=89631139)])


def _ygo_index():
    from src.services.catalog.yugioh import catalog_card_from_api
    return CatalogIndex([catalog_card_from_api(BEWD_API)], 'yugioh')


def _magic_collection():
    return GameCollection(game='magic', name='Venta', cards=[
        GameCollectionCard(card_id='o-bolt', name='Lightning Bolt', variants=[
            GameCollectionVariant(printing_id='p-m10', set_code='m10', number='146', rarity='common', entries=[
                CollectionEntry(quantity=3, list_price=1.49, language='DE', storage_location='Caja 1'),
                CollectionEntry(quantity=1, condition='Damaged')]),
            GameCollectionVariant(printing_id='p-m10', set_code='m10', number='146', rarity='common',
                                  finish='foil', entries=[CollectionEntry(quantity=1, first_edition=True)])]),
        GameCollectionCard(card_id='o-mace', name='+2 Mace', variants=[
            GameCollectionVariant(printing_id='p-mace', set_code='afr', number='1', rarity='common', entries=[
                CollectionEntry(quantity=2)])]),
    ])


LOOKUP = {'o-bolt': BOLT, 'o-mace': MACE}.get


# --- Export ----------------------------------------------------------------

def test_export_rows_use_cardmarket_codes():
    rows = export_rows(_magic_collection(), 'magic', LOOKUP)
    assert len(rows) == 4
    first = rows[0]
    assert (first['idProduct'], first['groupCount'], first['price'], first['idLanguage'], first['condition']) == \
        ('21390', 3, '1.49', 3, 'NM')
    assert (first['isFoil'], first['isSigned'], first['isAltered'], first['isPlayset'], first['isFirstEd']) == \
        (0, 0, 0, 0, 0)
    assert (first['name'], first['expansion'], first['expansionCode'], first['number'], first['language'],
            first['storage'], first['game'], first['cardId'], first['printingId']) == \
        ('Lightning Bolt', 'Magic 2010', 'M10', '146', 'DE', 'Caja 1', 'magic', 'o-bolt', 'p-m10')
    assert rows[1]['condition'] == 'PO' and rows[1]['price'] == ''
    assert rows[2]['isFoil'] == 1 and rows[2]['isFirstEd'] == 1


def test_export_without_catalog_still_lists_the_cards():
    rows = export_rows(_magic_collection(), 'magic', lambda card_id: None)
    assert rows[0]['idProduct'] == '' and rows[0]['name'] == 'Lightning Bolt' and rows[0]['expansionCode'] == 'M10'


def test_to_csv_is_semicolon_utf8_bom_and_escapes_formulas():
    data = to_csv(export_rows(_magic_collection(), 'magic', LOOKUP))
    assert data.startswith(b'\xef\xbb\xbf')
    lines = list(csv.reader(io.StringIO(data.decode('utf-8-sig')), delimiter=';'))
    assert lines[0] == EXPORT_COLUMNS
    assert lines[0][:11] == ['idProduct', 'groupCount', 'price', 'idLanguage', 'condition', 'isFoil', 'isSigned',
                             'isAltered', 'isPlayset', 'isFirstEd', 'comments']
    assert lines[4][EXPORT_COLUMNS.index('name')] == "'+2 Mace"


def test_export_yugioh_collection():
    collection = Collection(name='YGO', cards=[CollectionCard(card_id=89631139, name='Blue-Eyes White Dragon',
        variants=[CollectionVariant(variant_id='v-lob', set_code='LOB-EN001', rarity='Ultra Rare', image_id=89631139,
                                    entries=[CollectionEntry(quantity=2, first_edition=True, list_price=30)])])])
    index = _ygo_index()
    row = export_rows(collection, 'yugioh', index.card)[0]
    assert (row['groupCount'], row['price'], row['isFirstEd'], row['expansionCode'], row['expansion'], row['rarity'],
            row['cardId'], row['printingId'], row['game']) == \
        (2, '30.00', 1, 'LOB-EN001', 'Legend of Blue Eyes', 'Ultra Rare', '89631139', 'v-lob', 'yugioh')


# --- Read and map ----------------------------------------------------------

def test_read_table_sniffs_delimiter_and_encoding():
    headers, rows = read_table('Name,Set,Qty\r\n"Bolt, Lightning",m10,2\r\n\r\n'.encode('utf-8-sig'))
    assert headers == ['Name', 'Set', 'Qty']
    assert rows == [{'Name': 'Bolt, Lightning', 'Set': 'm10', 'Qty': '2'}]
    headers, rows = read_table('Nombre;Edición\nDragón;LOB\n'.encode('cp1252'))
    assert headers == ['Nombre', 'Edición'] and rows[0]['Nombre'] == 'Dragón'
    headers, rows = read_table(b'name\tqty\nBolt\t1\n')
    assert rows == [{'name': 'Bolt', 'qty': '1'}]


def test_read_table_rejects_empty_and_huge_files():
    with pytest.raises(ValueError):
        read_table(b'')
    with pytest.raises(ValueError):
        read_table(b'   \n')
    with pytest.raises(ValueError, match='20000'):
        read_table(('name\n' + 'x\n' * 20001).encode())


def test_guess_mapping_knows_our_format_and_other_tools():
    mapping = guess_mapping(EXPORT_COLUMNS)
    assert mapping['quantity'] == 'groupCount' and mapping['language'] == 'idLanguage'
    assert mapping['set_code'] == 'expansionCode' and mapping['set_name'] == 'expansion'
    assert mapping['printing_id'] == 'printingId' and mapping['id_product'] == 'idProduct'
    assert mapping['first_edition'] == 'isFirstEd' and mapping['foil'] == 'isFoil'
    other = guess_mapping(['Product Name', 'Set Name', 'Number', 'Total Quantity', 'Condition', 'Printing',
                           'TCG Marketplace Price', 'Whatever'])
    assert other == {'name': 'Product Name', 'set_name': 'Set Name', 'number': 'Number',
                     'quantity': 'Total Quantity', 'condition': 'Condition', 'foil': 'Printing',
                     'price': 'TCG Marketplace Price'}


# --- Parse -----------------------------------------------------------------

def _parse(row: dict) -> ImportRow:
    return parse_rows([row], {field: field for field in row})[0]


def test_parse_row_normalises_values():
    row = _parse({'quantity': '4', 'name': " '+2 Mace ", 'condition': 'ex', 'language': '3', 'price': '1,50 €',
                  'foil': 'Foil', 'first_edition': 'x', 'storage': 'Caja 1', 'set_code': ' m10 '})
    assert (row.line, row.quantity, row.name, row.condition, row.language, row.price, row.foil, row.first_edition,
            row.storage, row.set_code, row.error) == \
        (2, 4, '+2 Mace', 'Excellent', 'DE', 1.5, True, True, 'Caja 1', 'm10', None)


@pytest.mark.parametrize('value, expected', [
    ('', 'Near Mint'), ('NM', 'Near Mint'), ('MT', 'Mint'), ('M', 'Mint'), ('PO', 'Poor'), ('Light Played', 'Light Played'),
    ('Lightly Played', 'Excellent'), ('Moderately Played', 'Good'), ('Heavily Played', 'Played'), ('damaged', 'Damaged'),
    ('Casi nueva', 'Near Mint'),
])
def test_parse_condition(value, expected):
    assert _parse({'name': 'x', 'condition': value}).condition == expected


@pytest.mark.parametrize('value, expected', [
    ('', 'EN'), ('1', 'EN'), ('4', 'ES'), ('7', 'JP'), ('10', 'KR'), ('de', 'DE'), ('German', 'DE'),
    ('Español', 'ES'), ('Japanese', 'JP'),
])
def test_parse_language(value, expected):
    assert _parse({'name': 'x', 'language': value}).language == expected


@pytest.mark.parametrize('field, value', [
    ('quantity', '0'), ('quantity', '-2'), ('quantity', 'dos'), ('price', '-1'), ('price', 'abc'),
    ('condition', 'perfecta'), ('language', 'klingon'),
])
def test_parse_reports_bad_values_per_row(field, value):
    assert _parse({'name': 'x', field: value}).error


def test_parse_defaults_and_plain_values():
    row = _parse({'name': 'Bolt', 'quantity': '', 'price': '', 'foil': '0', 'first_edition': 'no'})
    assert (row.quantity, row.price, row.foil, row.first_edition, row.storage) == (1, None, False, False, None)
    assert _parse({'name': 'x', 'price': '1.234,50'}).price == 1234.5
    assert _parse({'name': 'x', 'foil': 'Normal'}).foil is False


def test_parse_row_without_card_data_is_an_error():
    assert _parse({'quantity': '2'}).error


# --- Match -----------------------------------------------------------------

def _match(index, **fields):
    return match_rows([ImportRow(line=2, **fields)], index)[0]


def test_match_by_printing_id_then_product_id():
    index = CatalogIndex([BOLT, MACE], 'magic')
    hit = _match(index, printing_id='p-lea')
    assert (hit.status, hit.card.card_id, hit.printing.printing_id) == ('ok', 'o-bolt', 'p-lea')
    assert _match(index, id_product='21390').printing.printing_id == 'p-m10'
    assert _match(index, printing_id='nope', id_product='5000').printing.printing_id == 'p-lea'


def test_match_by_set_and_number_or_name():
    index = CatalogIndex([BOLT, MACE], 'magic')
    assert _match(index, set_code='M10', number='0146').printing.printing_id == 'p-m10'
    assert _match(index, set_code='lea', name='lightning bolt').printing.printing_id == 'p-lea'
    assert _match(index, set_name='magic 2010', name='Lightning Bolt').printing.printing_id == 'p-m10'
    assert _match(index, name='+2 Mace').printing.printing_id == 'p-mace'


def test_match_reports_ambiguous_and_unknown_rows():
    index = CatalogIndex([BOLT, MACE], 'magic')
    ambiguous = _match(index, name='Lightning Bolt')
    assert ambiguous.status == 'ambigua' and ambiguous.printing is None and ambiguous.reason
    unknown = _match(index, name='Black Lotus')
    assert unknown.status == 'sin casar' and unknown.reason
    broken = match_rows([ImportRow(line=3, name='Bolt', error='Cantidad no válida')], index)[0]
    assert broken.status == 'error' and broken.reason == 'Cantidad no válida'


def test_match_same_name_on_different_cards_needs_the_set():
    index = CatalogIndex([PIKA_A, PIKA_B], 'pokemon')
    assert _match(index, name='Pikachu').status == 'ambigua'
    assert _match(index, name='Pikachu', set_code='base2').card.card_id == 'base2-60'


def test_match_yugioh_set_codes_in_any_language():
    index = _ygo_index()
    assert _match(index, set_code='LOB-DE001').printing.printing_id == 'v-lob'
    assert _match(index, set_code='lob-001').printing.printing_id == 'v-lob'
    assert _match(index, set_code='LOB', number='EN001').printing.printing_id == 'v-lob'
    assert _match(index, set_code='SDK-001').status == 'ambigua'
    assert _match(index, set_code='SDK-001', rarity='common').printing.printing_id == 'v-sdk-c'


# --- Apply -----------------------------------------------------------------

def test_apply_import_adds_to_a_game_collection_and_sets_price():
    index = CatalogIndex([BOLT, MACE], 'magic')
    collection = _magic_collection()
    matched = match_rows([
        ImportRow(line=2, printing_id='p-m10', quantity=2, language='DE', storage='Caja 1', price=2.0),
        ImportRow(line=3, printing_id='p-lea', quantity=1, foil=True, condition='Good'),
        ImportRow(line=4, name='Black Lotus'),
    ], index)
    assert apply_import(collection, matched) == 3
    bolt = collection.cards[0]
    assert (bolt.variants[0].entries[0].quantity, bolt.variants[0].entries[0].list_price) == (5, 2.0)
    lea = next(v for v in bolt.variants if v.printing_id == 'p-lea')
    assert (lea.finish, lea.entries[0].condition, lea.entries[0].quantity, lea.entries[0].list_price) == \
        ('nonfoil', 'Good', 1, None)  # Alpha has no foil: falls back to a finish that exists
    assert apply_import(collection, matched) == 3 and bolt.variants[0].entries[0].quantity == 7


def test_apply_import_adds_to_a_yugioh_collection():
    collection = Collection(name='YGO')
    matched = match_rows([ImportRow(line=2, set_code='LOB-EN001', quantity=2, first_edition=True, price=30.0,
                                    language='DE')], _ygo_index())
    assert apply_import(collection, matched, api_card_for={89631139: BEWD_API}.get) == 2
    variant = collection.cards[0].variants[0]
    assert (collection.cards[0].card_id, variant.variant_id, variant.set_code, variant.rarity, variant.image_id) == \
        (89631139, 'v-lob', 'LOB-EN001', 'Ultra Rare', 89631139)
    entry = variant.entries[0]
    assert (entry.quantity, entry.first_edition, entry.language, entry.list_price) == (2, True, 'DE', 30.0)
    assert apply_import(collection, matched, api_card_for=lambda card_id: None) == 0


# --- Merge -----------------------------------------------------------------

def test_merge_game_collections_adds_quantities_and_keeps_prices():
    other = GameCollection(game='magic', name='Otra', cards=[
        GameCollectionCard(card_id='o-bolt', name='Lightning Bolt', variants=[
            GameCollectionVariant(printing_id='p-m10', set_code='m10', number='146', rarity='common', entries=[
                CollectionEntry(quantity=2, language='DE', storage_location='Caja 1', list_price=9.0),
                CollectionEntry(quantity=1, condition='Played', list_price=0.5, price_locked=True)])])])
    source = _magic_collection()
    merged = merge_collections('Todo', [source, other])
    assert isinstance(merged, GameCollection) and (merged.game, merged.name) == ('magic', 'Todo')
    entries = merged.cards[0].variants[0].entries
    assert (entries[0].quantity, entries[0].list_price) == (5, 1.49)  # first price wins
    played = next(e for e in entries if e.condition == 'Played')
    assert (played.quantity, played.list_price, played.price_locked) == (1, 0.5, True)
    assert merged.total_cards == source.total_cards + 3
    assert source.cards[0].variants[0].entries[0].quantity == 3  # sources untouched


def test_merge_yugioh_collections():
    def one(quantity):
        return Collection(name='c', cards=[CollectionCard(card_id=1, name='A', variants=[
            CollectionVariant(variant_id='v', set_code='X-EN001', rarity='Common', image_id=1,
                              entries=[CollectionEntry(quantity=quantity)])])])
    merged = merge_collections('Todo', [one(1), one(4)])
    assert isinstance(merged, Collection) and merged.name == 'Todo'
    variant = merged.cards[0].variants[0]
    assert (variant.variant_id, variant.image_id, variant.entries[0].quantity) == ('v', 1, 5)


def test_merge_rejects_mixed_games():
    with pytest.raises(ValueError):
        merge_collections('x', [_magic_collection(), Collection(name='y')])
    with pytest.raises(ValueError):
        merge_collections('x', [_magic_collection(), GameCollection(game='pokemon', name='p')])


# --- Edit ------------------------------------------------------------------

def test_list_entries_has_one_row_per_stack():
    rows = list_entries(_magic_collection())
    assert len(rows) == 4
    assert (rows[0].name, rows[0].set_code, rows[0].finish, rows[0].entry.quantity) == \
        ('Lightning Bolt', 'm10', 'nonfoil', 3)


def test_edit_entry_changes_quantity_and_price():
    collection = _magic_collection()
    row = list_entries(collection)[0]
    assert edit_entry(collection, row, quantity=5, condition='Near Mint', price=2.5) is True
    entry = collection.cards[0].variants[0].entries[0]
    assert (entry.quantity, entry.list_price, entry.language, entry.storage_location) == (5, 2.5, 'DE', 'Caja 1')
    assert edit_entry(collection, list_entries(collection)[0], quantity=5, condition='Near Mint', price=2.5) is False


def test_edit_entry_zero_quantity_removes_the_stack():
    collection = _magic_collection()
    edit_entry(collection, list_entries(collection)[3], quantity=0, condition='Near Mint', price=None)
    assert [c.name for c in collection.cards] == ['Lightning Bolt']


def test_edit_entry_condition_change_merges_into_an_existing_stack():
    collection = GameCollection(game='magic', name='M', cards=[GameCollectionCard(card_id='o', name='Bolt', variants=[
        GameCollectionVariant(printing_id='p', set_code='m10', entries=[
            CollectionEntry(quantity=2, list_price=1.0, price_locked=True),
            CollectionEntry(quantity=3, condition='Good')])])])
    edit_entry(collection, list_entries(collection)[0], quantity=2, condition='Good', price=1.0)
    entries = collection.cards[0].variants[0].entries
    assert len(entries) == 1
    assert (entries[0].condition, entries[0].quantity, entries[0].list_price, entries[0].price_locked) == \
        ('Good', 5, 1.0, True)


def test_edit_entry_on_a_yugioh_collection():
    collection = Collection(name='c', cards=[CollectionCard(card_id=1, name='A', variants=[
        CollectionVariant(variant_id='v', set_code='X-EN001', rarity='Common', image_id=1,
                          entries=[CollectionEntry(quantity=1)])])])
    edit_entry(collection, list_entries(collection)[0], quantity=3, condition='Played', price=None)
    variant = collection.cards[0].variants[0]
    assert (variant.variant_id, variant.image_id) == ('v', 1)
    assert (variant.entries[0].condition, variant.entries[0].quantity, variant.entries[0].list_price) == \
        ('Played', 3, None)


def test_edit_entry_rejects_bad_values():
    collection = _magic_collection()
    row = list_entries(collection)[0]
    with pytest.raises(ValueError):
        edit_entry(collection, row, quantity=-1, condition='Near Mint', price=None)
    with pytest.raises(ValueError):
        edit_entry(collection, row, quantity=1, condition='Perfecta', price=None)
    with pytest.raises(ValueError):
        edit_entry(collection, row, quantity=1, condition='Near Mint', price=-3)


def test_round_trip_export_then_import_rebuilds_the_collection():
    source = _magic_collection()
    source.cards[0].variants[0].entries[1].condition = 'Poor'  # Damaged shares Cardmarket's PO code
    headers, rows = read_table(to_csv(export_rows(source, 'magic', LOOKUP)))
    matched = match_rows(parse_rows(rows, guess_mapping(headers)), CatalogIndex([BOLT, MACE], 'magic'))
    assert [m.status for m in matched] == ['ok'] * 4
    rebuilt = GameCollection(game='magic', name='Copia')
    assert apply_import(rebuilt, matched) == source.total_cards
    assert rebuilt.model_dump()['cards'] == source.model_dump()['cards']


def test_bulk_edit_changes_only_the_chosen_stacks():
    from src.services.csv_suite import bulk_edit, entry_key

    collection = _magic_collection()
    items = list_entries(collection)
    keys = [entry_key(items[0]), entry_key(items[3]), ('gone', 'p', 'nonfoil', 'Near Mint', 'EN', False, None)]
    assert bulk_edit(collection, keys, condition='Good', price=0.75) == (2, 1)
    after = list_entries(collection)
    # A new condition makes a new stack, so the order within a printing may change.
    assert sorted(((i.name, i.finish, i.entry.condition, i.entry.quantity, i.entry.list_price) for i in after),
                  key=str) == sorted([('Lightning Bolt', 'nonfoil', 'Good', 3, 0.75),
                                      ('Lightning Bolt', 'nonfoil', 'Damaged', 1, None),
                                      ('Lightning Bolt', 'foil', 'Near Mint', 1, None),
                                      ('+2 Mace', 'nonfoil', 'Good', 2, 0.75)], key=str)


def test_bulk_edit_can_clear_prices_and_set_quantity():
    from src.services.csv_suite import bulk_edit, entry_key

    collection = _magic_collection()
    key = entry_key(list_entries(collection)[0])
    assert bulk_edit(collection, [key], quantity=7, clear_price=True) == (1, 0)
    entry = list_entries(collection)[0].entry
    assert (entry.quantity, entry.condition, entry.list_price) == (7, 'Near Mint', None)
    assert bulk_edit(collection, [entry_key(list_entries(collection)[0])]) == (0, 0)


# --- Review fixes ------------------------------------------------------------
def test_condition_change_into_a_priced_stack_keeps_that_price():
    from src.services.csv_suite import bulk_edit, entry_key

    collection = GameCollection(game='magic', name='M', cards=[GameCollectionCard(card_id='o', name='Bolt', variants=[
        GameCollectionVariant(printing_id='p', set_code='m10', entries=[
            CollectionEntry(quantity=2),
            CollectionEntry(quantity=3, condition='Excellent', list_price=5.0, price_locked=True)])])])
    assert bulk_edit(collection, [entry_key(list_entries(collection)[0])], condition='Excellent') == (1, 0)
    entries = collection.cards[0].variants[0].entries
    assert [(e.condition, e.quantity, e.list_price, e.price_locked) for e in entries] == [('Excellent', 5, 5.0, True)]


def test_bulk_edit_lists_the_collection_once(monkeypatch):
    from src.services import csv_suite

    collection = _magic_collection()
    keys = [csv_suite.entry_key(item) for item in list_entries(collection)]
    calls = []
    real = csv_suite.list_entries
    monkeypatch.setattr(csv_suite, 'list_entries', lambda c: calls.append(1) or real(c))
    assert csv_suite.bulk_edit(collection, keys + keys[:1], price=2.0) == (4, 1)  # a repeated key is not there twice
    assert len(calls) == 1


@pytest.mark.parametrize('value, condition, foil, first', [
    ('Near Mint Foil', 'Near Mint', True, False),
    ('Lightly Played 1st Edition', 'Excellent', False, True),
    ('Moderately Played Holofoil', 'Good', True, False),
    ('Near Mint Reverse Holofoil', 'Near Mint', True, False),
    ('Near Mint Unlimited', 'Near Mint', False, False),
    ('Heavily Played 1st Edition Foil', 'Played', True, True),
    ('Good (Lightly Played)', 'Excellent', False, False),
    ('Near Mint', 'Near Mint', False, False),
])
def test_parse_condition_from_other_stores(value, condition, foil, first):
    row = _parse({'name': 'x', 'condition': value})
    assert (row.condition, row.foil, row.first_edition, row.error) == (condition, foil, first, None)


def test_condition_suffix_does_not_undo_an_explicit_foil_column():
    row = _parse({'name': 'x', 'condition': 'Near Mint', 'foil': 'foil'})
    assert row.foil is True


def test_match_accepts_a_set_code_in_the_edition_column():
    # Moxfield writes the set code under "Edition", which maps to the set name.
    index = CatalogIndex([BOLT, MACE], 'magic')
    assert _match(index, set_name='M10', name='Lightning Bolt').printing.printing_id == 'p-m10'
