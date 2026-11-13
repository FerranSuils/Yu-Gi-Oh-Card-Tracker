"""Bits the shop pages share: styles, messages a person may read, dates and names."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from src.core.sales_models import OutOfStock, format_money, to_cents
from src.core.shop_models import Customer
from src.services.sales.checkout import SaleError
from src.services.orders.book import OrderError
from src.services.shop.buylist import BuyError
from src.services.shop.consignment import ConsignmentError
from src.services.events.store import EventError
from src.services.shop.customers import CustomerError
from src.services.orders.channels import ChannelError
from src.services.shop.kiosk import KioskError

logger = logging.getLogger(__name__)

SHOP_ERRORS = (CustomerError, ConsignmentError, BuyError, KioskError, SaleError, OutOfStock, OrderError, ChannelError, EventError)
SHOP_CSS = '''
.oy-pos { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 440px); gap: 24px; width: 100%;
  align-items: start; }
@media (max-width: 900px) { .oy-pos { grid-template-columns: minmax(0, 1fr); } }
.oy-pos-row { border-bottom: 1px solid var(--oy-border-soft); }
.oy-pos-ticket { border: 1px solid var(--oy-border); border-radius: 6px; background: var(--oy-surface); }
.oy-pos-total { font-family: var(--oy-font-display); font-size: 30px; line-height: 1.1; }
.oy-kiosk-code { font-family: var(--oy-font-display); font-size: 72px; line-height: 1; letter-spacing: 0.08em; }
'''


def shop_failure(error: Exception, fallback: str) -> str:
    """Only messages written for the person at the screen reach it."""
    if isinstance(error, SHOP_ERRORS) and str(error):
        return str(error)
    logger.error('Tienda: %s', type(error).__name__)
    return fallback


def when(stamp: Optional[str]) -> str:
    """An ISO moment as a short local date and time."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime('%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return stamp or ''


def amount_cents(text) -> int:
    """Cents typed by a person ("2,50"). Raises ValueError when it is not a positive amount."""
    cents = to_cents((text or '').strip() or '0')
    if cents <= 0:
        raise ValueError('Escribe un importe mayor que cero.')
    return cents


def customer_options(customers: List[Customer], balances: Dict[str, Dict[str, int]], currency: str,
                     kind: Optional[str] = 'credit') -> Dict[str, str]:
    """Choices for a customer picker, by name, with the balance that matters next to each."""
    options = {}
    for customer in sorted(customers, key=lambda c: c.name.casefold()):
        cents = balances.get(customer.id, {}).get(kind, 0) if kind else 0
        options[customer.id] = f'{customer.name} · {format_money(cents, currency)}' if cents else customer.name
    return options


def game_name(game: str) -> str:
    from src.services.catalog import get_provider

    try:
        return get_provider(game).display_name
    except Exception:
        return game


def printing_text(printing, finish: str = '') -> str:
    return ' · '.join(part for part in (printing.set_code, printing.number, printing.rarity or '', finish) if part)
