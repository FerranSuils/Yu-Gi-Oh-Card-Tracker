"""The ticket being rung up at the counter, before it is charged."""

from __future__ import annotations

from typing import Dict, List, Optional

from src.core.sales_models import Discount, SaleLine, discount_cents, subtotal_cents, to_cents
from src.services.sales.inventory import line_key

MAX_CUSTOM_QUANTITY = 999


class Ticket:
    def __init__(self) -> None:
        self.lines: List[SaleLine] = []
        self.discount = Discount()
        self._stock: Dict[tuple, int] = {}

    # --- lines -------------------------------------------------------------------------------

    def add(self, item: SaleLine) -> Optional[str]:
        """Put one copy of a pile on the ticket. Returns a message when the pile has no more."""
        key = line_key(item)
        self._stock[key] = item.quantity
        for line in self.lines:
            if line.kind == 'stock' and line_key(line) == key:
                if line.quantity >= item.quantity:
                    return f'{item.name}: solo hay {item.quantity} en esa pila.'
                line.quantity += 1
                return None
        self.lines.append(item.model_copy(update={'quantity': 1}))
        return None

    def add_custom(self, name: str, price, quantity: int = 1) -> None:
        name = (name or '').strip()
        if not name:
            raise ValueError('Escribe el nombre del artículo.')
        cents = to_cents(price)
        if cents <= 0:
            raise ValueError('Escribe el precio del artículo.')
        quantity = max(1, min(MAX_CUSTOM_QUANTITY, int(quantity or 1)))
        self.lines.append(SaleLine(kind='custom', game='', name=name[:120], quantity=quantity, unit_cents=cents))

    def stock(self, index: int) -> Optional[int]:
        """Copies the pile of a line holds; None for a line without inventory."""
        line = self.lines[index]
        return self._stock.get(line_key(line)) if line.kind == 'stock' else None

    def set_quantity(self, index: int, quantity) -> None:
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            quantity = 1
        limit = self.stock(index)
        self.lines[index].quantity = max(1, min(MAX_CUSTOM_QUANTITY if limit is None else limit, quantity))

    def set_price(self, index: int, price) -> None:
        self.lines[index].unit_cents = to_cents(price)

    def remove(self, index: int) -> None:
        del self.lines[index]

    def sync(self, items: List[SaleLine]) -> List[str]:
        """Bring the ticket in line with the shelf as it is now. Returns the names it had to change."""
        self._stock = {line_key(item): item.quantity for item in items}
        changed, kept = [], []
        for line in self.lines:
            if line.kind == 'stock':
                available = self._stock.get(line_key(line), 0)
                if available < line.quantity:
                    changed.append(line.name)
                    if available <= 0:
                        continue
                    line.quantity = available
            kept.append(line)
        self.lines = kept
        return changed

    def clear(self) -> None:
        self.lines = []
        self.discount = Discount()

    # --- totals ------------------------------------------------------------------------------

    def set_discount(self, kind: str, value) -> None:
        if kind == 'none':
            self.discount = Discount()
            return
        if kind not in ('percent', 'amount'):
            raise ValueError('Descuento no válido')
        try:
            number = to_cents(value) / 100
        except ValueError:
            raise ValueError('Descuento no válido') from None
        if kind == 'percent' and number > 100:
            raise ValueError('El descuento no puede pasar del 100 %')
        self.discount = Discount(kind=kind, value=number)

    @property
    def subtotal(self) -> int:
        return subtotal_cents(self.lines)

    @property
    def discount_cents(self) -> int:
        return discount_cents(self.subtotal, self.discount)

    @property
    def total(self) -> int:
        return self.subtotal - self.discount_cents

    def blocker(self) -> Optional[str]:
        """Why this ticket cannot be charged yet, or None."""
        if not self.lines:
            return 'El ticket está vacío.'
        unpriced = [line.name for line in self.lines if line.unit_cents <= 0]
        if unpriced:
            return f'Pon precio a: {", ".join(unpriced[:3])}.'
        if self.total <= 0:
            return 'El descuento deja el ticket a cero.'
        return None
