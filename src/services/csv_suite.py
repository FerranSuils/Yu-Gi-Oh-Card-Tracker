"""CSV Suite: export, import, merge and bulk-edit collections of any game.

The export uses the column names of a Cardmarket stock file (``idProduct``, ``groupCount``,
``idLanguage``…) followed by readable columns, so one file serves Cardmarket-style tools,
a spreadsheet and our own import.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Optional

from src.core.catalog_models import CatalogCard, CatalogPrinting, GameCollection
from src.core.constants import CARD_CONDITIONS
from src.core.game_collections import GameCollectionEditor
from src.core.models import Collection, CollectionEntry
from src.services.collection_editor import CollectionEditor

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000
MAX_QUANTITY = 100000  # per row; more than this is a typo or a broken column

EXPORT_COLUMNS = ['idProduct', 'groupCount', 'price', 'idLanguage', 'condition', 'isFoil', 'isSigned',
                  'isAltered', 'isPlayset', 'isFirstEd', 'comments', 'name', 'expansion', 'expansionCode',
                  'number', 'rarity', 'language', 'storage', 'game', 'cardId', 'printingId']

CONDITION_CODES = {'Mint': 'MT', 'Near Mint': 'NM', 'Excellent': 'EX', 'Good': 'GD', 'Light Played': 'LP',
                   'Played': 'PL', 'Poor': 'PO', 'Damaged': 'PO'}
LANGUAGE_IDS = {'EN': 1, 'FR': 2, 'DE': 3, 'ES': 4, 'IT': 5, 'ZH': 6, 'JP': 7, 'PT': 8, 'RU': 9, 'KR': 10,
                'ZH-TW': 11}

_FORMULA_START = ('=', '+', '-', '@')


def _norm(text: Any) -> str:
    """Lower-case, accent-free, alphanumeric only: 'Set Name' and 'set_name' compare equal."""
    plain = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]', '', plain.lower())


# --- Export ----------------------------------------------------------------

@dataclass
class EntryRow:
    """One physical stack, with what identifies it."""
    card_id: Any
    name: str
    printing_id: str
    set_code: str
    number: Optional[str]
    rarity: Optional[str]
    finish: str
    image_id: Optional[int]
    entry: CollectionEntry


def list_entries(collection) -> list[EntryRow]:
    rows = []
    for card in collection.cards:
        for variant in card.variants:
            for entry in variant.entries:
                if isinstance(collection, GameCollection):
                    rows.append(EntryRow(card.card_id, card.name, variant.printing_id, variant.set_code,
                                         variant.number, variant.rarity, variant.finish, None, entry))
                else:
                    rows.append(EntryRow(card.card_id, card.name, variant.variant_id, variant.set_code,
                                         None, variant.rarity, 'nonfoil', variant.image_id, entry))
    return rows


def export_rows(collection, game: str, lookup: Optional[Callable[[Any], Optional[CatalogCard]]] = None) -> list[dict]:
    """One dict per stack. ``lookup(card_id)`` gives the catalog card, for idProduct and set name."""
    rows = []
    cache: dict = {}
    for item in list_entries(collection):
        if item.card_id not in cache:
            cache[item.card_id] = lookup(item.card_id) if lookup else None
        catalog = cache[item.card_id]
        printing = next((p for p in catalog.printings if p.printing_id == item.printing_id), None) if catalog else None
        entry = item.entry
        rows.append({
            'idProduct': (printing.market_ids.get('cardmarket', '') if printing else ''),
            'groupCount': entry.quantity,
            'price': '' if entry.list_price is None else f'{entry.list_price:.2f}',
            'idLanguage': LANGUAGE_IDS.get((entry.language or 'EN').upper(), ''),
            'condition': CONDITION_CODES.get(entry.condition, 'NM'),
            'isFoil': int(item.finish != 'nonfoil'),
            'isSigned': 0, 'isAltered': 0, 'isPlayset': 0,
            'isFirstEd': int(bool(entry.first_edition)),
            # Cardmarket has no Damaged grade: it travels as Poor plus a comment.
            'comments': 'Damaged' if entry.condition == 'Damaged' else '',
            'name': item.name,
            'expansion': printing.set_name if printing else '',
            'expansionCode': (item.set_code or '').upper(),
            'number': item.number or (printing.number if printing and printing.number else ''),
            'rarity': item.rarity or '',
            'language': (entry.language or 'EN').upper(),
            'storage': entry.storage_location or '',
            'game': game,
            'cardId': str(item.card_id),
            'printingId': item.printing_id,
        })
    return rows


def _risky(value: str) -> bool:
    # Spreadsheets skip leading blanks before deciding a cell is a formula; tab and CR start one too.
    return value[:1] in ('\t', '\r') or value.lstrip()[:1] in _FORMULA_START


def _guard(value: Any) -> Any:
    """A text cell starting with = + - @ would run as a formula in a spreadsheet."""
    if isinstance(value, str) and _risky(value):
        return "'" + value
    return value


def _unguard(value: str) -> str:
    return value[1:] if value[:1] == "'" and _risky(value[1:]) else value


def to_csv(rows: Iterable[dict]) -> bytes:
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, delimiter=';', lineterminator='\r\n')
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        writer.writerow([_guard(row.get(column, '')) for column in EXPORT_COLUMNS])
    return buffer.getvalue().encode('utf-8-sig')


# --- Read and map ----------------------------------------------------------

def _sniff_delimiter(header_line: str) -> str:
    counts = {}
    for delimiter in (';', ',', '\t'):
        try:
            counts[delimiter] = len(next(csv.reader([header_line], delimiter=delimiter)))
        except (csv.Error, StopIteration):
            counts[delimiter] = 0
    return max(counts, key=counts.get)


def _decode(data: bytes) -> str:
    """Text of a CSV in UTF-8, UTF-16 (Excel's "Unicode text") or Windows-1252."""
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return data.decode('utf-16', errors='replace')
    sample = data[:4096]
    half = len(sample) // 2
    if half:
        even, odd = sample[0::2].count(0), sample[1::2].count(0)
        if odd > half * 0.4 and even < half * 0.1:
            return data.decode('utf-16-le', errors='replace')
        if even > half * 0.4 and odd < half * 0.1:
            return data.decode('utf-16-be', errors='replace')
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('cp1252', errors='replace')


def _first_line(text: str) -> Optional[str]:
    return next((line for line in text.splitlines() if line.strip()), None)


def read_table(data: bytes) -> tuple[list[str], list[dict]]:
    """Headers and rows of a CSV in UTF-8, UTF-16 or Windows-1252, separated by ';', ',' or tab."""
    if len(data) > MAX_BYTES:
        raise ValueError('El archivo supera los 5 MB')
    text = _decode(data).replace('\x00', '').lstrip('\ufeff')
    first = _first_line(text)
    delimiter = None
    hint = re.fullmatch(r'"?sep=(.)"?', first.strip(), re.IGNORECASE) if first else None
    if hint:  # Excel's own first line naming the separator
        delimiter = hint.group(1)
        text = text.partition(first)[2]
        first = _first_line(text)
    if first is None:
        raise ValueError('El archivo está vacío')
    try:
        lines = [line for line in csv.reader(io.StringIO(text, newline=''),
                                             delimiter=delimiter or _sniff_delimiter(first))
                 if any(cell.strip() for cell in line)]
    except csv.Error as exc:
        raise ValueError(f'No se ha podido leer el CSV: {exc}') from exc
    if not lines:
        raise ValueError('El archivo está vacío')
    headers = [cell.strip() for cell in lines[0]]
    if len(lines) - 1 > MAX_ROWS:
        raise ValueError(f'El archivo tiene más de {MAX_ROWS} filas')
    rows = []
    for line in lines[1:]:
        cells = [cell.strip() for cell in line] + [''] * len(headers)
        rows.append({header: cells[i] for i, header in enumerate(headers) if header})
    return headers, rows


# Field -> header names it is known by, best first (compared with _norm).
ALIASES: dict[str, list[str]] = {
    'quantity': ['groupCount', 'quantity', 'qty', 'cantidad', 'Total Quantity', 'Add to Quantity', 'amount',
                 'count', 'stock', 'unidades'],
    'name': ['name', 'Product Name', 'card name', 'cardname', 'nombre', 'carta', 'enName', 'card', 'title'],
    'set_code': ['expansionCode', 'set code', 'setcode', 'set', 'edition code', 'codigo', 'code',
                 'set abbreviation'],
    'set_name': ['expansion', 'Set Name', 'expansion name', 'edition', 'edicion', 'coleccion'],
    'number': ['number', 'collector number', 'card number', 'numero', 'cn', 'num'],
    'rarity': ['rarity', 'rareza'],
    'condition': ['condition', 'estado', 'cond', 'minCondition'],
    'language': ['idLanguage', 'language', 'idioma', 'lang'],
    'first_edition': ['isFirstEd', 'first edition', '1st edition', 'firstedition', 'primera edicion', 'edition1'],
    'foil': ['isFoil', 'foil', 'Printing', 'finish', 'acabado', 'isReverseHolo'],
    'price': ['price', 'precio', 'TCG Marketplace Price', 'list price', 'sale price', 'my price', 'precio venta'],
    'storage': ['storage', 'ubicacion', 'location', 'almacen', 'caja'],
    'id_product': ['idProduct', 'product id', 'cardmarket id', 'cardmarketid', 'idarticle product'],
    'printing_id': ['printingId', 'printing id', 'scryfall id', 'scryfallid', 'variant id', 'variantid'],
    'card_id': ['cardId', 'card id', 'oracle id', 'passcode', 'konami id'],
    'comment': ['comments', 'comment', 'comentario', 'comentarios', 'notes', 'notas'],
}
FIELD_LABELS = {'quantity': 'Cantidad', 'name': 'Nombre', 'set_code': 'Código de set', 'set_name': 'Edición',
                'number': 'Número', 'rarity': 'Rareza', 'condition': 'Estado', 'language': 'Idioma',
                'first_edition': '1.ª edición', 'foil': 'Foil', 'price': 'Precio de venta',
                'storage': 'Ubicación', 'id_product': 'Id de producto Cardmarket',
                'printing_id': 'Id de impresión', 'card_id': 'Id de carta', 'comment': 'Comentario'}


def guess_mapping(headers: Iterable[str]) -> dict[str, str]:
    """Which header feeds each field. Each header is used once."""
    by_norm: dict[str, str] = {}
    for header in headers:
        by_norm.setdefault(_norm(header), header)
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for field, aliases in ALIASES.items():
        for alias in aliases:
            header = by_norm.get(_norm(alias))
            if header and header not in used:
                mapping[field] = header
                used.add(header)
                break
    return mapping


# --- Parse -----------------------------------------------------------------

@dataclass
class ImportRow:
    line: int
    quantity: int = 1
    name: str = ''
    set_code: str = ''
    set_name: str = ''
    number: str = ''
    rarity: str = ''
    condition: str = 'Near Mint'
    language: str = 'EN'
    first_edition: bool = False
    foil: bool = False
    price: Optional[float] = None
    storage: Optional[str] = None
    id_product: str = ''
    printing_id: str = ''
    card_id: str = ''
    comment: str = ''
    error: Optional[str] = None


_CONDITIONS = {_norm(name): name for name in CARD_CONDITIONS}
_CONDITIONS.update({
    'mt': 'Mint', 'm': 'Mint', 'nm': 'Near Mint', 'ex': 'Excellent', 'gd': 'Good', 'lp': 'Light Played',
    'pl': 'Played', 'po': 'Poor',
    # TCGplayer's scale sits one step below Cardmarket's for the same words.
    'lightlyplayed': 'Excellent', 'moderatelyplayed': 'Good', 'mp': 'Good', 'heavilyplayed': 'Played',
    'hp': 'Played', 'dmg': 'Damaged',
    'nueva': 'Mint', 'casinueva': 'Near Mint', 'excelente': 'Excellent', 'buena': 'Good',
    'pocojugada': 'Light Played', 'jugada': 'Played', 'pobre': 'Poor', 'danada': 'Damaged',
})
_LANGUAGES = {str(number): code for code, number in LANGUAGE_IDS.items()}
_LANGUAGES.update({_norm(code): code for code in LANGUAGE_IDS})
_LANGUAGES.update({
    'english': 'EN', 'ingles': 'EN', 'french': 'FR', 'frances': 'FR', 'francais': 'FR', 'german': 'DE',
    'aleman': 'DE', 'deutsch': 'DE', 'spanish': 'ES', 'espanol': 'ES', 'castellano': 'ES', 'sp': 'ES',
    'italian': 'IT', 'italiano': 'IT', 'portuguese': 'PT', 'portugues': 'PT', 'japanese': 'JP', 'japones': 'JP',
    'ja': 'JP', 'korean': 'KR', 'coreano': 'KR', 'ko': 'KR', 'russian': 'RU', 'ruso': 'RU', 'chinese': 'ZH',
    'chino': 'ZH', 'schinese': 'ZH', 'simplifiedchinese': 'ZH', 'tchinese': 'ZH-TW',
    'traditionalchinese': 'ZH-TW',
})
_FALSE = {'', '0', 'false', 'no', 'n', 'normal', 'nonfoil', 'f', 'falso', 'unlimited'}


# TCGplayer appends the printing to the condition: "Near Mint Foil", "Lightly Played 1st Edition".
_CONDITION_SUFFIXES = (('reverseholofoil', 'foil'), ('holofoil', 'foil'), ('foil', 'foil'),
                       ('1stedition', 'first'), ('firstedition', 'first'), ('unlimited', ''), ('limited', ''))


def _condition(value: str) -> tuple[Optional[str], bool, bool]:
    """(our condition or None, says foil, says first edition) for a condition cell of any store."""
    inner = re.search(r'\(([^)]+)\)', value)  # Deckbox: "Good (Lightly Played)"
    text = _norm(inner.group(1) if inner else value)
    flags = set()
    while text not in _CONDITIONS:
        for suffix, flag in _CONDITION_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[:-len(suffix)]
                flags.add(flag)
                break
        else:
            return None, False, False
    return _CONDITIONS[text], 'foil' in flags, 'first' in flags


_CURRENCY = re.compile(r'[\s\u00a0€$£¥]|eur|usd|gbp', re.IGNORECASE)
_PLAIN_NUMBER = re.compile(r'\d[\d.,]*|[.,]\d+')
_DAMAGED_COMMENTS = {'damaged', 'danada', 'dmg'}


def _grouped(parts: list[str]) -> bool:
    """'1', '234', '567': digits split in thousands."""
    return 1 <= len(parts[0]) <= 3 and parts[0].strip('0') != '' and all(len(part) == 3 for part in parts[1:])


def _number(value: str) -> float:
    """A positive amount as people and stores write it: 1,50 · 1.50 · 1.234,50 · 1,234.50 · € 2.

    Raises ValueError for anything else (1e3, 12abc, -1). A single separator followed by exactly
    three digits (1.500) is read as thousands: wrong the other way would sell a card 1000 times cheaper.
    """
    cleaned = _CURRENCY.sub('', value)
    if not _PLAIN_NUMBER.fullmatch(cleaned):
        raise ValueError(value)
    if ',' in cleaned and '.' in cleaned:
        decimal = ',' if cleaned.rfind(',') > cleaned.rfind('.') else '.'
        thousands = '.' if decimal == ',' else ','
        whole, _, fraction = cleaned.rpartition(decimal)
        if decimal in whole or not _grouped(whole.split(thousands)):
            raise ValueError(value)
        return float(f"{whole.replace(thousands, '')}.{fraction}")
    separator = ',' if ',' in cleaned else '.' if '.' in cleaned else None
    if separator is None:
        return float(cleaned)
    parts = cleaned.split(separator)
    if _grouped(parts):
        return float(''.join(parts))
    if len(parts) > 2:
        raise ValueError(value)
    return float(f"{parts[0] or '0'}.{parts[1] or '0'}")


def _parse_one(line: int, raw: dict, mapping: dict[str, str]) -> ImportRow:
    def cell(field: str) -> str:
        header = mapping.get(field)
        return _unguard(str(raw.get(header, '') or '').strip()).strip() if header else ''

    row = ImportRow(line=line, name=cell('name'), set_code=cell('set_code'), set_name=cell('set_name'),
                    number=cell('number'), rarity=cell('rarity'), storage=cell('storage') or None,
                    id_product=cell('id_product'), printing_id=cell('printing_id'), card_id=cell('card_id'),
                    comment=cell('comment'))
    row.foil = _norm(cell('foil')) not in _FALSE
    row.first_edition = _norm(cell('first_edition')) not in _FALSE

    errors = []
    quantity = cell('quantity')
    if quantity:
        try:
            value = _number(quantity)
            if value != int(value) or value <= 0 or value > MAX_QUANTITY:
                raise ValueError
            row.quantity = int(value)
        except (ValueError, OverflowError):
            errors.append('Cantidad no válida')
    price = cell('price')
    if price:
        try:
            row.price = _number(price)
            if row.price < 0 or row.price != row.price or row.price == float('inf'):
                raise ValueError
        except (ValueError, OverflowError):
            row.price = None
            errors.append('Precio no válido')
    condition = cell('condition')
    if condition:
        known, foil, first = _condition(condition)
        if known:
            row.condition = known
            if known == 'Poor' and _norm(row.comment) in _DAMAGED_COMMENTS:
                row.condition = 'Damaged'  # our own export: Cardmarket has no Damaged grade
            row.foil = row.foil or foil
            row.first_edition = row.first_edition or first
        else:
            errors.append(f'Estado desconocido: {condition}')
    language = cell('language')
    if language:
        if _norm(language) in _LANGUAGES:
            row.language = _LANGUAGES[_norm(language)]
        else:
            errors.append(f'Idioma desconocido: {language}')
    if not (row.name or row.set_code or row.id_product or row.printing_id):
        errors.append('Fila sin datos de carta')
    row.error = '; '.join(errors) or None
    return row


PROBLEM_COLUMNS = ['Línea', 'Resultado', 'Motivo']


def problem_rows_csv(headers: Iterable[str], rows: list[dict], matched: Iterable['MatchedRow']) -> bytes:
    """The rows that were not imported, as they came, plus why. Empty when every row matched.

    The file can be corrected and imported again: the three extra columns are ignored.
    """
    columns = [header for header in headers if header and header not in PROBLEM_COLUMNS]
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, delimiter=';', lineterminator='\r\n')
    writer.writerow(columns + PROBLEM_COLUMNS)
    count = 0
    for item in matched:
        index = item.row.line - 2
        if item.status == 'ok' or not 0 <= index < len(rows):
            continue
        writer.writerow([_guard(_unguard(str(rows[index].get(column, '')))) for column in columns]
                        + [item.row.line, item.status, _guard(item.reason or '')])
        count += 1
    return buffer.getvalue().encode('utf-8-sig') if count else b''


