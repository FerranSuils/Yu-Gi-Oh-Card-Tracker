"""A shop's own WooCommerce, through its REST API: orders being prepared in, stock out. The address is
somebody else's, so it is checked again before every single call and redirects are never followed."""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

import requests

from src.core.order_models import Address
from src.services.orders.channels import ChannelError, check_public_https
from src.services.orders.importer import Article, Incoming
from src.services.orders.shopify import SAFE_SKU, PushReport, cents_of, count_of, read_body, shut, text_of

TIMEOUT = 20
PAGE = 50
MAX_PAGES = 5
SEARCH_BATCH = 50
WRITE_BATCH = 100
_STRANGE = 'La tienda respondió algo que no entiendo. ¿Está activa la API REST de WooCommerce?'


class WooClient:
    def __init__(self, url: str, key: str, secret: str, http=None, resolve: Optional[Callable] = None):
        self._base = url
        self._key = key
        self._secret = secret
        self._http = http or requests
        self._resolve = resolve
        self.truncated = False   # the last orders() left some behind

    def __repr__(self) -> str:
        return f'WooClient({self._base!r})'

    def _call(self, method: str, path: str, params: Optional[dict] = None, json: Optional[dict] = None):
        base = check_public_https(self._base, resolve=self._resolve)
        started = time.monotonic()
        try:
            reply = self._http.request(
                method, f'{base}/wp-json/wc/v3/{path}', params=params, json=json, auth=(self._key, self._secret),
                headers={'Accept': 'application/json', 'User-Agent': 'OpenYuGi/1.0'},
                timeout=TIMEOUT, allow_redirects=False, stream=True)
        except requests.RequestException:
            raise ChannelError('No se pudo conectar con la tienda. Inténtalo de nuevo en un momento.') from None
        try:
            return self._answer(reply, started)
        finally:
            shut(reply)

    @staticmethod
    def _answer(reply, started: float):
        status = reply.status_code
        if 300 <= status < 400:
            raise ChannelError('La tienda redirige a otra dirección. Escribe la dirección definitiva (con o sin www).')
        if status in (401, 403):
            raise ChannelError('WooCommerce no acepta esas claves, o no tienen permiso de lectura y escritura.')
        if status == 404:
            raise ChannelError('No encuentro la API de WooCommerce en esa dirección.')
        if status == 429:
            raise ChannelError('La tienda dice que son demasiadas peticiones. Espera un minuto.')
        if not 200 <= status < 300:
            raise ChannelError(f'La tienda respondió algo inesperado ({status}).')
        try:
            return read_body(reply, started)
        except ValueError:
            raise ChannelError(_STRANGE) from None

    def _list(self, path: str, params: dict) -> List[dict]:
        body = self._call('GET', path, params=params)
        if not isinstance(body, list):
            raise ChannelError(_STRANGE)
        return [entry for entry in body if isinstance(entry, dict)]

    # --- reading ---------------------------------------------------------------------------

    def ping(self) -> str:
        self._list('orders', {'per_page': 1})
        return self._base

    def orders(self) -> List[Incoming]:
        """Paid orders the shop is preparing. ``truncated`` says whether some were left behind."""
        found: List[Incoming] = []
        self.truncated = False
        for page in range(1, MAX_PAGES + 1):
            batch = self._list('orders', {'status': 'processing', 'per_page': PAGE, 'page': page})
            found.extend(order for order in map(self._order, batch) if order)
            if len(batch) < PAGE:
                break
        else:
            self.truncated = True
        return found

    @staticmethod
    def _order(entry: dict) -> Optional[Incoming]:
        reference = str(entry.get('number') or entry.get('id') or '').strip()[:60]
        if not reference:
            return None
        billing = entry.get('billing') if isinstance(entry.get('billing'), dict) else {}
        shipping = entry.get('shipping') if isinstance(entry.get('shipping'), dict) else {}
        place = shipping if text_of(shipping.get('address_1')) else billing

        def person(source: dict) -> str:
            return ' '.join(part for part in (text_of(source.get('first_name')), text_of(source.get('last_name')))
                            if part)

        name = person(place) or person(billing)
        address = Address(
            name=name, line1=text_of(place.get('address_1')), line2=text_of(place.get('address_2')),
            postcode=text_of(place.get('postcode'), 20), city=text_of(place.get('city')),
            region=text_of(place.get('state')), country=text_of(place.get('country'), 60))
        lines = entry.get('line_items') if isinstance(entry.get('line_items'), list) else []
        articles = [Article(name=text_of(line.get('name'), 255) or 'Artículo', quantity=count_of(line.get('quantity')),
                            sku=text_of(line.get('sku'), 64), unit_cents=cents_of(line.get('price')))
                    for line in lines if isinstance(line, dict)]
        return Incoming(external_id=reference, channel='woocommerce', customer_name=name,
                        email=text_of(billing.get('email'), 254), address=address,
                        shipping_cents=cents_of(entry.get('shipping_total')),
                        total_cents=cents_of(entry.get('total')),
                        currency=text_of(entry.get('currency'), 3), articles=articles)

    # --- writing ---------------------------------------------------------------------------

    def push(self, quantities: Dict[str, int]) -> PushReport:
        """Sets the stock of the products whose SKU is ours. A product the shop refuses is left for next time."""
        wanted = {sku: max(0, int(count)) for sku, count in quantities.items()}
        askable = [sku for sku in wanted if SAFE_SKU.fullmatch(sku)]
        products: Dict[str, int] = {}
        for start in range(0, len(askable), SEARCH_BATCH):
            batch = askable[start:start + SEARCH_BATCH]
            for product in self._list('products', {'sku': ','.join(batch), 'per_page': 100}):
                sku, identity = product.get('sku'), product.get('id')
                if sku in wanted and sku not in products and isinstance(identity, int) and identity > 0:
                    products[sku] = identity
        by_id = {identity: sku for sku, identity in products.items()}
        found = list(products)
        updated: List[str] = []
        for start in range(0, len(found), WRITE_BATCH):
            batch = found[start:start + WRITE_BATCH]
            body = self._call('POST', 'products/batch', json={'update': [
                {'id': products[sku], 'manage_stock': True, 'stock_quantity': wanted[sku]} for sku in batch]})
            answers = body.get('update') if isinstance(body, dict) else None
            if not isinstance(answers, list):
                raise ChannelError(_STRANGE)
            for answer in answers:
                if isinstance(answer, dict) and not answer.get('error') and answer.get('id') in by_id:
                    updated.append(by_id[answer['id']])
        return PushReport(updated=updated, missing=[sku for sku in wanted if sku not in products])
