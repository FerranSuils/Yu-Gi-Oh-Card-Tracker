"""Loyalty points: what a customer earns by buying and swaps for store credit."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Tuple

from src.core.sales_models import Sale, format_money
from src.core.shop_models import LoyaltyRules
from src.services.sales.store import _write, patiently
from src.services.shop.customers import CustomerError, CustomerStore
from src.services.shop.files import root_lock, shop_path

FILE = 'loyalty.json'


def points_for(total_cents: int, rules: LoyaltyRules) -> int:
    """Whole points for what was charged; cents that do not make a point are dropped."""
    if total_cents <= 0:
        return 0
    return int(Decimal(total_cents) * Decimal(str(rules.points_per_unit)) / 100)


class Loyalty:
    def __init__(self, root: str, customers: CustomerStore, currency: str = 'EUR'):
        self._path = shop_path(root, FILE)
        self._customers = customers
        self._currency = currency
        self._lock = root_lock(root)

    # --- the rules ---------------------------------------------------------------------------

    def rules(self) -> LoyaltyRules:
        if not os.path.exists(self._path):
            return LoyaltyRules()

        def load():
            with open(self._path, 'r', encoding='utf-8') as file:
                return json.load(file)

        try:
            data = patiently(load)
            if not isinstance(data, dict):
                raise ValueError('not a dict')
            return LoyaltyRules(**data)
        except (OSError, ValueError, TypeError) as error:
            raise CustomerError(f'El fichero {FILE} está dañado; no se ha tocado.') from error

    def save_rules(self, rules: LoyaltyRules) -> None:
        with self._lock:
            _write(self._path, rules.model_dump(mode='json'))

    # --- at the till -------------------------------------------------------------------------

    def earn(self, sale: Sale) -> int:
        """Note the points of a paid sale. Once per sale; nothing for what store credit paid."""
        if not sale.customer_id or sale.method == 'credit':
            return 0
        rules = self.rules()
        if not rules.enabled:
            return 0
        points = points_for(sale.total_cents, rules)
        if points <= 0:
            return 0
        with self._lock:
            if self._customers.by_ref(sale.id, 'points'):
                return 0
            self._customers.post(sale.customer_id, 'points', points, f'Venta {sale.label}', ref=sale.id)
        return points

    def reverse(self, sale: Sale) -> int:
        """Take back what a sale gave. The balance may end below zero if it was already spent."""
        if not sale.customer_id:
            return 0
        with self._lock:
            given = sum(entry.cents for entry in self._customers.by_ref(sale.id, 'points'))
            if given <= 0:
                return 0
            self._customers.post(sale.customer_id, 'points', -given, f'Devolución venta {sale.label}', ref=sale.id)
        return given

    # --- at the customer's card --------------------------------------------------------------

    def redeem(self, customer_id: str) -> Tuple[int, int]:
        """Swap every whole block of points for store credit. Returns (points used, cents given)."""
        rules = self.rules()
        if not rules.enabled:
            raise CustomerError('Los puntos están apagados. Enciéndelos en Ajustes → Puntos.')
        with self._lock:
            if self._customers.get(customer_id) is None:
                raise CustomerError('Ese cliente no existe.')
            have = self._customers.points(customer_id)
            blocks = have // rules.redeem_points if have > 0 else 0
            if blocks <= 0:
                raise CustomerError(f'Tiene {have} puntos y hacen falta {rules.redeem_points} para canjear.')
            used, cents = blocks * rules.redeem_points, blocks * rules.redeem_cents
            reason = f'Canje de {used} puntos por {format_money(cents, self._currency)}'
            self._customers.post_together(customer_id, [('points', -used, reason), ('credit', cents, reason)])
        return used, cents
