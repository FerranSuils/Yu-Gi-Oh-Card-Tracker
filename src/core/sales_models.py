"""Counter sales: tickets, their lines and the money maths. Amounts are integer cents."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

MAX_AMOUNT = Decimal(1_000_000)
SYMBOLS = {'EUR': '€', 'USD': '$', 'GBP': '£'}
METHOD_LABELS = {'cash': 'Efectivo', 'card': 'Tarjeta (datáfono)', 'stripe': 'Stripe',
                 'credit': 'Saldo de tienda'}
STATUS_LABELS = {'pending': 'Pendiente de pago', 'paid': 'Cobrada', 'cancelled': 'Cancelada',
                 'refunded': 'Devuelta'}


def to_cents(value: Any) -> int:
    """Cents for a price typed or stored as text or number. Empty means 0; anything else odd raises."""
    if value is None:
        return 0
    text = str(value).strip() if not isinstance(value, str) else value.strip()
    text = re.sub(r'[\s €$£]', '', text).replace(',', '.')
    if not text:
        return 0
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError('Importe no válido') from None
    if not number.is_finite() or number < 0 or number > MAX_AMOUNT:
        raise ValueError('Importe no válido')
    return int((number * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_money(cents: int, currency: str = 'EUR') -> str:
    whole, rest = divmod(abs(int(cents)), 100)
    sign = '-' if cents < 0 else ''
    symbol = SYMBOLS.get(currency, currency)
    if currency == 'EUR':
        return f'{sign}{whole:,}'.replace(',', '.') + f',{rest:02d} {symbol}'
    if currency in SYMBOLS:
        return f'{sign}{symbol}{whole:,}.{rest:02d}'
    return f'{sign}{whole:,}.{rest:02d} {symbol}'


class Discount(BaseModel):
    kind: Literal['none', 'percent', 'amount'] = 'none'
    value: float = 0.0

    @field_validator('value')
    @classmethod
    def _not_negative(cls, value: float) -> float:
        if value != value or value < 0:
            raise ValueError('El descuento no puede ser negativo')
        return value


class SaleLine(BaseModel):
    """One row of a ticket. A 'stock' line points at one physical pile of a collection."""
    kind: Literal['stock', 'custom'] = 'stock'
    game: str = 'yugioh'
    collection: str = ''          # collection filename
    card_id: str = ''
    name: str
    set_code: str = ''
    number: Optional[str] = None
    rarity: str = ''
    variant_id: str = ''          # Yu-Gi-Oh variant_id, or the printing_id in other games
    finish: str = ''              # other games only
    image_id: Optional[int] = None
    condition: str = 'Near Mint'
    language: str = 'EN'
    first_edition: bool = False
    storage_location: Optional[str] = None
    quantity: int = 1
    unit_cents: int = 0
    # The pile's own sale price, kept so a return can rebuild the pile as it was.
    list_price: Optional[float] = None
    price_locked: bool = False

    @field_validator('quantity')
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError('La cantidad debe ser 1 o más')
        return value

    @field_validator('unit_cents')
    @classmethod
    def _price(cls, value: int) -> int:
        if value < 0:
            raise ValueError('El precio no puede ser negativo')
        return value

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_cents

    def pile(self) -> tuple:
        return (self.condition, self.language, self.first_edition, self.storage_location)


def spoken(error: BaseException, fallback: str) -> str:
    """The words of an error written for people; anything else (paths, tracebacks) becomes the fallback."""
    text = str(error) if getattr(error, 'spoken', False) else ''
    return text or fallback


class OutOfStock(Exception):
    """A ticket line asks for more copies than its pile holds."""

    spoken = True

    def __init__(self, line: SaleLine, available: int):
        self.line = line
        self.available = available
        left = 'no queda ninguna' if available <= 0 else f'solo quedan {available}'
        super().__init__(f'{line.name} ({line.set_code or "sin set"}): {left} y el ticket pide {line.quantity}.')


def subtotal_cents(lines: List[SaleLine]) -> int:
    return sum(line.total_cents for line in lines)


def discount_cents(subtotal: int, discount: Discount) -> int:
    if discount.kind == 'percent':
        amount = int((Decimal(subtotal) * Decimal(str(discount.value)) / 100).quantize(
            Decimal(1), rounding=ROUND_HALF_UP))
    elif discount.kind == 'amount':
        amount = to_cents(discount.value)
    else:
        amount = 0
    return max(0, min(subtotal, amount))


def total_cents(lines: List[SaleLine], discount: Discount) -> int:
    subtotal = subtotal_cents(lines)
    return subtotal - discount_cents(subtotal, discount)


def change_cents(total: int, received: int) -> int:
    if received < total:
        raise ValueError('El importe entregado no cubre el total')
    return received - total


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Sale(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    number: Optional[int] = None
    created_at: str = Field(default_factory=now_iso)
    paid_at: Optional[str] = None
    refunded_at: Optional[str] = None
    lines: List[SaleLine] = []
    discount: Discount = Field(default_factory=Discount)
    subtotal_cents: int = 0
    discount_cents: int = 0
    total_cents: int = 0
    currency: str = 'EUR'
    method: Literal['cash', 'card', 'stripe', 'credit'] = 'cash'
    status: Literal['pending', 'paid', 'cancelled', 'refunded'] = 'paid'
    received_cents: Optional[int] = None
    change_cents: Optional[int] = None
    stripe_session: Optional[str] = None
    stripe_url: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: str = ''
    note: str = ''

    @property
    def label(self) -> str:
        return f'{self.number:06d}' if self.number else 'sin número'

    @property
    def units(self) -> int:
        return sum(line.quantity for line in self.lines)