def parse_rows(rows: Iterable[dict], mapping: dict[str, str]) -> list[ImportRow]:
    """Typed rows; a bad value marks its row with ``error`` instead of stopping the import."""
    return [_parse_one(index + 2, raw, mapping) for index, raw in enumerate(rows)]


# --- Match -----------------------------------------------------------------

_YGO_REGIONS = ('EN', 'DE', 'FR', 'IT', 'SP', 'PT', 'JP', 'KR', 'AE', 'TC', 'SC')


def _collector(number: Any) -> str:
    return _norm(number).lstrip('0')


def _ygo_number(suffix: str) -> str:
    """'EN001', 'DE001', 'E001' and '001' are the same card of a set."""
    suffix = suffix.upper()
    for region in _YGO_REGIONS:
        if suffix.startswith(region) and len(suffix) > len(region):
            return _collector(suffix[len(region):])
    if len(suffix) > 1 and suffix[0].isalpha() and suffix[1].isdigit():
        return _collector(suffix[1:])
    return _collector(suffix)


@dataclass
class MatchedRow:
    row: ImportRow
    status: str  # 'ok' | 'sin casar' | 'ambigua' | 'error'
    reason: str = ''
    card: Optional[CatalogCard] = None
    printing: Optional[CatalogPrinting] = None


