"""Shop back office: customers, their balances, purchases, consignments and kiosk orders. Integer cents."""

from __future__ import annotations

import uuid
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src.core.pricing_models import DEFAULT_CONDITION_FACTORS
from src.core.sales_models import SaleLine, now_iso

LedgerKind = Literal['credit', 'consignment', 'points']
LEDGER_LABELS = {'credit': 'Saldo de tienda', 'consignment': 'Consigna por liquidar', 'points': 'Puntos'}
PAYMENT_LABELS = {'cash': 'Efectivo', 'credit': 'Saldo de tienda'}


def _id() -> str:
    return uuid.uuid4().hex


def _percent(value: float) -> float:
    if value != value or value < 0 or value > 100:
        raise ValueError('El porcentaje debe estar entre 0 y 100')
    return value


class Customer(BaseModel):
    id: str = Field(default_factory=_id)
    name: str
    email: str = ''
    phone: str = ''
    note: str = ''
    created_at: str = Field(default_factory=now_iso)


class LedgerEntry(BaseModel):
    """One movement of a customer's balance. Entries are only ever added."""
    id: str = Field(default_factory=_id)
    customer_id: str
    at: str = Field(default_factory=now_iso)
    kind: LedgerKind
    cents: int  # positive: the shop owes the customer more; for 'points' it counts points, not cents
    reason: str
    ref: str = ''  # the sale, purchase or consignment behind it


class LoyaltyRules(BaseModel):
    """How customers earn points and what the shop gives for them."""
    enabled: bool = False
    points_per_unit: float = Field(default=1.0, ge=0, le=1000, allow_inf_nan=False)  # per unit of currency charged
    redeem_points: int = Field(default=100, ge=1, le=1_000_000)  # a block of this many points...
    redeem_cents: int = Field(default=100, ge=1, le=10_000_000)  # ...becomes this much store credit


class BuylistRules(BaseModel):
    """What the shop pays for a card, as a share of its market price."""
    cash_percent: float = 50.0
    credit_percent: float = 65.0
    min_offer_cents: int = 0  # cards whose offer falls below this are not bought
    condition_factors: Dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_CONDITION_FACTORS))

    @field_validator('cash_percent', 'credit_percent')
    @classmethod
    def _share(cls, value: float) -> float:
        return _percent(value)

    @field_validator('min_offer_cents')
    @classmethod
    def _floor(cls, value: int) -> int:
        if value < 0:
            raise ValueError('La oferta mínima no puede ser negativa')
        return value


class Purchase(BaseModel):
    """Cards bought from a customer. Each line's ``unit_cents`` is what the shop paid per copy."""
    id: str = Field(default_factory=_id)
    number: Optional[int] = None
    created_at: str = Field(default_factory=now_iso)
    cancelled_at: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: str = ''
    lines: List[SaleLine] = []
    total_cents: int = 0
    currency: str = 'EUR'
    payment: Literal['cash', 'credit'] = 'cash'
    status: Literal['done', 'cancelled'] = 'done'

    @property
    def label(self) -> str:
        return f'C{self.number:05d}' if self.number else 'sin número'

    @property
    def units(self) -> int:
        return sum(line.quantity for line in self.lines)


class Consignment(BaseModel):
    """A collection whose cards belong to a customer; the shop keeps a commission of each sale."""
    id: str = Field(default_factory=_id)
    customer_id: str
    game: str = 'yugioh'
    collection: str  # collection filename
    commission_percent: float = 20.0
    opened_at: str = Field(default_factory=now_iso)
    closed_at: Optional[str] = None

    @field_validator('commission_percent')
    @classmethod
    def _share(cls, value: float) -> float:
        return _percent(value)


class KioskOrder(BaseModel):
    """A list a visitor sent from the kiosk, waiting to be rung up at the counter."""
    id: str = Field(default_factory=_id)
    code: str
    name: str
    created_at: str = Field(default_factory=now_iso)
    lines: List[SaleLine] = []
    status: Literal['open', 'taken'] = 'open'
