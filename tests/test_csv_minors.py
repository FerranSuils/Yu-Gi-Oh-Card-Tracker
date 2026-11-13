"""Loose ends of the CSV suite and the scan upload found in the phase 1b review."""
import io
from pathlib import Path

import pytest

from src.core.catalog_models import GameCollection, GameCollectionCard, GameCollectionVariant
from src.core.models import CollectionEntry
from src.services.csv_suite import (ImportRow, MatchedRow, export_rows, guess_mapping, parse_rows, read_table,
                                    to_csv)


def _parse(row: dict) -> ImportRow:
    return parse_rows([row], {field: field for field in row})[0]


# --- Numbers -----------------------------------------------------------------

@pytest.mark.parametrize('value, expected', [
    ('1,50', 1.5), ('1.50', 1.5), ('0,5', 0.5), ('.5', 0.5), ('3', 3.0), ('1.234,50', 1234.5), ('1,234.50', 1234.5),
    ('1.234.567', 1234567.0), ('1,500', 1500.0), ('1.500', 1500.0), ('0.500', 0.5), ('0,125', 0.125),
    ('12,3456', 12.3456), ('€ 2,00', 2.0), ('$3.25', 3.25), ('4,10 EUR', 4.1), ('1 234,50', 1234.5),
])
def test_price_reads_decimal_and_thousands_separators(value, expected):
    row = _parse({'name': 'x', 'price': value})
    assert row.error is None and row.price == expected


@pytest.mark.parametrize('value', ['1e3', '1E3', '12abc', '1-2', '--1', '1.2.3,4,5', 'nan', 'inf', '1,2,3', ','])
def test_price_rejects_what_is_not_a_plain_number(value):
    row = _parse({'name': 'x', 'price': value})
    assert row.price is None and 'Precio no válido' in row.error


@pytest.mark.parametrize('value, expected', [('1.000', 1000), ('1,000', 1000), ('2', 2), ('12.000', 12000),
                                             ('100000', 100000), ('3.0', 3)])
def test_quantity_reads_thousands_separators(value, expected):
    row = _parse({'name': 'x', 'quantity': value})
    assert row.error is None and row.quantity == expected


@pytest.mark.parametrize('value', ['1e3', '1,5', '100001', '1.000.000', '9999999999999999999999', '2x'])
def test_quantity_rejects_fractions_exponents_and_absurd_amounts(value):
    row = _parse({'name': 'x', 'quantity': value})
    assert row.quantity == 1 and 'Cantidad no válida' in row.error


# --- Reading -----------------------------------------------------------------

@pytest.mark.parametrize('data', [b'""', b'""\r\n', b'"";""\n', b'sep=;\n', b'\xef\xbb\xbf'])
def test_read_table_without_any_header_is_an_empty_file(data):
    with pytest.raises(ValueError, match='vacío'):
        read_table(data)


def test_read_table_honours_the_excel_separator_line():
    headers, rows = read_table(b'sep=;\r\nName;Note\r\nBolt;a,b,c\r\n')
    assert headers == ['Name', 'Note'] and rows == [{'Name': 'Bolt', 'Note': 'a,b,c'}]
    headers, rows = read_table(b'"sep=,"\nName,Qty\nBolt,2\n')
    assert headers == ['Name', 'Qty'] and rows == [{'Name': 'Bolt', 'Qty': '2'}]
    headers, rows = read_table(b'sep=|\nName|Qty\nBolt|2\n')
    assert headers == ['Name', 'Qty'] and rows == [{'Name': 'Bolt', 'Qty': '2'}]


@pytest.mark.parametrize('encoding', ['utf-16', 'utf-16-le', 'utf-16-be'])
def test_read_table_reads_utf16_from_excel(encoding):
    headers, rows = read_table('Nombre\tEdición\r\nDragón\tLOB\r\n'.encode(encoding))
    assert headers == ['Nombre', 'Edición'] and rows == [{'Nombre': 'Dragón', 'Edición': 'LOB'}]


# --- Formula guard -----------------------------------------------------------

def _collection_named(name: str, condition: str = 'Near Mint') -> GameCollection:
    return GameCollection(game='magic', name='x', cards=[GameCollectionCard(card_id='c', name=name, variants=[
        GameCollectionVariant(printing_id='p', set_code='m10', number='1', rarity='common',
                              entries=[CollectionEntry(quantity=1, condition=condition)])])])


