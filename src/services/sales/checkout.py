"""Charging a ticket: cash, the shop's own card terminal, its own Stripe account, or store credit."""

from __future__ import annotations

import logging
from typing import List, Optional

from src.core.sales_models import (
    Discount,
    Sale,
    SaleLine,
    discount_cents,
    format_money,
    now_iso,
    spoken,
    subtotal_cents,
)
from src.services.sales.inventory import Inventory
from src.services.sales.store import SalesStore

logger = logging.getLogger(__name__)

STRIPE_MINIMUM_CENTS = 50
UNCONFIRMED_NOTE = 'Cerrada sin confirmar con Stripe; comprueba en tu panel de Stripe si se llegó a pagar.'


class SaleError(Exception):
    """A ticket that cannot be charged, with a message for the person at the counter."""

    spoken = True


class Checkout:
    def __init__(self, inventory: Inventory, store: SalesStore, customers=None, consignments=None, loyalty=None):
        self._inventory = inventory
        self._store = store
        self._customers = customers  # CustomerStore: store credit and who bought
        self._consignments = consignments  # ConsignmentBook: what each sale owes the owners of the cards
        self._loyalty = loyalty  # Loyalty: the points a sale gives its customer

    # --- building ----------------------------------------------------------------------------

    @staticmethod
    def _draft(lines: List[SaleLine], discount: Discount, method: str, currency: str) -> Sale:
        if not lines:
            raise SaleError('El ticket está vacío.')
        if method not in ('cash', 'card', 'stripe', 'credit'):
            raise SaleError('Forma de cobro no válida.')
        subtotal = subtotal_cents(lines)
        off = discount_cents(subtotal, discount)
        if subtotal - off <= 0:
            raise SaleError('El ticket no tiene precio que cobrar.')
        return Sale(lines=[line.model_copy() for line in lines], discount=discount, subtotal_cents=subtotal,
                    discount_cents=off, total_cents=subtotal - off, currency=currency, method=method,
                    status='pending')

    def _get(self, sale_id: str) -> Sale:
        sale = self._store.get(sale_id)
        if sale is None:
            raise SaleError('Esa venta no existe.')
        return sale

    def _attach(self, sale: Sale, customer_id: Optional[str]) -> None:
        """Write the customer on the ticket. Store credit cannot be spent without one."""
        if customer_id is None and sale.method != 'credit':
            return
        if self._customers is None:
            if sale.method == 'credit':
                raise SaleError('El saldo de tienda no está disponible.')
            return
        try:
            customer = self._customers.get(customer_id)
        except Exception as error:
            raise SaleError(spoken(error, 'No se pudieron leer los clientes. Inténtalo de nuevo.')) from error
        if customer is None:
            raise SaleError('Elige el cliente que paga con su saldo.' if sale.method == 'credit'
                            else 'Ese cliente ya no existe.')
        sale.customer_id, sale.customer_name = customer.id, customer.name

    def _remark(self, sale: Sale, text: str) -> None:
        sale.note = f'{sale.note} {text}'.strip()
        self._store.save(sale)

    def _close(self, sale: Sale) -> Sale:
        sale.status = 'paid'
        sale.paid_at = now_iso()
        sale.number = self._store.next_number()
        self._store.save(sale)
        if self._consignments is not None:
            try:
                self._consignments.settle(sale)
            except Exception as error:  # the customer has paid: the sale stands and the shop is told
                logger.error('Venta %s: consigna sin anotar: %s', sale.id, type(error).__name__)
                self._remark(sale, 'Consigna sin anotar: revisa a mano lo que se debe al dueño de las cartas.')
        if self._loyalty is not None:
            try:
                self._loyalty.earn(sale)
            except Exception as error:
                logger.error('Venta %s: puntos sin anotar: %s', sale.id, type(error).__name__)
                self._remark(sale, 'Puntos sin anotar: añádelos a mano en la ficha del cliente.')
        return sale

    def _undo_money(self, sale: Sale) -> None:
        """After a refund: give the store credit back and take back what consignors were credited."""
        if sale.method == 'credit' and self._customers is not None:
            try:
                spent = -sum(entry.cents for entry in self._customers.by_ref(sale.id, 'credit'))
                if spent > 0:
                    self._customers.post(sale.customer_id, 'credit', spent, f'Devolución venta {sale.label}',
                                         ref=sale.id)
            except Exception as error:
                logger.error('Venta %s: saldo sin devolver: %s', sale.id, type(error).__name__)
                self._remark(sale, 'El saldo de tienda no se pudo devolver al cliente; revísalo a mano.')
        if self._consignments is not None:
            try:
                self._consignments.reverse(sale)
            except Exception as error:
                logger.error('Venta %s: consigna sin descontar: %s', sale.id, type(error).__name__)
                self._remark(sale, 'Consigna sin descontar: revisa a mano lo que se debe al dueño de las cartas.')
        if self._loyalty is not None:
            try:
                self._loyalty.reverse(sale)
            except Exception as error:
                logger.error('Venta %s: puntos sin descontar: %s', sale.id, type(error).__name__)
                self._remark(sale, 'Puntos sin descontar: quítalos a mano en la ficha del cliente.')

    def _release(self, sale: Sale, status: str) -> Sale:
        """Close a sale that will not be kept and put its stock back on the shelf."""
        sale.status = status
        if status == 'refunded':
            sale.refunded_at = now_iso()
        self._store.save(sale)
        try:
            self._inventory.give_back(sale.lines)
        except Exception as error:
            logger.error('Venta %s: no se pudo devolver el stock: %s', sale.id, type(error).__name__)
            sale.note = 'El stock no se pudo devolver a la colección; revísalo a mano.'
            self._store.save(sale)
        return sale

    # --- cash and card -----------------------------------------------------------------------

    def charge(self, lines: List[SaleLine], discount: Discount, method: str, currency: str,
               received_cents: Optional[int] = None, customer_id: Optional[str] = None) -> Sale:
        if method == 'stripe':
            raise SaleError('Forma de cobro no válida aquí: Stripe se cobra con enlace.')
        sale = self._draft(lines, discount, method, currency)
        self._attach(sale, customer_id)
        if method == 'cash':
            if received_cents is None:
                raise SaleError('Indica el importe entregado.')
            if received_cents < sale.total_cents:
                raise SaleError('El importe entregado no cubre el total.')
            sale.received_cents = received_cents
            sale.change_cents = received_cents - sale.total_cents
        with self._store.lock:
            if method == 'credit':
                return self._charge_credit(sale)
            self._inventory.take(sale.lines)
            try:
                return self._close(sale)
            except Exception:
                self._inventory.give_back(sale.lines)
                raise

    def _charge_credit(self, sale: Sale) -> Sale:
        """Spend the customer's store credit. Runs under the lock, so two tills cannot spend it twice."""
        try:
            have = self._customers.balance(sale.customer_id, 'credit')
        except Exception as error:
            raise SaleError(spoken(error, 'No se pudo leer el saldo de tienda. Inténtalo de nuevo.')) from error
        if have < sale.total_cents:
            raise SaleError(f'Saldo insuficiente: tiene {format_money(have, sale.currency)} de saldo de tienda.')
        self._inventory.take(sale.lines)
        try:
            self._close(sale)
        except Exception:
            self._inventory.give_back(sale.lines)
            raise
        try:
            self._customers.post(sale.customer_id, 'credit', -sale.total_cents, f'Venta {sale.label}', ref=sale.id)
        except Exception as error:
            sale.note = 'Anulada: no se pudo descontar el saldo de tienda.'
            self._release(sale, 'cancelled')
            self._undo_money(sale)
            raise SaleError(spoken(error, 'No se pudo descontar el saldo de tienda.')) from error
        return sale

    def refund(self, sale_id: str, gateway=None) -> Sale:
        with self._store.lock:
            sale = self._get(sale_id)
            if sale.status == 'refunded':
                raise SaleError('Esta venta ya está devuelta.')
            if sale.status != 'paid':
                raise SaleError('Solo se pueden devolver ventas cobradas.')
            if sale.method != 'stripe':
                self._release(sale, 'refunded')
                self._undo_money(sale)
                return sale
        if gateway is None:
            raise SaleError('Para devolver un cobro de Stripe, conecta Stripe en Ajustes.')
        gateway.refund(sale.stripe_session)  # raises before anything changes here
        with self._store.lock:
            sale = self._get(sale_id)
            if sale.status != 'paid':
                return sale  # another click got here first; the stock went back once
            self._release(sale, 'refunded')
            self._undo_money(sale)
            return sale

    # --- Stripe ------------------------------------------------------------------------------
    # Stripe is never called while holding the sales lock: a slow answer must not stop the till.
    # Each step asks Stripe first and then, under the lock, re-reads the sale before changing it.

    def start_stripe(self, lines: List[SaleLine], discount: Discount, currency: str, success_url: str,
                     gateway, customer_id: Optional[str] = None) -> Sale:
        sale = self._draft(lines, discount, 'stripe', currency)
        self._attach(sale, customer_id)
        if sale.total_cents < STRIPE_MINIMUM_CENTS:
            raise SaleError(f'Stripe no admite cobros de menos de {format_money(STRIPE_MINIMUM_CENTS, currency)}.')
        with self._store.lock:
            self._inventory.take(sale.lines)  # reserved while the customer pays
        try:
            sale.stripe_session, sale.stripe_url = gateway.create_checkout(sale, success_url)
            with self._store.lock:
                self._store.save(sale)
        except Exception:
            with self._store.lock:
                self._inventory.give_back(sale.lines)
            if sale.stripe_session:
                try:
                    gateway.expire(sale.stripe_session)
                except Exception:
                    pass
            raise
        return sale

    def _waiting(self, sale_id: str) -> Optional[Sale]:
        """The sale, if it is still waiting for a Stripe payment."""
        with self._store.lock:
            sale = self._get(sale_id)
        return sale if sale.status == 'pending' and sale.method == 'stripe' else None

    def _finish(self, sale_id: str, state: str, note: str = '') -> Sale:
        """Write down what Stripe said, unless the sale was closed meanwhile."""
        with self._store.lock:
            sale = self._get(sale_id)
            if sale.status != 'pending' or sale.method != 'stripe':
                return sale
            if state == 'paid':
                return self._close(sale)
            if state == 'expired':
                if note:
                    sale.note = note
                return self._release(sale, 'cancelled')
            return sale

    def settle_stripe(self, sale_id: str, gateway) -> Sale:
        """Ask Stripe how a pending payment went and close the sale accordingly."""
        sale = self._waiting(sale_id)
        if sale is None:
            return self._get(sale_id)
        return self._finish(sale_id, gateway.status(sale.stripe_session))

    def cancel_stripe(self, sale_id: str, gateway) -> Sale:
        sale = self._waiting(sale_id)
        if sale is None:
            return self._get(sale_id)
        if gateway.status(sale.stripe_session) == 'paid':
            return self._finish(sale_id, 'paid')  # the customer was faster than the cancel button
        try:
            gateway.expire(sale.stripe_session)
        except Exception:
            if self._waiting(sale_id) is None:
                return self._get(sale_id)  # closed by another click meanwhile
            if gateway.status(sale.stripe_session) == 'paid':
                return self._finish(sale_id, 'paid')
            raise
        return self._finish(sale_id, 'expired')

    def reconcile(self, gateway) -> List[Sale]:
        """Settle payments left pending by a closed page. Returns the sales that changed."""
        changed = []
        for pending in self._store.pending_stripe():
            try:
                sale = self.settle_stripe(pending.id, gateway)
            except Exception as error:
                logger.warning('Venta %s: no se pudo consultar Stripe: %s', pending.id, type(error).__name__)
                continue
            if sale.status != 'pending':
                changed.append(sale)
        return changed

    def close_pending(self, gateway) -> List[Sale]:
        """Cancel every payment still waiting (or close it if it was paid). Raises if Stripe fails."""
        return [self.cancel_stripe(pending.id, gateway) for pending in self._store.pending_stripe()]

    def release_pending(self) -> List[Sale]:
        """Close every waiting payment without Stripe, for a key that no longer works. Stock goes back."""
        return [self._finish(pending.id, 'expired', UNCONFIRMED_NOTE) for pending in self._store.pending_stripe()]
