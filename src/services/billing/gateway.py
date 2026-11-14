"""Nordic Byte's own Stripe account: the 10 € lifetime payment and the yearly 2 € invoice.

Reuses the shops' REST client (key never leaves api.stripe.com, never shows in errors or logs).
"""

from __future__ import annotations

import time
from typing import Tuple

from src.services.billing import plan
from src.services.sales.stripe_gateway import CHECKOUT_MINUTES, StripeError, StripeGateway


def _https_stripe(url) -> bool:
    return isinstance(url, str) and url.startswith('https://') and url.split('/')[2].endswith('stripe.com')


class BillingGateway(StripeGateway):
    def __repr__(self) -> str:
        return 'BillingGateway(…)'

    def create_lifetime_checkout(self, username: str, success_url: str, cancel_url: str) -> Tuple[str, str]:
        bucket = int(time.time() // (CHECKOUT_MINUTES * 60))  # a new attempt after the old session expired
        body = self._call('POST', '/checkout/sessions', idempotency=f'lifetime-{username}-{bucket}', data={
            'mode': 'payment',
            'success_url': success_url,
            'cancel_url': cancel_url,
            'client_reference_id': username,
            'metadata[account]': username,
            'metadata[plan]': 'lifetime',
            'payment_method_types[0]': 'card',
            'line_items[0][quantity]': 1,
            'line_items[0][price_data][currency]': 'eur',
            'line_items[0][price_data][unit_amount]': plan.LIFETIME_CENTS,
            'line_items[0][price_data][product_data][name]': 'OpenYuGi · plan de por vida',
        })
        session, url = body.get('id'), body.get('url')
        if not _https_stripe(url):
            raise StripeError('Stripe no devolvió un enlace de pago válido.')
        return self._session(session), url

    def ensure_customer(self, username: str) -> str:
        body = self._call('POST', '/customers', idempotency=f'customer-{username}',
                          data={'name': username, 'metadata[account]': username})
        return self._session(body.get('id'))

    def create_annual_invoice(self, customer: str, username: str, year: int) -> Tuple[str, str]:
        """A 2 € invoice for the server's upkeep, payable from its Stripe page (accounts have no email)."""
        key = f'annual-{username}-{year}'
        self._call('POST', '/invoiceitems', idempotency=f'{key}-item', data={
            'customer': customer, 'amount': plan.ANNUAL_CENTS, 'currency': 'eur',
            'description': f'OpenYuGi · mantenimiento del servidor {year}',
        })
        invoice = self._call('POST', '/invoices', idempotency=f'{key}-invoice', data={
            'customer': customer, 'collection_method': 'send_invoice',
            'days_until_due': plan.INVOICE_DAYS_DUE, 'pending_invoice_items_behavior': 'include',
            'metadata[account]': username, 'metadata[year]': year,
        })
        invoice_id = self._session(invoice.get('id'))
        final = self._call('POST', f'/invoices/{invoice_id}/finalize', idempotency=f'{key}-finalize')
        url = final.get('hosted_invoice_url')
        if not _https_stripe(url):
            raise StripeError('Stripe no devolvió el enlace de la factura.')
        return invoice_id, url

    def invoice_paid(self, invoice_id: str) -> bool:
        return self._call('GET', f'/invoices/{self._session(invoice_id)}').get('status') == 'paid'