@pytest.mark.parametrize('name', ['=1+1', ' =1+1', '\t=cmd', '\r=cmd', '\tplain', '  @SUM(A1)', '-2', '+2 Mace'])
def test_export_guards_formulas_hidden_behind_whitespace_and_round_trips(name):
    data = to_csv(export_rows(_collection_named(name), 'magic'))
    cell = data.decode('utf-8-sig').split('\r\n')[1].split(";")[11].strip('"')
    assert cell.startswith("'")
    headers, rows = read_table(data)
    assert parse_rows(rows, guess_mapping(headers))[0].name == name.strip()


def test_export_leaves_ordinary_text_alone():
    data = to_csv(export_rows(_collection_named("Jace's Ingenuity"), 'magic'))
    assert ";Jace's Ingenuity;" in data.decode('utf-8-sig')
    assert _parse({'name': "'Tis the Season"}).name == "'Tis the Season"


# --- Damaged -----------------------------------------------------------------

def test_damaged_survives_the_cardmarket_round_trip():
    data = to_csv(export_rows(_collection_named('Bolt', 'Damaged'), 'magic'))
    headers, rows = read_table(data)
    assert rows[0]['condition'] == 'PO' and rows[0]['comments'] == 'Damaged'
    assert parse_rows(rows, guess_mapping(headers))[0].condition == 'Damaged'


def test_poor_stays_poor_and_other_comments_do_not_change_the_condition():
    data = to_csv(export_rows(_collection_named('Bolt', 'Poor'), 'magic'))
    headers, rows = read_table(data)
    assert rows[0]['comments'] == '' and parse_rows(rows, guess_mapping(headers))[0].condition == 'Poor'
    assert _parse({'name': 'x', 'condition': 'PO', 'comment': 'esquina doblada'}).condition == 'Poor'
    assert _parse({'name': 'x', 'condition': 'NM', 'comment': 'Damaged'}).condition == 'Near Mint'
    assert _parse({'name': 'x', 'condition': 'po', 'comment': ' dañada '}).condition == 'Damaged'


# --- Rows that did not match ---------------------------------------------------

def test_problem_rows_csv_keeps_the_original_columns_and_says_why():
    from src.services.csv_suite import problem_rows_csv

    headers = ['Name', 'Set', '']
    rows = [{'Name': 'Bolt', 'Set': 'm10'}, {'Name': '=Nope', 'Set': 'XXX'}, {'Name': 'Pikachu', 'Set': ''},
            {'Name': 'x', 'Set': 'y'}]
    matched = [MatchedRow(ImportRow(line=2), 'ok'),
               MatchedRow(ImportRow(line=3), 'sin casar', 'No está en el catálogo'),
               MatchedRow(ImportRow(line=4), 'ambigua', '2 impresiones'),
               MatchedRow(ImportRow(line=5), 'error', 'Cantidad no válida')]
    data = problem_rows_csv(headers, rows, matched)
    lines = data.decode('utf-8-sig').split('\r\n')
    assert lines[0] == 'Name;Set;Línea;Resultado;Motivo'
    assert lines[1:] == ["'=Nope;XXX;3;sin casar;No está en el catálogo", 'Pikachu;;4;ambigua;2 impresiones',
                         'x;y;5;error;Cantidad no válida', '']
    # It can be corrected and imported again as it is.
    again, again_rows = read_table(data)
    assert again[:2] == ['Name', 'Set'] and [row['Name'] for row in again_rows] == ["'=Nope", 'Pikachu', 'x']
    assert problem_rows_csv(headers, rows, matched[:1]) == b''


def test_preview_offers_the_problem_rows():
    source = Path('src/ui/csv_suite.py').read_text(encoding='utf-8')
    assert 'problem_rows_csv(' in source and 'sin-casar.csv' in source


# --- Collection names ----------------------------------------------------------

@pytest.mark.parametrize('name, expected', [
    ('Mi colección', 'Mi colección.json'), ('Venta: abril?', 'Venta_ abril_.json'), ('a/b\\c*d|e<f>g"h', 'a_b_c_d_e_f_g_h.json'),
    ('  Caja 1.  ', 'Caja 1.json'), ('CON', '_CON.json'), ('lpt1', '_lpt1.json'), ('tab\there', 'tab_here.json'),
    ('nul.txt', '_nul.txt.json'),
])
def test_new_collection_filename_is_always_a_valid_windows_name(name, expected):
    from src.ui.catalog import new_collection_filename

    assert new_collection_filename(name) == expected


@pytest.mark.parametrize('name', ['', '   ', '...', ' . '])
def test_new_collection_filename_needs_a_name(name):
    from src.ui.catalog import new_collection_filename

    with pytest.raises(ValueError, match='nombre'):
        new_collection_filename(name)