class CatalogIndex:
    """Look-ups over a game's catalog for matching imported rows."""

    def __init__(self, cards: Iterable[CatalogCard], game: str):
        self.game = game
        self.cards: dict[str, CatalogCard] = {}
        self.by_printing: dict[str, tuple] = {}
        self.by_product: dict[str, list] = {}
        self.by_set_number: dict[tuple, list] = {}
        self.by_name: dict[str, list] = {}
        for card in cards:
            self.cards[str(card.card_id)] = card
            for printing in card.printings:
                pair = (card, printing)
                self.by_printing.setdefault(printing.printing_id, pair)
                product = printing.market_ids.get('cardmarket')
                if product:
                    self.by_product.setdefault(str(product), []).append(pair)
                key = self.set_key(printing.set_code, printing.number)
                if key[1]:
                    self.by_set_number.setdefault(key, []).append(pair)
                self.by_name.setdefault(_norm(card.name), []).append(pair)

    def card(self, card_id: Any) -> Optional[CatalogCard]:
        return self.cards.get(str(card_id))

    def set_key(self, set_code: Any, number: Any = None) -> tuple[str, str]:
        code = str(set_code or '').strip()
        if self.game == 'yugioh':
            prefix, _, suffix = code.partition('-')
            return _norm(prefix), _ygo_number(suffix or str(number or ''))
        return _norm(code), _collector(number)

    def same_set(self, printing: CatalogPrinting, set_code: str) -> bool:
        return self.set_key(printing.set_code)[0] == self.set_key(set_code)[0]


