"""What a sale looks like on paper and in the day's takings."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Dict, List, Optional

from src.core.sales_models import METHOD_LABELS, STATUS_LABELS, Sale, format_money


def local_time(iso: Optional[str], utc_offset_hours: Optional[float] = None) -> Optional[datetime]:
    """A stored UTC moment in the shop's clock (the server's, unless an offset is given)."""
    if not iso:
        return None
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if utc_offset_hours is None:
        return moment.astimezone()
    return moment.astimezone(timezone(timedelta(hours=utc_offset_hours)))


def when_text(iso: Optional[str], utc_offset_hours: Optional[float] = None) -> str:
    moment = local_time(iso, utc_offset_hours)
    return moment.strftime('%d/%m/%Y %H:%M') if moment else ''


# --- receipt -----------------------------------------------------------------------------------

def receipt_html(sale: Sale, shop, utc_offset_hours: Optional[float] = None) -> str:
    """The printable ticket. Every text is escaped; nothing about Stripe's session is printed."""
    def money(cents: int) -> str:
        return escape(format_money(cents, sale.currency))

    head = [f'<div class="oy-receipt-shop">{escape(shop.name or "Ticket de venta")}</div>']
    place = ', '.join(part for part in (shop.address, shop.city, shop.country) if part)
    for text in (place, shop.email):
        if text:
            head.append(f'<div class="oy-receipt-small">{escape(text)}</div>')
    rows = []
    for line in sale.lines:
        detail = ' · '.join(part for part in (line.set_code, line.rarity if line.kind == 'stock' else '') if part)
        rows.append(
            '<tr><td>'
            f'{escape(line.name)}'
            + (f'<div class="oy-receipt-small">{escape(detail)}</div>' if detail else '')
            + f'</td><td class="oy-receipt-num">{line.quantity} × {money(line.unit_cents)}</td>'
            f'<td class="oy-receipt-num">{money(line.total_cents)}</td></tr>')
    totals = [('Subtotal', money(sale.subtotal_cents))]
    if sale.discount_cents:
        label = 'Descuento'
        if sale.discount.kind == 'percent':
            label += f' ({sale.discount.value:g} %)'
        totals.append((label, '−' + money(sale.discount_cents)))
    totals.append(('<b>Total</b>', f'<b>{money(sale.total_cents)}</b>'))
    totals.append(('Forma de cobro', escape(METHOD_LABELS.get(sale.method, sale.method))))
    if sale.method == 'cash' and sale.received_cents is not None:
        totals.append(('Entregado', money(sale.received_cents)))
        totals.append(('Cambio', money(sale.change_cents or 0)))
    state = ''
    if sale.status != 'paid':
        state = f'<div class="oy-receipt-state">{escape(STATUS_LABELS.get(sale.status, sale.status))}'
        if sale.status == 'refunded' and sale.refunded_at:
            state += f' · {escape(when_text(sale.refunded_at, utc_offset_hours))}'
        state += '</div>'
    return (
        '<div class="oy-receipt">' + ''.join(head)
        + f'<div class="oy-receipt-meta">Ticket {escape(sale.label)} · '
          f'{escape(when_text(sale.paid_at or sale.created_at, utc_offset_hours))}</div>'
        + state
        + '<table class="oy-receipt-lines">' + ''.join(rows) + '</table>'
        + '<table class="oy-receipt-totals">'
        + ''.join(f'<tr><td>{label}</td><td class="oy-receipt-num">{value}</td></tr>' for label, value in totals)
        + '</table>'
        + (f'<div class="oy-receipt-small">{escape(sale.note)}</div>' if sale.note else '')
        + '<div class="oy-receipt-small oy-receipt-thanks">Gracias por tu compra</div></div>')


def qr_svg(url: str, scale: int = 5) -> str:
    """A QR of a Stripe payment link, as inline SVG."""
    import segno

    if not url.startswith('https://') or not url.split('/')[2].endswith('stripe.com'):
        raise ValueError('Solo se generan QR de enlaces de pago de Stripe')
    buffer = io.BytesIO()
    segno.make(url, error='m').save(buffer, kind='svg', scale=scale, border=2, xmldecl=False, svgns=True,
                                    dark='#000', light='#fff', nl=False)
    return buffer.getvalue().decode('utf-8')


# --- takings -----------------------------------------------------------------------------------

@dataclass
class Day:
    date: str  # AAAA-MM-DD in the shop's clock
    sales: List[Sale] = field(default_factory=list)
    total_cents: int = 0
    count: int = 0
    by_method: Dict[str, int] = field(default_factory=dict)


def days(sales: List[Sale], utc_offset_hours: Optional[float] = None) -> List[Day]:
    """Sales grouped by day, newest first. Only money that stayed in the till is added up."""
    found: Dict[str, Day] = {}
    for sale in sales:
        moment = local_time(sale.created_at, utc_offset_hours)
        date = moment.strftime('%Y-%m-%d') if moment else sale.created_at[:10]
        day = found.setdefault(date, Day(date))
        day.sales.append(sale)
        if sale.status == 'paid':
            day.total_cents += sale.total_cents
            day.count += 1
            day.by_method[sale.method] = day.by_method.get(sale.method, 0) + sale.total_cents
    return [found[date] for date in sorted(found, reverse=True)]
