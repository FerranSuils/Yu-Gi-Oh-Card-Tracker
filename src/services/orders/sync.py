"""The round trip with a connected online shop: its paid orders come into the book, and what is left on
the shelves goes back as stock. Orders first, so that the stock sent already counts them."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from src.core.sales_models import SaleLine
from src.services.orders.book import OrderBook
from src.services.orders.channels import (CHANNELS, ChannelError, ChannelSettings, check_shopify,
                                          check_woocommerce)
from src.services.orders.importer import Report, bring_in
from src.services.orders.sku import sku_of
from src.services.sales.inventory import StockUnreadable

_running: Dict[tuple, threading.Lock] = {}
_running_guard = threading.Lock()


@dataclass
class SyncReport:
    orders: Report = field(default_factory=Report)
    updated: int = 0                # products whose stock changed in the shop
    missing: int = 0                # piles with stock the shop has no product for
    push_error: str = ''            # why the stock could not be sent, when it could not
    pushed: Dict[str, int] = field(default_factory=dict)   # SKU → quantity the shop now has from us
    truncated: bool = False         # the shop has more orders waiting than one round reads


def sync(book: OrderBook, client, stock: Callable[[], List[SaleLine]], currency: str,
         pushed: Dict[str, int]) -> SyncReport:
    """Brings the shop's orders in and sends back only the stock that changed since `pushed`.

    If sending fails the orders stay written down (they are never entered twice) and `pushed` comes back
    untouched, so the next round sends the same again.

    A collection that cannot be read stops the round before anything moves: taking it for empty shelves
    would leave orders without their piles and tell the shop that everything is sold out."""
    try:
        shelves = stock()
    except StockUnreadable as error:
        raise ChannelError(f'No se pudo leer una colección ({error}), así que no se ha tocado nada: ni pedidos '
                           'ni stock. Revísala y vuelve a sincronizar.') from None
    incoming = client.orders()
    report = SyncReport(orders=bring_in(book, incoming, shelves, currency), pushed=dict(pushed),
                        truncated=bool(getattr(client, 'truncated', False)))
    now: Dict[str, int] = {}
    try:
        left = stock()
    except StockUnreadable as error:
        report.push_error = f'no se pudo leer la colección {error}.'
        return report
    for pile in left:
        now[sku_of(pile)] = now.get(sku_of(pile), 0) + pile.quantity
    wanted = {sku: count for sku, count in now.items() if pushed.get(sku) != count}
    wanted.update({sku: 0 for sku, count in pushed.items() if sku not in now and count != 0})
    try:
        answer = client.push(wanted)
    except ChannelError as error:
        report.push_error = str(error)
        return report
    for sku in answer.updated:
        if sku in wanted:
            report.pushed[sku] = wanted[sku]
            report.updated += 1
    for sku in answer.missing:
        report.pushed.pop(sku, None)
        if wanted.get(sku):
            report.missing += 1
    report.pushed = {sku: count for sku, count in report.pushed.items() if count or sku in now}
    return report


def due_channels(settings: ChannelSettings) -> List[str]:
    """The connected shops whose last round is old enough to go again on their own."""
    connected = settings.summary()
    return [channel for channel in CHANNELS if channel in connected and settings.due(channel)]


def _lock_for(root: str, channel: str) -> threading.Lock:
    key = (os.path.normcase(os.path.abspath(root)), channel)
    with _running_guard:
        return _running.setdefault(key, threading.Lock())


def sync_channel(settings: ChannelSettings, channel: str, book: OrderBook, stock: Callable[[], List[SaleLine]],
                 currency: str, client=None, http=None) -> SyncReport:
    """One round with a stored connection; remembers what was sent and when. Never two at once."""
    client = client if settings.secrets(channel) and client is not None else settings.client(channel, http=http)
    if client is None:
        raise ChannelError('Esa tienda no está conectada. Conéctala en Ajustes.')
    running = _lock_for(settings.root, channel)
    if not running.acquire(blocking=False):
        raise ChannelError('Ya se está sincronizando esa tienda. Espera a que termine.')
    try:
        report = sync(book, client, stock, currency, settings.pushed(channel))
        settings.remember(channel, report.pushed)
        if not report.push_error:
            settings.stamp(channel)
        return report
    finally:
        running.release()


def connect(settings: ChannelSettings, channel: str, *values: str, http=None) -> str:
    """Saves a connection only after the shop has answered with it. Returns how the shop calls itself."""
    if channel not in CHANNELS:
        raise ChannelError('No conozco ese tipo de tienda.')
    if channel == 'shopify':
        if len(values) != 2:
            raise ChannelError('Hacen falta el dominio y el token.')
        from src.services.orders.shopify import ShopifyClient

        domain, token = check_shopify(*values)
        name = ShopifyClient(domain, token, http=http).ping()
        settings.save_shopify(domain, token)
        return name
    if len(values) != 3:
        raise ChannelError('Hacen falta la dirección y las dos claves.')
    from src.services.orders.woocommerce import WooClient

    url, key, secret = check_woocommerce(*values, resolve=settings.resolve)
    name = WooClient(url, key, secret, http=http, resolve=settings.resolve).ping()
    settings.save_woocommerce(url, key, secret)
    return name