def _narrow(candidates: list, row: ImportRow, index: CatalogIndex) -> list:
    """Drop candidates that contradict the row, as long as something is left."""
    tests = []
    if row.name:
        tests.append(lambda pair: _norm(pair[0].name) == _norm(row.name))
    if row.set_code:
        tests.append(lambda pair: index.same_set(pair[1], row.set_code))
    if row.set_name:
        tests.append(lambda pair: _norm(pair[1].set_name) == _norm(row.set_name))
    if row.number and index.game != 'yugioh':
        tests.append(lambda pair: _collector(pair[1].number) == _collector(row.number))
    if row.rarity:
        tests.append(lambda pair: _norm(pair[1].rarity) == _norm(row.rarity))
    for test in tests:
        kept = [pair for pair in candidates if test(pair)]
        if kept:
            candidates = kept
    return candidates


def _match_one(row: ImportRow, index: CatalogIndex) -> MatchedRow:
    if row.error:
        return MatchedRow(row, 'error', row.error)
    if row.printing_id and row.printing_id in index.by_printing:
        card, printing = index.by_printing[row.printing_id]
        return MatchedRow(row, 'ok', '', card, printing)
    if row.id_product and index.by_product.get(row.id_product):
        card, printing = _narrow(index.by_product[row.id_product], row, index)[0]
        return MatchedRow(row, 'ok', '', card, printing)

    candidates: list = []
    if row.set_code:
        key = index.set_key(row.set_code, row.number)
        if key[1]:
            candidates = index.by_set_number.get(key, [])
    if not candidates and row.name:
        named = index.by_name.get(_norm(row.name), [])
        if row.set_code or row.set_name:
            candidates = [pair for pair in named
                          if (row.set_code and index.same_set(pair[1], row.set_code))
                          or (row.set_name and (_norm(pair[1].set_name) == _norm(row.set_name)
                                                # Moxfield puts the set code under "Edition".
                                                or index.same_set(pair[1], row.set_name)))]
        else:
            candidates = named
    if not candidates:
        return MatchedRow(row, 'sin casar', 'No está en el catálogo')
    candidates = _narrow(candidates, row, index)
    if len(candidates) > 1:
        sets = sorted({pair[1].set_code.upper() for pair in candidates})
        hint = ', '.join(sets[:6]) + ('…' if len(sets) > 6 else '')
        return MatchedRow(row, 'ambigua', f'{len(candidates)} impresiones posibles ({hint}): '
                                          'añade set, número o rareza')
    card, printing = candidates[0]
    return MatchedRow(row, 'ok', '', card, printing)


