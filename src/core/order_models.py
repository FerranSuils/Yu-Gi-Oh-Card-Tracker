"""Orders to ship: what was sold away from the counter, to whom, and how it travels. Integer cents."""

from __future__ import annotations

import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src.core.sales_models import SaleLine, now_iso

Channel = Literal['manual', 'cardmarket', 'tcgplayer', 'ebay', 'shopify', 'woocommerce', 'otro']
Status = Literal['new', 'paid', 'packed', 'shipped', 'delivered', 'cancelled', 'returned']

CHANNEL_LABELS = {'manual': 'A mano', 'cardmarket': 'Cardmarket', 'tcgplayer': 'TCGplayer', 'ebay': 'eBay',
                  'shopify': 'Shopify', 'woocommerce': 'WooCommerce', 'otro': 'Otro'}
ORDER_LABELS = {'new': 'Pendiente de pago', 'paid': 'Por preparar', 'packed': 'Preparado', 'shipped': 'Enviado',
                'delivered': 'Entregado', 'cancelled': 'Anulado', 'returned': 'Devuelto'}
OPEN_STATUSES = ('new', 'paid', 'packed')


def _id() -> str:
    return uuid.uuid4().hex


class Address(BaseModel):
    name: str = ''
    line1: str = ''
    line2: str = ''
    postcode: str = ''
    city: str = ''
    region: str = ''
    country: str = ''

    def lines(self) -> List[str]:
        town = ' '.join(part for part in (self.postcode.strip(), self.city.strip()) if part)
        rows = (self.name, self.line1, self.line2, town, self.region, self.country)
        return [row.strip() for row in rows if row.strip()]


class ShippingMethod(BaseModel):
    id: str = Field(default_factory=_id)
    name: str
    carrier: str = ''
    cents: int = 0
    tracking_url: str = ''        # https link with {code} where the tracking number goes

    @field_validator('cents')
    @classmethod
    def _price(cls, value: int) -> int:
        if value < 0:
            raise ValueError('El precio del envío no puede ser negativo')
        return value


class OrderLine(SaleLine):
    """A ticket line inside an order. ``unlinked``: sold outside, and nobody said which pile it leaves from."""
    unlinked: bool = False
    sku: str = ''


class Order(BaseModel):
    id: str = Field(default_factory=_id)
    number: Optional[int] = None
    created_at: str = Field(default_factory=now_iso)
    channel: Channel = 'manual'
    external_id: str = ''
    customer_id: Optional[str] = None
    customer_name: str = ''
    email: str = ''
    address: Address = Field(default_factory=Address)
    lines: List[OrderLine] = []
    shipping_name: str = ''
    carrier: str = ''
    shipping_cents: int = 0
    total_cents: int = 0
    charged_cents: int = 0   # what an online shop charged, when it told us; ours may differ
    currency: str = 'EUR'
    status: Status = 'new'
    tracking: str = ''
    tracking_template: str = ''
    paid_at: Optional[str] = None
    packed_at: Optional[str] = None
    shipped_at: Optional[str] = None
    delivered_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    returned_at: Optional[str] = None
    restocked: bool = False
    note: str = ''

    @property
    def label(self) -> str:
        return f'P{self.number:05d}' if self.number else 'sin número'

    @property
    def units(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def unlinked(self) -> int:
        return sum(1 for line in self.lines if line.unlinked)

    @property
    def goods_cents(self) -> int:
        return sum(line.total_cents for line in self.lines)

    @property
    def income_cents(self) -> int:
        """The money that came in: what the shop charged when it said so, our own sum otherwise."""
        return self.charged_cents or self.total_cents
