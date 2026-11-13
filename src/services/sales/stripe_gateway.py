"""Stripe, called with the shop's own key: the money goes straight to the shop's Stripe account.

Plain REST over ``requests``. The key is only ever sent to api.stripe.com and never appears in
errors, logs or reprs.
"""

from __future__ import annotations

import re
import time
from typing import Optional, Tuple

import requests

from src.core.sales_models import Sale

API = 'https://api.stripe.com/v1'
TIMEOUT = 20
CHECKOUT_MINUTES = 31  # Stripe's shortest allowed life for a Checkout Session is 30 minutes
_KEY = re.compile(r'(sk|rk)_(test|live)_[A-Za-z0-9]{16,}')
_ID = re.compile(r'[A-Za-z0-9_]{4,255}')


class StripeError(Exception):
    """Something Stripe refused or that could not reach Stripe, worded for the shop."""

    code = ''  # Stripe's own error code, when it gave one


def check_key_format(key: str) -> str:
    key = (key or '').strip()
    if not key:
        raise StripeError('Pega la clave de Stripe.')
    if key.startswith('pk_'):
        raise StripeError('Esa es la clave publicable (pk_…). Hace falta la secreta o una restringida.')
    if not _KEY.fullmatch(key):
        raise StripeError('La clave debe empezar por sk_… o rk_… y estar completa.')
    return key


class StripeGateway:
    def __init__(self, key: str, http=None):
        self._key = key
        self._http = http or requests

    def __repr__(self) -> str:
        return 'StripeGateway(…)'

    # --- transport ---------------------------------------------------------------------------

    def _clean(self, text: str) -> str:
        return str(text).replace(self._key, '…')[:300]

    def _call(self, method: str, path: str, *, params=None, data=None, idempotency: Optional[str] = None) -> dict:
        headers = {'Authorization': f'Bearer {self._key}', 'User-Agent': 'OpenYuGi/1.0'}
        if idempotency:
            headers['Idempotency-Key'] = idempotency
        try:
            reply = self._http.request(method, f'{API}{path}', headers=headers, params=params, data=data,
                                       timeout=TIMEOUT)
        except requests.RequestException:
            raise StripeError('No se pudo conectar con Stripe. Inténtalo de nuevo.') from None
        try:
            body = reply.json()
        except ValueError:
            body = None
        if reply.status_code == 401:
            raise StripeError('La clave de Stripe no es válida o se ha revocado.')
        if reply.status_code == 403:
            raise StripeError('A la clave le falta permiso: necesita escritura en Checkout Sessions y en '
                              'Refunds.')
        if not 200 <= reply.status_code < 300 or not isinstance(body, dict):
            message = code = ''
            if isinstance(body, dict) and isinstance(body.get('error'), dict):
                message = body['error'].get('message') or ''
                code = body['error'].get('code') or ''
            error = StripeError(self._clean(message) or f'Stripe respondió con un error ({reply.status_code}).')
            error.code = code if isinstance(code, str) else ''
            raise error
        return body

    @staticmethod
    def _session(session: str) -> str:
        if not isinstance(session, str) or not _ID.fullmatch(session):
            raise StripeError('Identificador de pago no válido.')
        return session

    # --- operations --------------------------------------------------------------------------

    def check(self) -> None:
        """Raises unless the key works and may read Checkout Sessions."""
        self._call('GET', '/checkout/sessions', params={'limit': 1})

    def create_checkout(self, sale: Sale, success_url: str) -> Tuple[str, str]:
        units = sale.units
        name = f'Compra en tienda ({units} artículo{"s" if units != 1 else ""})'
        body = self._call('POST', '/checkout/sessions', idempotency=f'sale-{sale.id}', data={
            'mode': 'payment',
            'success_url': success_url,
            'client_reference_id': sale.id,
            'metadata[sale]': sale.id,
            'payment_method_types[0]': 'card',  # cards and wallets only: the result is known at once
            'expires_at': int(time.time()) + CHECKOUT_MINUTES * 60,
            # One line for the whole ticket, so discounts can never disagree with Stripe's sum.
            'line_items[0][quantity]': 1,
            'line_items[0][price_data][currency]': sale.currency.lower(),
            'line_items[0][price_data][unit_amount]': sale.total_cents,
            'line_items[0][price_data][product_data][name]': name,
        })
        session, url = body.get('id'), body.get('url')
        if not isinstance(session, str) or not isinstance(url, str) or not url.startswith('https://') \
                or not url.split('/')[2].endswith('stripe.com'):
            raise StripeError('Stripe no devolvió un enlace de pago válido.')
        return self._session(session), url

    def status(self, session: str) -> str:
        """'paid', 'open' or 'expired'."""
        body = self._call('GET', f'/checkout/sessions/{self._session(session)}')
        if body.get('payment_status') in ('paid', 'no_payment_required') and body.get('status') == 'complete':
            return 'paid'
        return 'expired' if body.get('status') == 'expired' else 'open'

    def expire(self, session: str) -> None:
        self._call('POST', f'/checkout/sessions/{self._session(session)}/expire')

    def refund(self, session: str) -> None:
        body = self._call('GET', f'/checkout/sessions/{self._session(session)}')
        payment = body.get('payment_intent')
        if not isinstance(payment, str) or not payment:
            raise StripeError('Stripe no tiene un pago asociado a esta venta.')
        try:
            self._call('POST', '/refunds', data={'payment_intent': payment}, idempotency=f'refund-{session}')
        except StripeError as error:
            # The money already went back (an earlier try that this app failed to write down).
            if error.code != 'charge_already_refunded':
                raise
