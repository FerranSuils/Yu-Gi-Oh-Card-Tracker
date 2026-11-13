"""Figures for a period, from the three books: counter sales, orders to ship and purchases."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from src.core.order_models import CHANNEL_LABELS, Order
from src.core.sales_models import Sale, SaleLine
from src.core.shop_models import Purchase
from src.services.sales.store import _amount, _text

COUNTER = 'Mostrador'
TOP = 20
NOT_INCOME = ('new', 'cancelled', 'returned')
PERIODS = {'hoy': 'Hoy', '7d': '7 días', '30d': '30 días', 'mes': 'Este mes', 'mes_pasado': 'Mes pasado',
           'ano': 'Este año'}


@dataclass
class TopCard:
    name: str
    set_code: str
    units: int = 0
    cents: int = 0


@dataclass
class Report:
    start: date
    end: date
    revenue_cents: int = 0
    count: int = 0
    units: int = 0
    purchases_cents: int = 0
    by_day: List[Tuple[str, int]] = field(default_factory=list)
    by_channel: Dict[str, int] = field(default_factory=dict)
    by_method: Dict[str, int] = field(default_factory=dict)
    top: List[TopCard] = field(default_factory=list)
    foreign: Dict[str, int] = field(default_factory=dict)   # orders charged in another currency, never added

    @property
    def average_cents(self) -> int:
        return round(self.revenue_cents / self.count) if self.count else 0


def period(name: str, today: date) -> Tuple[date, date]:
    """First and last day of a named period. An unknown name means this month."""
    if name == 'hoy':
        return today, today
    if name == '7d':
        return today - timedelta(days=6), today
    if name == '30d':
        return today - timedelta(days=29), today
    if name == 'mes_pasado':
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if name == 'ano':
        return today.replace(month=1, day=1), today
    return today.replace(day=1), today


def _day(stamp: Optional[str], tz) -> Optional[date]:
    """The local day of a stored moment, or None when it cannot be read."""
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return (moment.astimezone(tz) if moment.tzinfo else moment).date()


def build(sales: Iterable[Sale], orders: Iterable[Order], purchases: Iterable[Purchase], start: date, end: date,
          tz=None, currency: Optional[str] = None) -> Report:
    """`tz=None` reads the moments in the machine's own time zone. With `currency`, orders charged in another
    one are set apart in `foreign` instead of being added as if they were the shop's money."""
    if start > end:
        start, end = end, start
    report = Report(start=start, end=end)
    days: Dict[str, int] = {}
    cards: Dict[tuple, TopCard] = {}

    def earn(day: date, cents: int, channel: str, lines) -> None:
        report.revenue_cents += cents
        report.count += 1
        days[day.isoformat()] = days.get(day.isoformat(), 0) + cents
        report.by_channel[channel] = report.by_channel.get(channel, 0) + cents
        for line in lines:
            key = (line.name.casefold(), line.set_code.casefold())
            card = cards.setdefault(key, TopCard(line.name, line.set_code))
            card.units += line.quantity
            card.cents += line.total_cents
            report.units += line.quantity

    for sale in sales:
        day = _day(sale.paid_at, tz)
        if sale.status == 'paid' and day and start <= day <= end:
            earn(day, sale.total_cents, COUNTER, sale.lines)
            report.by_method[sale.method] = report.by_method.get(sale.method, 0) + sale.total_cents
    for order in orders:
        day = _day(order.paid_at or order.created_at, tz)
        if order.status not in NOT_INCOME and day and start <= day <= end:
            theirs = (order.currency or '').upper()
            if currency and theirs and theirs != currency.upper():
                report.foreign[theirs] = report.foreign.get(theirs, 0) + order.income_cents
                continue
            earn(day, order.income_cents, CHANNEL_LABELS.get(order.channel, order.channel), order.lines)
    for purchase in purchases:
        day = _day(purchase.created_at, tz)
        if purchase.status == 'done' and day and start <= day <= end:
            report.purchases_cents += purchase.total_cents
    report.by_day = sorted(days.items())
    report.top = sorted(cards.values(), key=lambda c: (-c.units, -c.cents, c.name.casefold()))[:TOP]
    return report


def stock_value(items: Iterable[SaleLine]) -> Tuple[int, int]:
    """Copies on the shelves and what they add up to at their sale price."""
    items = list(items)
    return sum(i.quantity for i in items), sum(i.total_cents for i in items)


def report_csv(report: Report) -> bytes:
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, delimiter=';', lineterminator='\r\n')
    writer.writerow(['Día', 'Ingresos'])
    for day, cents in report.by_day:
        writer.writerow([day, _amount(cents)])
    writer.writerow([])
    writer.writerow(['Carta', 'Set', 'Unidades', 'Ingresos'])
    for card in report.top:
        writer.writerow([_text(card.name), _text(card.set_code), card.units, _amount(card.cents)])
    if report.foreign:
        writer.writerow([])
        writer.writerow(['Pedidos en otra moneda (no sumados)', 'Importe'])
        for code, cents in sorted(report.foreign.items()):
            writer.writerow([_text(code), _amount(cents)])
    return buffer.getvalue().encode('utf-8-sig')


def gather(desk, start: date, end: date, currency: Optional[str] = None) -> Report:
    """The report of one shop: reads every month of sales the period touches, plus orders and purchases."""
    if start > end:
        start, end = end, start
    wanted = {(start - timedelta(days=1)).strftime('%Y-%m'), (end + timedelta(days=1)).strftime('%Y-%m')}
    months = [m for m in desk.sales.months() if min(wanted) <= m <= max(wanted)]
    sales = [sale for month in months for sale in desk.sales.month(month, strict=True)]
    return build(sales, desk.dispatch.all(), desk.purchases.all(), start, end, currency=currency)