def match_rows(rows: Iterable[ImportRow], index: CatalogIndex) -> list[MatchedRow]:
    return [_match_one(row, index) for row in rows]


# --- Apply -----------------------------------------------------------------

def _finish(printing: CatalogPrinting, foil: bool) -> str:
    wanted = 'foil' if foil else 'nonfoil'
    if not printing.finishes or wanted in printing.finishes:
        return wanted
    if foil and 'etched' in printing.finishes:
        return 'etched'
    return printing.finishes[0]


def _entry_of(variant, condition, language, first_edition, storage) -> Optional[CollectionEntry]:
    key = (condition, language, first_edition, storage)
    return next((e for e in variant.entries
                 if (e.condition, e.language, e.first_edition, e.storage_location) == key), None) if variant else None


def _game_add(collection: GameCollection, card, printing, finish: str, quantity: int, condition: str,
              language: str, first_edition: bool, storage: Optional[str]) -> Optional[CollectionEntry]:
    GameCollectionEditor.apply_change(collection, card, printing, finish, quantity, condition, language,
                                      first_edition, storage)
    owned = next((c for c in collection.cards if c.card_id == card.card_id), None)
    variant = next((v for v in owned.variants if v.printing_id == printing.printing_id and v.finish == finish),
                   None) if owned else None
    return _entry_of(variant, condition, language, first_edition, storage)


