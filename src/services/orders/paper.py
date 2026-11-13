"""What an order looks like on the desk and on paper: its next steps, the delivery note, the pick sheet."""

from __future__ import annotations

from html import escape
from typing import Iterable, List, Optional

from src.core.order_models import CHANNEL_LABELS, ORDER_LABELS, OPEN_STATUSES, Order
from src.core.sales_models import format_money
from src.services.orders.book import Pick
from src.services.sales.receipt import when_text

VIEWS = {'open': 'Por hacer', 'shipped': 'En camino', 'closed': 'Cerrados', 'all': 'Todos'}
_VIEW_STATUSES = {'open': OPEN_STATUSES, 'shipped': ('shipped',), 'closed': ('delivered', 'cancelled', 'returned')}
_NEXT = {
    'new': ['paid', 'cancel'],
    'paid': ['packed', 'ship', 'cancel'],
    'packed': ['ship', 'cancel'],
    'shipped': ['delivered', 'return'],
    'delivered': ['return'],
}


def next_steps(order: Order) -> List[str]:
    """What the desk may do with this order now, most likely first."""
    return list(_NEXT.get(order.status, ()))


def in_view(orders: Iterable[Order], view: str) -> List[Order]:
    statuses = _VIEW_STATUSES.get(view)
    return [order for order in orders if statuses is None or order.status in statuses]


def matching(orders: Iterable[Order], text: str) -> List[Order]:
    """Orders whose number, outside reference, buyer or cards contain the text."""
    needle = text.strip().lower()
    if not needle:
        return list(orders)
    return [order for order in orders if any(needle in field.lower() for field in (
        order.label, order.external_id, order.customer_name, order.email, order.tracking,
        *(line.name for line in order.lines)))]


def slip_html(order: Order, shop, utc_offset_hours: Optional[float] = None) -> str:
    """The printable delivery note. Every text is escaped."""
    def money(cents: int) -> str:
        return escape(format_money(cents, order.currency))

    head = [f'<div class="oy-slip-shop">{escape(shop.name or "Albarán")}</div>']
    place = ', '.join(part for part in (shop.address, shop.city, shop.country) if part)
    for text in (place, shop.email):
        if text:
            head.append(f'<div class="oy-slip-small">{escape(text)}</div>')
    reference = CHANNEL_LABELS.get(order.channel, order.channel)
    if order.external_id:
        reference += f' {order.external_id}'
    meta = ' · '.join(part for part in (
        f'Pedido {order.label}', reference, when_text(order.created_at, utc_offset_hours),
        ORDER_LABELS.get(order.status, order.status)) if part)
    to = order.address.lines() or ([order.customer_name] if order.customer_name else [])
    rows = []
    for line in order.lines:
        detail = ' · '.join(part for part in (
            line.set_code, line.rarity, line.condition if line.kind == 'stock' else '',
            line.language if line.kind == 'stock' else '', '1.ª edición' if line.first_edition else '') if part)
        rows.append(
            f'<tr><td class="oy-slip-num">{line.quantity}</td><td>{escape(line.name)}'
            + (f'<div class="oy-slip-small">{escape(detail)}</div>' if detail else '')
            + f'</td><td class="oy-slip-num">{money(line.unit_cents)}</td>'
            f'<td class="oy-slip-num">{money(line.total_cents)}</td></tr>')
    travel = ' · '.join(part for part in (order.shipping_name, order.carrier
                                          if order.carrier != order.shipping_name else '', order.tracking) if part)
    totals = [('Artículos', money(order.goods_cents)), (f'Envío{" (" + escape(travel) + ")" if travel else ""}',
                                                        money(order.shipping_cents)),
              ('<b>Total</b>', f'<b>{money(order.total_cents)}</b>')]
    if order.charged_cents and order.charged_cents != order.total_cents:   # discounts and taxes live there
        totals.append(('Cobrado en la tienda', money(order.charged_cents)))
    return (
        '<div class="oy-slip">' + ''.join(head)
        + f'<div class="oy-slip-meta">{escape(meta)}</div>'
        + ('<div class="oy-slip-to"><div class="oy-slip-small">Enviar a</div>'
           + ''.join(f'<div>{escape(row)}</div>' for row in to) + '</div>' if to else '')
        + '<table class="oy-slip-lines"><tr><th>Uds.</th><th>Artículo</th><th>Precio</th><th>Importe</th></tr>'
        + ''.join(rows) + '</table>'
        + '<table class="oy-slip-totals">'
        + ''.join(f'<tr><td>{label}</td><td class="oy-slip-num">{value}</td></tr>' for label, value in totals)
        + '</table>'
        + (f'<div class="oy-slip-small">{escape(order.note)}</div>' if order.note else '')
        + '</div>')


def picks_html(picks: List[Pick]) -> str:
    """The printable sheet of piles to visit. Every text is escaped."""
    if not picks:
        return '<div class="oy-slip"><div class="oy-slip-meta">No hay cartas que recoger.</div></div>'
    rows = []
    for pick in picks:
        detail = ' · '.join(part for part in (
            pick.set_code, pick.rarity, pick.condition, pick.language,
            '1.ª edición' if pick.first_edition else '') if part)
        place = ' · '.join(part for part in (
            pick.storage_location or 'Sin ubicación', pick.collection.rsplit('.', 1)[0]) if part)
        rows.append(
            f'<tr><td class="oy-slip-num"><b>{pick.quantity}</b></td><td>{escape(pick.name)}'
            f'<div class="oy-slip-small">{escape(detail)}</div></td><td>{escape(place)}</td>'
            f'<td class="oy-slip-small">{escape(", ".join(pick.orders))}</td></tr>')
    units = sum(pick.quantity for pick in picks)
    return (
        '<div class="oy-slip"><div class="oy-slip-shop">Hoja de recogida</div>'
        f'<div class="oy-slip-meta">{units} cartas en {len(picks)} montones</div>'
        '<table class="oy-slip-lines"><tr><th>Uds.</th><th>Carta</th><th>Dónde</th><th>Pedidos</th></tr>'
        + ''.join(rows) + '</table></div>')
