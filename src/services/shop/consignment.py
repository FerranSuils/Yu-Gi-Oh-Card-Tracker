"""Consignment: collections whose cards belong to a customer, and what each sale owes them."""

from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional

from src.core.sales_models import Sale, SaleLine, now_iso
from src.core.shop_models import Consignment, LedgerEntry
from src.services.shop.customers import CustomerError, CustomerStore
from src.services.shop.files import BrokenFile, read_list, shop_path, write_list


class ConsignmentError(Exception):
    """A consignment that cannot be opened, closed or paid, with a message for the counter."""

    spoken = True


def line_net_cents(line: SaleLine, sale: Sale) -> int:
    """What a line brought in once the ticket discount is shared out by line value."""
    if sale.subtotal_cents <= 0:
        return 0
    return (2 * line.total_cents * sale.total_cents + sale.subtotal_cents) // (2 * sale.subtotal_cents)


def payout_cents(net: int, commission_percent: float) -> int:
    commission = int((Decimal(net) * Decimal(str(commission_percent)) / 100).quantize(
        Decimal(1), rounding=ROUND_HALF_UP))
    return net - commission


class ConsignmentBook:
    def __init__(self, root: str, customers: CustomerStore):
        self._path = shop_path(root, 'consignments.json')
        self._customers = customers
        self.lock = customers.lock

    def _read(self) -> List[Consignment]:
        try:
            return read_list(self._path, Consignment)
        except BrokenFile as error:
            raise ConsignmentError(f'El fichero {error} está dañado; no se ha tocado.') from error

    # --- reading -----------------------------------------------------------------------------

    def all(self) -> List[Consignment]:
        return sorted(self._read(), key=lambda c: c.opened_at, reverse=True)

    def active(self) -> List[Consignment]:
        return [c for c in self.all() if c.closed_at is None]

    def of(self, game: str, collection: str) -> Optional[Consignment]:
        """The open consignment a collection belongs to, if any."""
        return next((c for c in self._read()
                     if c.closed_at is None and (c.game, c.collection) == (game, collection)), None)

    def of_customer(self, customer_id: str) -> List[Consignment]:
        return [c for c in self.active() if c.customer_id == customer_id]

    # --- opening and closing -----------------------------------------------------------------

    def open(self, customer_id: str, game: str, collection: str, commission_percent: float) -> Consignment:
        if not collection or os.path.basename(collection) != collection or collection.startswith('.'):
            raise ConsignmentError('Colección no válida.')
        with self.lock:
            if self._customers.get(customer_id) is None:
                raise ConsignmentError('Elige el cliente dueño de las cartas.')
            if self.of(game, collection) is not None:
                raise ConsignmentError('Esa colección ya está en consigna.')
            try:
                consignment = Consignment(customer_id=customer_id, game=game, collection=collection,
                                          commission_percent=commission_percent)
            except ValueError:
                raise ConsignmentError('La comisión debe estar entre 0 y 100 %.') from None
            write_list(self._path, self._read() + [consignment])
        return consignment

    def close(self, consignment_id: str) -> None:
        """Unlink the collection: its cards stay where they are and stop earning for the customer."""
        with self.lock:
            consignments = self._read()
            for consignment in consignments:
                if consignment.id == consignment_id and consignment.closed_at is None:
                    consignment.closed_at = now_iso()
            write_list(self._path, consignments)

    def remove_customer(self, customer_id: str) -> None:
        """Delete a customer, unless the shop still holds their cards."""
        with self.lock:
            if self.of_customer(customer_id):
                raise ConsignmentError('Este cliente tiene cartas en consigna: cierra la consigna antes de '
                                       'borrarlo.')
            self._customers.remove(customer_id)

    # --- money -------------------------------------------------------------------------------

    def settle(self, sale: Sale) -> List[LedgerEntry]:
        """Credit the owners of the consigned lines of a paid sale. Call once per sale."""
        with self.lock:
            open_now = {(c.game, c.collection): c for c in self._read() if c.closed_at is None}
            entries = []
            for line in sale.lines:
                consignment = open_now.get((line.game, line.collection)) if line.kind == 'stock' else None
                if consignment is None:
                    continue
                owed = payout_cents(line_net_cents(line, sale), consignment.commission_percent)
                if owed <= 0:
                    continue
                entries.append(self._customers.post(
                    consignment.customer_id, 'consignment', owed,
                    f'Venta {sale.label}: {line.quantity}× {line.name} ({line.set_code or "sin set"})', ref=sale.id))
            return entries

    def reverse(self, sale: Sale) -> List[LedgerEntry]:
        """Take back whatever a sale credited. Safe to call twice: the second finds nothing left."""
        with self.lock:
            owed: Dict[str, int] = {}
            for entry in self._customers.by_ref(sale.id, 'consignment'):
                owed[entry.customer_id] = owed.get(entry.customer_id, 0) + entry.cents
            return [self._customers.post(customer_id, 'consignment', -cents, f'Devolución venta {sale.label}',
                                         ref=sale.id)
                    for customer_id, cents in owed.items() if cents > 0]

    def pay_out(self, customer_id: str, to: str, cents: Optional[int] = None) -> int:
        """Pay what is pending, in cash or as store credit. Returns the cents paid."""
        if to not in ('cash', 'credit'):
            raise ConsignmentError('Forma de liquidación no válida.')
        with self.lock:
            pending = self._customers.balance(customer_id, 'consignment')
            amount = pending if cents is None else cents
            if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0 or amount > pending:
                raise ConsignmentError('No hay ese importe pendiente de liquidar.')
            try:
                if to == 'credit':
                    self._customers.post(customer_id, 'consignment', -amount, 'Liquidación pasada a saldo de tienda')
                    self._customers.post(customer_id, 'credit', amount, 'Consigna liquidada')
                else:
                    self._customers.post(customer_id, 'consignment', -amount, 'Liquidación en efectivo')
            except CustomerError as error:
                raise ConsignmentError(str(error)) from error
        return amount

    def write_off(self, customer_id: str, reason) -> int:
        """Put a consignment debt back to zero (a refund after paying out), saying why. Returns the cents."""
        reason = str(reason or '').strip()
        if not reason:
            raise ConsignmentError('Indica cómo se ha resuelto la deuda.')
        with self.lock:
            try:
                debt = -self._customers.balance(customer_id, 'consignment')
                if debt <= 0:
                    raise ConsignmentError('Ese cliente no tiene deuda de consigna que regularizar.')
                self._customers.post(customer_id, 'consignment', debt, f'Deuda regularizada: {reason}')
            except CustomerError as error:
                raise ConsignmentError(str(error)) from error
        return debt