def _ygo_add(collection: Collection, api_card, set_code: str, rarity: str, image_id, variant_id: Optional[str],
             quantity: int, condition: str, language: str, first_edition: bool,
             storage: Optional[str]) -> Optional[CollectionEntry]:
    CollectionEditor.apply_change(collection, api_card, set_code, rarity, language, quantity, condition,
                                  first_edition, image_id=image_id, variant_id=variant_id, mode='ADD',
                                  storage_location=storage)
    return CollectionEditor._find_entry(collection, api_card.id, variant_id, set_code, rarity, image_id,
                                        language, condition, first_edition, storage)


def apply_import(collection, matched: Iterable[MatchedRow],
                 api_card_for: Optional[Callable[[int], Any]] = None) -> int:
    """Add every matched row to the collection. Returns the number of cards added."""
    added = 0
    for item in matched:
        if item.status != 'ok':
            continue
        row = item.row
        if isinstance(collection, GameCollection):
            entry = _game_add(collection, item.card, item.printing, _finish(item.printing, row.foil),
                              row.quantity, row.condition, row.language, row.first_edition, row.storage)
            if entry is not None and row.price is not None:
                GameCollectionEditor.set_list_price(entry, row.price)
        else:
            api_card = api_card_for(int(item.card.card_id)) if api_card_for else None
            card_set = next((s for s in api_card.card_sets
                             if (s.variant_id or f'{s.set_code}:{s.set_rarity}') == item.printing.printing_id),
                            None) if api_card else None
            if card_set is None:
                continue
            entry = _ygo_add(collection, api_card, card_set.set_code, card_set.set_rarity, card_set.image_id,
                             card_set.variant_id, row.quantity, row.condition, row.language, row.first_edition,
                             row.storage)
            if entry is not None and row.price is not None:
                CollectionEditor.set_list_price(entry, row.price)
        if entry is not None:
            added += row.quantity
    return added


