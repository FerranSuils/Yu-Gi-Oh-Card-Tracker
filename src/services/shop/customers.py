"""The customers of one shop and the book of what the shop owes each of them."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from src.core.sales_models import format_money
from src.core.shop_models import Customer, LedgerEntry
from src.services.shop.files import BrokenFile, read_list, root_lock, shop_path, write_list

MAX_ENTRY_CENTS = 100_000_000
LIMITS = {'name': 80, 'email': 120, 'phone': 40, 'note': 500}
KINDS = ('credit', 'consignment', 'points')
MONEY = ('credit', 'consignment')


class CustomerError(Exception):
    """Something about a customer or their balance that the person at the counter must read."""

    spoken = True


def _clean(fields: dict) -> dict:
    return {key: str(value or '').strip()[:LIMITS[key]] for key, value in fields.items() if key in LIMITS}


class CustomerStore:
    def __init__(self, root: str, currency: str = 'EUR'):
        self._customers = shop_path(root, 'customers.json')
        self._ledger = shop_path(root, 'ledger.json')
        self._currency = currency
        self.lock = root_lock(root)  # the same lock as the sales of this account

    # --- reading -----------------------------------------------------------------------------

    def _read(self, path: str, model):
        try:
            return read_list(path, model)
        except BrokenFile as error:
            raise CustomerError(f'El fichero {error} está dañado; no se ha tocado.') from error

    def all(self) -> List[Customer]:
        return sorted(self._read(self._customers, Customer), key=lambda c: c.name.casefold())

    def get(self, customer_id: Optional[str]) -> Optional[Customer]:
        return next((c for c in self._read(self._customers, Customer) if c.id == customer_id), None)

    def entries(self, customer_id: str, kind: Optional[str] = None) -> List[LedgerEntry]:
        """A customer's movements, newest first."""
        rows = [e for e in self._read(self._ledger, LedgerEntry)
                if e.customer_id == customer_id and kind in (None, e.kind)]
        return rows[::-1]

    def by_ref(self, ref: str, kind: Optional[str] = None) -> List[LedgerEntry]:
        return [e for e in self._read(self._ledger, LedgerEntry) if e.ref == ref and kind in (None, e.kind)]

    def balance(self, customer_id: str, kind: str) -> int:
        return sum(e.cents for e in self._read(self._ledger, LedgerEntry)
                   if e.customer_id == customer_id and e.kind == kind)

    def balances(self) -> Dict[str, Dict[str, int]]:
        totals: Dict[str, Dict[str, int]] = {}
        for entry in self._read(self._ledger, LedgerEntry):
            per = totals.setdefault(entry.customer_id, dict.fromkeys(KINDS, 0))
            per[entry.kind] += entry.cents
        return totals

    def points(self, customer_id: str) -> int:
        return self.balance(customer_id, 'points')

    # --- writing -----------------------------------------------------------------------------

    def add(self, name: str, email: str = '', phone: str = '', note: str = '') -> Customer:
        fields = _clean({'name': name, 'email': email, 'phone': phone, 'note': note})
        if not fields['name']:
            raise CustomerError('El cliente necesita un nombre.')
        customer = Customer(**fields)
        with self.lock:
            write_list(self._customers, self._read(self._customers, Customer) + [customer])
        return customer

    def update(self, customer_id: str, **fields) -> Customer:
        fields = _clean(fields)
        if 'name' in fields and not fields['name']:
            raise CustomerError('El cliente necesita un nombre.')
        with self.lock:
            customers = self._read(self._customers, Customer)
            customer = next((c for c in customers if c.id == customer_id), None)
            if customer is None:
                raise CustomerError('Ese cliente no existe.')
            for key, value in fields.items():
                setattr(customer, key, value)
            write_list(self._customers, customers)
        return customer

    def remove(self, customer_id: str) -> None:
        with self.lock:
            owed = self.balances().get(customer_id, {})
            if any(owed.get(kind) for kind in MONEY):  # points are no debt: they go with the customer
                raise CustomerError('Este cliente tiene saldo pendiente: liquídalo antes de borrarlo.')
            customers = self._read(self._customers, Customer)
            write_list(self._customers, [c for c in customers if c.id != customer_id])

    def post(self, customer_id: str, kind: str, cents: int, reason: str, ref: str = '') -> LedgerEntry:
        """Write one movement down. Store credit can never end below zero."""
        return self.post_together(customer_id, [(kind, cents, reason)], ref)[0]

    def post_together(self, customer_id: str, moves: List[Tuple[str, int, str]], ref: str = '') -> List[LedgerEntry]:
        """Write several movements of one customer in a single write: all of them or none."""
        checked = []
        for kind, cents, reason in moves:
            reason = str(reason or '').strip()[:200]
            if kind not in KINDS:
                raise CustomerError('Tipo de saldo no válido.')
            if isinstance(cents, bool) or not isinstance(cents, int) or cents == 0 or abs(cents) > MAX_ENTRY_CENTS:
                raise CustomerError('Importe no válido.')
            if not reason:
                raise CustomerError('Indica el motivo del movimiento.')
            checked.append((kind, cents, reason))
        with self.lock:
            if self.get(customer_id) is None:
                raise CustomerError('Ese cliente no existe.')
            ledger = self._read(self._ledger, LedgerEntry)
            have = sum(e.cents for e in ledger if e.customer_id == customer_id and e.kind == 'credit')
            entries = []
            for kind, cents, reason in checked:
                if kind == 'credit':
                    if cents < 0 and have + cents < 0:
                        raise CustomerError(
                            f'Saldo insuficiente: tiene {format_money(have, self._currency)} de saldo de tienda.')
                    have += cents
                entries.append(LedgerEntry(customer_id=customer_id, kind=kind, cents=cents, reason=reason, ref=ref))
            write_list(self._ledger, ledger + entries)
        return entries