def test_failure_text_never_shows_server_paths():
    from src.ui.csv_suite import failure_text

    assert failure_text('importar', ValueError('Elige una colección.')) == 'Elige una colección.'
    hidden = OSError(22, 'Invalid argument', r'C:\inetpub\vhosts\x\data\users\KKDBB\a.json')
    assert failure_text('importar', hidden) == 'No se ha podido importar. Inténtalo de nuevo.'
    assert failure_text('guardar', RuntimeError(r'D:\secret')) == 'No se ha podido guardar. Inténtalo de nuevo.'
    source = Path('src/ui/csv_suite.py').read_text(encoding='utf-8')
    assert ': {exc}' not in source


def test_edit_table_shows_prices_with_two_decimals():
    from src.ui.csv_suite import EDIT_COLUMNS

    price = next(column for column in EDIT_COLUMNS if column['name'] == 'price')
    assert 'toFixed(2)' in price[':format']


# --- Scan upload -----------------------------------------------------------------

def _encrypted_pdf(user_password: str) -> bytes:
    from PIL import Image
    from pypdf import PdfReader, PdfWriter

    plain = io.BytesIO()
    Image.new('RGB', (300, 420), (40, 90, 160)).save(plain, 'PDF')
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(plain.getvalue())))
    writer.encrypt(user_password, 'owner-secret', algorithm='RC4-128')
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_pdf_that_only_restricts_permissions_is_read():
    from src.services.scanner.upload import pdf_page_images

    assert len(pdf_page_images(_encrypted_pdf(''))) == 1


def test_pdf_that_needs_a_password_is_refused():
    from src.services.scanner.upload import pdf_page_images

    with pytest.raises(ValueError, match='contraseña'):
        pdf_page_images(_encrypted_pdf('abre'))


def _manager(tmp_path, monkeypatch, available: bool):
    import threading

    from src.services.scanner import manager as manager_module

    fake = type('M', (), {})()
    fake.queue_dir = str(tmp_path / 'queue')
    fake.notification_queue = type('Q', (), {'put': lambda self, item: None})()
    fake.queue_lock = threading.Lock()
    fake.scan_queue = []
    fake._log_debug = lambda *a: None
    fake._emit = lambda *a: None
    monkeypatch.setattr(manager_module, 'SCANNER_AVAILABLE', available, raising=False)
    monkeypatch.setattr(manager_module, 'ScanRequest', lambda **fields: fields, raising=False)
    return manager_module, fake


def test_submit_scan_says_whether_the_scan_was_queued(tmp_path, monkeypatch):
    module, fake = _manager(tmp_path, monkeypatch, True)
    (tmp_path / 'queue').mkdir()
    assert module.ScannerManager.submit_scan(fake, b'x', {}, filename='a.jpg') is True
    assert len(fake.scan_queue) == 1

    module, fake = _manager(tmp_path, monkeypatch, True)
    fake.queue_dir = str(tmp_path / 'missing' / 'queue')  # the write fails
    assert module.ScannerManager.submit_scan(fake, b'x', {}, filename='a.jpg') is False
    assert fake.scan_queue == []

    module, fake = _manager(tmp_path, monkeypatch, False)
    assert module.ScannerManager.submit_scan(fake, b'x', {}, filename='b.jpg') is False


@pytest.mark.parametrize('queued, total, name, from_pdf, expected', [
    (9, 9, 'doc.pdf', True, ('En cola: 9 cartas de doc.pdf', 'positive')),
    (1, 1, 'a.jpg', False, ('En cola: a.jpg', 'positive')),
    (1, 1, None, False, ('En cola: imagen', 'positive')),
    (7, 9, 'doc.pdf', True, ('En cola: 7 de 9 cartas de doc.pdf. El resto no se ha podido guardar.', 'warning')),
    (0, 9, None, True, ('No se ha podido poner en cola PDF.', 'negative')),
    (0, 1, 'a.jpg', False, ('No se ha podido poner en cola a.jpg.', 'negative')),
])
def test_queued_notice_only_claims_what_was_queued(queued, total, name, from_pdf, expected):
    from src.services.scanner.upload import queued_notice

    assert queued_notice(queued, total, name, from_pdf) == expected


def test_scan_upload_queues_off_the_ui_loop_and_reports_the_real_count():
    source = Path('src/ui/scan.py').read_text(encoding='utf-8')
    assert 'await run.io_bound(scanner_service.scanner_manager.submit_scan' in source
    assert 'queued_notice(' in source