# --- Merge and edit --------------------------------------------------------

def _add_stack(collection, item: EntryRow, quantity: int, condition: str) -> Optional[CollectionEntry]:
    """Add ``quantity`` cards like ``item`` (same printing, language, edition, place) through the editor."""
    entry = item.entry
    if isinstance(collection, GameCollection):
        card = CatalogCard(game=collection.game, card_id=item.card_id, name=item.name)
        printing = CatalogPrinting(printing_id=item.printing_id, set_code=item.set_code, set_name='',
                                   number=item.number, rarity=item.rarity)
        return _game_add(collection, card, printing, item.finish, quantity, condition, entry.language,
                         entry.first_edition, entry.storage_location)
    stub = SimpleNamespace(id=item.card_id, name=item.name)  # the editor only reads id and name
    return _ygo_add(collection, stub, item.set_code, item.rarity, item.image_id, item.printing_id, quantity,
                    condition, entry.language, entry.first_edition, entry.storage_location)


def _set_price(collection, entry: CollectionEntry, price: Optional[float], locked: Optional[bool] = None) -> bool:
    editor = GameCollectionEditor if isinstance(collection, GameCollection) else CollectionEditor
    return editor.set_list_price(entry, price, locked)


def merge_collections(name: str, sources: list):
    """A new collection with every card of ``sources``. The sources are not changed."""
    if not sources:
        raise ValueError('Elige al menos una colección')
    first = sources[0]
    if any(type(source) is not type(first) for source in sources) or (
            isinstance(first, GameCollection) and any(source.game != first.game for source in sources)):
        raise ValueError('Solo se pueden fusionar colecciones del mismo juego')
    if isinstance(first, GameCollection):
        merged = GameCollection(game=first.game, name=name)
    else:
        merged = Collection(name=name)
        seen = set()
        for source in sources:
            for definition in source.storage_definitions:
                if definition.name not in seen:
                    seen.add(definition.name)
                    merged.storage_definitions.append(definition.model_copy(deep=True))
    for source in sources:
        for item in list_entries(source):
            entry = _add_stack(merged, item, item.entry.quantity, item.entry.condition)
            if entry is not None and entry.list_price is None and item.entry.list_price is not None:
                _set_price(merged, entry, item.entry.list_price, item.entry.price_locked)
    return merged


