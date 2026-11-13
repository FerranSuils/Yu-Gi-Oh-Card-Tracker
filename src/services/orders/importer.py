"""Orders that arrive from outside (a file, an online shop): read them, find their piles, write them down."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from src.core.order_models import Address, Order, OrderLine
from src.core.sales_models import OutOfStock, SaleLine
from src.services.csv_suite import MAX_QUANTITY, _condition, _LANGUAGES, _norm, _number, read_table
from src.services.orders.book import OrderBook, OrderError
from src.services.orders.sku import sku_of
from src.services.sales.inventory import StockUnreadable, line_key
from src.services.shop.files import BrokenFile

logger = logging.getLogger(__name__)


@dataclass
class Article:
    """One thing sold outside, in the words of whoever sold it."""
    name: str
    set_code: str = ''
    condition: str = ''
    language: str = ''
    quantity: int = 1
    unit_cents: int = 0
    sku: str = ''
    rarity: str = ''


@dataclass
class Incoming:
    external_id: str = ''
    channel: str = 'otro'
    customer_name: str = ''
    email: str = ''
    address: Address = field(default_factory=Address)
    shipping_cents: int = 0
    currency: str = ''
    articles: List[Article] = field(default_factory=list)
    total_cents: int = 0      # what the buyer paid there, discounts and taxes in; 0 when nobody said
    made_up: bool = False     # the reference is ours: the file brought none


@dataclass
class Report:
    created: List[Order] = field(default_factory=list)
    skipped: int = 0          # already in the book
    unlinked: int = 0         # lines that found no pile
    failed: List[str] = field(default_factory=list)


# Field -> header names it is known by, best first (compared with _norm).
_ALIASES = {
    'order': ('orderid', 'idorder', 'order', 'ordernumber', 'pedido', 'numerodepedido', 'reference', 'referencia'),
    'card': ('lineitemname', 'card', 'cardname', 'article', 'articulo', 'product', 'productname', 'item', 'carta',
             'producto'),
    'description': ('description', 'descripcion', 'articles', 'articulos'),
    'buyer': ('shippingname', 'buyer', 'customer', 'cliente', 'comprador', 'billingname', 'username'),
    'email': ('email', 'correo', 'buyeremail'),
    'line1': ('shippingaddress1', 'address', 'address1', 'street', 'direccion', 'calle', 'shippingstreet'),
    'line2': ('shippingaddress2', 'address2', 'direccion2'),
    'postcode': ('shippingzip', 'zip', 'postcode', 'postalcode', 'cp', 'codigopostal'),
    'city': ('shippingcity', 'city', 'ciudad', 'poblacion'),
    'region': ('shippingprovince', 'state', 'province', 'region', 'provincia'),
    'country': ('shippingcountry', 'country', 'pais'),
    'quantity': ('lineitemquantity', 'quantity', 'qty', 'cantidad', 'count', 'amount'),
    'set_code': ('setcode', 'set', 'expansion', 'edition', 'coleccion', 'code'),
    'condition': ('condition', 'estado', 'cond'),
    'language': ('language', 'idioma', 'lang'),
    'rarity': ('rarity', 'rareza'),
    'price': ('lineitemprice', 'unitprice', 'price', 'precio'),
    'shipping': ('shipmentcosts', 'shippingcost', 'shipping', 'envio', 'gastosdeenvio'),
    'sku': ('lineitemsku', 'sku'),
    'currency': ('currency', 'moneda'),
    'total': ('totalvalue', 'ordertotal', 'grandtotal', 'totalpedido', 'importetotal'),
}
_PIECE = re.compile(r'^\s*(\d{1,6})\s*x?\s+(.+?)\s*$', re.IGNORECASE)
_NAME_SET = re.compile(r'^(.*\S)\s+\(([^()]*)\)$')
_PRICE = re.compile(r'^\s*([\d.,]+)\s*(?:€|EUR|USD|GBP|\$|£)?\s*$', re.IGNORECASE)


def _columns(headers: Iterable[str]) -> Dict[str, str]:
    known = {_norm(header): header for header in headers if header}
    columns = {name: next((known[alias] for alias in aliases if alias in known), '')
               for name, aliases in _ALIASES.items()}
    if 'name' in known:
        # "Name" is the card in a plain list, the buyer next to a description, the order next to line items.
        if not columns['card'] and not columns['description']:
            columns['card'] = known['name']
        elif columns['card'] and not columns['order']:
            columns['order'] = known['name']
        elif not columns['card']:
            columns['name'] = known['name']
    if not columns['total'] and 'total' in known and ('lineitemname' in known or not columns['card']):
        # A bare "Total" is the order's in a file of whole orders; in a plain list it is the row's.
        columns['total'] = known['total']
    return columns


def _cents(text: str) -> int:
    try:
        return int(round(_number(text) * 100)) if text.strip() else 0
    except ValueError:
        return 0


def _language(text: str) -> str:
    return _LANGUAGES.get(_norm(text), '')


def _split_name(text: str) -> tuple[str, str]:
    match = _NAME_SET.match(text.strip())
    return (match.group(1), match.group(2).strip()) if match else (text.strip(), '')


def _from_description(text: str) -> List[Article]:
    """'2x Name (Set) - 001 - Rare - NM - English - 2,00 EUR | 1x …' → articles; odd pieces stay as text."""
    articles = []
    for piece in text.split(' | '):
        piece = piece.strip()
        if not piece:
            continue
        count = _PIECE.match(piece)
        quantity, rest = (int(count.group(1)), count.group(2)) if count else (1, piece)
        if not 1 <= quantity <= MAX_QUANTITY:
            quantity, rest = 1, piece
        parts = rest.split(' - ')
        name, set_code = _split_name(parts[0])
        article = Article(name=name, set_code=set_code, quantity=quantity)
        for part in parts[1:]:
            price = _PRICE.match(part)
            if _language(part):
                article.language = _language(part)
            elif _condition(part)[0] and len(_norm(part)) <= 16:
                article.condition = _condition(part)[0]
            elif price and re.search(r'[.,]\d{2}\b|€|EUR|USD|GBP|\$|£', part, re.IGNORECASE):
                article.unit_cents = _cents(price.group(1))
            elif not article.rarity and part.strip() and not any(sign.isdigit() for sign in part):
                article.rarity = part.strip()[:40]
        articles.append(article)
    return articles


def _fingerprint(row: dict, seen: Dict[str, int]) -> str:
    """A reference for a row that brings none. The same file read again gives the same ones, so it does not
    enter twice; two equal rows in one file are told apart by their turn."""
    mark = '\x1f'.join(f'{key}={str(value or "").strip()}'
                       for key, value in sorted(row.items(), key=lambda pair: str(pair[0])))
    seen[mark] = seen.get(mark, 0) + 1
    return 'f-' + hashlib.sha256(f'{mark}\x1e{seen[mark]}'.encode('utf-8')).hexdigest()[:16]


def parse_orders(data: bytes, channel: str = 'otro') -> List[Incoming]:
    """The orders in a CSV: one row per article, or one row per order with a Description of its articles."""
    try:
        headers, rows = read_table(data)
    except ValueError as error:
        raise OrderError(str(error)) from None
    columns = _columns(headers)
    if not columns['card'] and not columns['description']:
        raise OrderError('No encuentro la columna con el nombre de la carta (Card, Artículo o Description).')

    def cell(row: dict, name: str) -> str:
        return row.get(columns.get(name) or '', '').strip() if columns.get(name) else ''

    orders: List[Incoming] = []
    by_reference: Dict[str, Incoming] = {}
    seen: Dict[str, int] = {}
    for number, row in enumerate(rows, start=2):
        reference = cell(row, 'order')
        order = by_reference.get(reference) if reference else None
        if order is None:
            buyer = cell(row, 'buyer') if columns['card'] else (cell(row, 'name') or cell(row, 'buyer'))
            order = Incoming(
                external_id=reference or _fingerprint(row, seen), made_up=not reference,
                total_cents=_cents(cell(row, 'total')),
                channel=channel, customer_name=buyer, email=cell(row, 'email'),
                address=Address(name=buyer, line1=cell(row, 'line1'), line2=cell(row, 'line2'),
                                postcode=cell(row, 'postcode'), city=cell(row, 'city'), region=cell(row, 'region'),
                                country=cell(row, 'country')),
                shipping_cents=_cents(cell(row, 'shipping')), currency=cell(row, 'currency').upper()[:3])
            orders.append(order)
            if reference:
                by_reference[reference] = order
        if columns['card']:
            name = cell(row, 'card')
            if not name:
                continue
            amount = cell(row, 'quantity') or '1'
            if not amount.isdigit() or not 1 <= int(amount) <= MAX_QUANTITY:
                raise OrderError(f'Fila {number}: la cantidad «{amount[:20]}» no es un número de copias.')
            order.articles.append(Article(
                name=name, set_code=cell(row, 'set_code'), condition=_condition(cell(row, 'condition'))[0] or '',
                language=_language(cell(row, 'language')), quantity=int(amount),
                unit_cents=_cents(cell(row, 'price')), sku=cell(row, 'sku'), rarity=cell(row, 'rarity')[:40]))
        else:
            order.articles.extend(_from_description(cell(row, 'description')))
    return orders


# --- linking -------------------------------------------------------------------------------

def _set_matches(item: SaleLine, theirs: str) -> bool:
    return _norm(item.set_code) == _norm(theirs) or _norm(item.set_code.split('-')[0]) == _norm(theirs)


def _printings(items: List[SaleLine]) -> set:
    return {(item.game, item.card_id, item.variant_id, item.finish) for item in items}


def _candidates(article: Article, items: List[SaleLine]) -> List[SaleLine]:
    if article.sku:
        return [item for item in items if sku_of(item) == article.sku.strip().upper()]
    name = _norm(article.name)
    found = [item for item in items if _norm(item.name) == name] if name else []
    if article.set_code:
        exact = [item for item in found if _set_matches(item, article.set_code)]
        if exact:
            found = exact
        elif len(_printings(found)) != 1:
            return []   # the set is written some other way and several printings could be meant
    if article.rarity:
        exact = [item for item in found if _norm(item.rarity) == _norm(article.rarity)]
        if exact:
            found = exact
    if len(_printings(found)) > 1:
        return []   # several printings fit and nothing says which: a person chooses, not the first in the list
    if article.condition:
        found = [item for item in found if item.condition == article.condition]
    if article.language:
        found = [item for item in found if item.language == article.language]
    return found


def link(articles: Iterable[Article], items: List[SaleLine],
         available: Optional[Dict[tuple, int]] = None) -> List[OrderLine]:
    """A line per article: on its pile when one fits and holds enough copies, otherwise unlinked text."""
    left = available if available is not None else {}
    for item in items:
        left.setdefault(line_key(item), item.quantity)
    lines = []
    for article in articles:
        pile = next((item for item in _candidates(article, items) if left[line_key(item)] >= article.quantity),
                    None)
        if pile is None:
            title = f'{article.name} ({article.set_code})' if article.set_code else article.name
            lines.append(OrderLine(kind='custom', name=title[:200] or 'Artículo', quantity=article.quantity,
                                   unit_cents=article.unit_cents, unlinked=True, sku=article.sku[:60],
                                   rarity=article.rarity[:40],
                                   condition=article.condition or 'Near Mint', language=article.language or 'EN'))
            continue
        left[line_key(pile)] -= article.quantity
        lines.append(OrderLine(**{**pile.model_dump(), 'quantity': article.quantity,
                                  'unit_cents': article.unit_cents or pile.unit_cents, 'sku': sku_of(pile)}))
    return lines


def shelves_or_refuse(inventory, games: Iterable[str]) -> List[SaleLine]:
    """What is on the shelves, for linking orders to it; all of it or nothing."""
    try:
        return inventory.items(games, strict=True)
    except StockUnreadable as error:
        raise OrderError(f'No se pudo leer la colección {error}, así que no se ha importado nada. Revísala y '
                         'vuelve a intentarlo.') from None


def bring_in(book: OrderBook, incoming: Iterable[Incoming], items: List[SaleLine],
             currency: str = 'EUR') -> Report:
    """Writes down every order not yet in the book. One order failing does not stop the others."""
    report = Report()
    available: Dict[tuple, int] = {}
    for order in incoming:
        tag = ('' if order.made_up else order.external_id) or order.customer_name or 'sin referencia'
        if order.external_id and book.has(order.channel, order.external_id):
            report.skipped += 1
            continue
        if not order.articles:
            report.failed.append(f'{tag}: no trae artículos.')
            continue
        tentative = dict(available)
        lines = link(order.articles, items, tentative)
        try:
            created = book.create(
                lines, channel=order.channel, external_id=order.external_id, customer_name=order.customer_name,
                email=order.email, address=order.address, shipping_cents=order.shipping_cents,
                currency=order.currency or currency, paid=True, charged_cents=order.total_cents)
        except (OrderError, OutOfStock) as error:
            report.failed.append(f'{tag}: {error}')
            continue
        except (OSError, BrokenFile) as error:   # nothing was written and its cards are back on the shelf
            logger.error('Pedidos: no se pudo guardar un pedido de %s: %s', order.channel, type(error).__name__)
            report.failed.append(f'{tag}: no se pudo guardar. Vuelve a intentarlo.')
            continue
        available.clear()
        available.update(tentative)
        report.created.append(created)
        report.unlinked += created.unlinked
    return report