def edit_entry(collection, item: EntryRow, quantity: int, condition: str, price: Optional[float]) -> bool:
    """Change one stack's quantity, condition and sale price. True when something changed."""
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
        raise ValueError('Cantidad no válida')
    if condition not in CARD_CONDITIONS:
        raise ValueError('Estado no válido')
    if price is not None and not (0 <= price < float('inf')):
        raise ValueError('Precio no válido')
    entry = item.entry
    new_price = None if price is None else round(float(price), 2)
    if quantity == entry.quantity and condition == entry.condition and new_price == entry.list_price:
        return False
    if quantity == 0:
        _add_stack(collection, item, -entry.quantity, entry.condition)
    elif condition == entry.condition:
        if quantity != entry.quantity:
            _add_stack(collection, item, quantity - entry.quantity, condition)
        _set_price(collection, entry, new_price)
    else:
        locked, unpriced = entry.price_locked, entry.list_price is None
        old_quantity, old_condition = entry.quantity, entry.condition
        target = _add_stack(collection, item, quantity, condition)  # first, so the printing keeps its place
        _add_stack(collection, item, -old_quantity, old_condition)
        # An unpriced stack that joins a priced one takes that price instead of wiping it.
        if target is not None and not (unpriced and new_price is None and target.list_price is not None):
            _set_price(collection, target, new_price, True if locked else None)
    return True


def entry_key(item: EntryRow) -> tuple:
    """What tells one stack from every other stack of its collection."""
    entry = item.entry
    return (str(item.card_id), item.printing_id, item.finish, entry.condition, entry.language,
            bool(entry.first_edition), entry.storage_location)


def bulk_edit(collection, keys: Iterable[tuple], quantity: Optional[int] = None, condition: Optional[str] = None,
              price: Optional[float] = None, clear_price: bool = False) -> tuple[int, int]:
    """Apply one change to several stacks. ``None`` leaves that field alone.
    Returns (stacks changed, stacks no longer there)."""
    changed = missing = 0
    by_key = {entry_key(item): item for item in list_entries(collection)}
    for key in keys:
        item = by_key.pop(tuple(key), None)
        if item is None:
            missing += 1
            continue
        entry = item.entry
        new_price = None if clear_price else (entry.list_price if price is None else price)
        if edit_entry(collection, item, entry.quantity if quantity is None else quantity,
                      condition or entry.condition, new_price):
            changed += 1
    return changed, missing
