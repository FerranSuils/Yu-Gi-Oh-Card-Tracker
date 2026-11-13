"""A shop's own Shopify, through its Admin GraphQL API: paid orders in, stock out. The token is the shop's."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

import requests

from src.core.order_models import Address
from src.services.orders.channels import ChannelError
from src.services.orders.importer import Article, Incoming

API_VERSION = '2026-10'
TIMEOUT = 20
PAGE = 50
MAX_PAGES = 5
MAX_BYTES = 8 * 1024 * 1024   # no honest answer to these questions is bigger
DEADLINE = 60                 # seconds for a whole answer, however slowly it drips
SEARCH_BATCH = 40
WRITE_BATCH = 100
SAFE_SKU = re.compile(r'[A-Za-z0-9._-]{1,64}')
_MAX_CENTS = 10 ** 9

_ORDERS = '''query Orders($query: String!, $after: String) {
  orders(first: %d, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id name email currencyCode
      shippingAddress { name address1 address2 zip city province countryCodeV2 }
      totalShippingPriceSet { shopMoney { amount } }
      currentTotalPriceSet { shopMoney { amount } }
      lineItems(first: 100) { nodes { name quantity sku originalUnitPriceSet { shopMoney { amount } } } }
    }
  }
}''' % PAGE
_ORDER_FILTER = 'financial_status:paid fulfillment_status:unfulfilled status:open'
_LOCATIONS = 'query { locations(first: 1) { nodes { id } } }'
_VARIANTS = '''query Variants($query: String!) {
  productVariants(first: 250, query: $query) { nodes { sku inventoryItem { id } } }
}'''
_SET = '''mutation Stock($input: InventorySetQuantitiesInput!, $key: String!) {
  inventorySetQuantities(input: $input) @idempotent(key: $key) { userErrors { code field message } }
}'''


@dataclass
class PushReport:
    updated: List[str] = field(default_factory=list)    # SKUs the shop now shows with our quantity
    missing: List[str] = field(default_factory=list)    # SKUs the shop does not have


def cents_of(value) -> int:
    """Whatever a shop calls an amount ('3.90', 9.99, None), in cents; nonsense is nothing."""
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return 0
    if not amount.is_finite() or amount < 0:
        return 0
    return min(int((amount * 100).to_integral_value()), _MAX_CENTS)


def read_body(reply, started: float, clock=time.monotonic):
    """The JSON a shop answered, read piece by piece so that it can be neither endless nor eternal.
    Raises ValueError when it is not JSON."""
    data = bytearray()
    try:
        for chunk in reply.iter_content(65536):
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise ChannelError('La tienda respondió con demasiados datos.')
            if clock() - started > DEADLINE:
                raise ChannelError('La tienda tarda demasiado en responder. Inténtalo de nuevo en un momento.')
    except requests.RequestException:
        raise ChannelError('Se cortó la respuesta de la tienda. Inténtalo de nuevo en un momento.') from None
    return json.loads(bytes(data).decode('utf-8'))


def shut(reply) -> None:
    close = getattr(reply, 'close', None)
    if callable(close):
        close()


def text_of(value, limit: int = 200) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ''


def count_of(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 1


class ShopifyClient:
    def __init__(self, domain: str, token: str, http=None):
        self._url = f'https://{domain}/admin/api/{API_VERSION}/graphql.json'
        self._domain = domain
        self._token = token
        self._http = http or requests
        self.truncated = False   # the last orders() left some behind

    def __repr__(self) -> str:
        return f'ShopifyClient({self._domain!r})'

    def _clean(self, text: str) -> str:
        return str(text).replace(self._token, '…')[:300]

    def _graphql(self, query: str, variables: Optional[dict] = None) -> dict:
        started = time.monotonic()
        try:
            reply = self._http.request(
                'POST', self._url, json={'query': query, 'variables': variables or {}},
                headers={'X-Shopify-Access-Token': self._token, 'Accept': 'application/json',
                         'User-Agent': 'OpenYuGi/1.0'},
                timeout=TIMEOUT, allow_redirects=False, stream=True)
        except requests.RequestException:
            raise ChannelError('No se pudo conectar con Shopify. Inténtalo de nuevo en un momento.') from None
        try:
            body = self._answer(reply, started)
        finally:
            shut(reply)
        if not isinstance(body, dict):
            raise ChannelError('Shopify respondió algo que no entiendo.')
        errors = body.get('errors')
        if errors:
            first = errors[0] if isinstance(errors, list) and errors else errors
            message = first.get('message') if isinstance(first, dict) else first
            raise ChannelError(f'Shopify dice: {self._clean(message)}')
        data = body.get('data')
        if not isinstance(data, dict):
            raise ChannelError('Shopify respondió algo que no entiendo.')
        return data

    @staticmethod
    def _answer(reply, started: float):
        status = reply.status_code
        if status == 401:
            raise ChannelError('Shopify no acepta ese token. Revísalo o crea uno nuevo.')
        if status == 403:
            raise ChannelError('Ese token no tiene permiso para esto. Dale acceso a pedidos, productos e inventario.')
        if status in (402, 404):
            raise ChannelError('No encuentro esa tienda de Shopify. Revisa el dominio.')
        if status == 429:
            raise ChannelError('Shopify dice que son demasiadas peticiones. Espera un minuto.')
        if status != 200:
            raise ChannelError(f'Shopify respondió algo inesperado ({status}).')
        try:
            return read_body(reply, started)
        except ValueError:
            raise ChannelError('Shopify respondió algo que no entiendo.') from None

    @staticmethod
    def _nodes(data: dict, name: str) -> List[dict]:
        nodes = (data.get(name) or {}).get('nodes') if isinstance(data.get(name), dict) else None
        return [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []

    # --- reading ---------------------------------------------------------------------------

    def ping(self) -> str:
        """The shop's name, which proves the domain and the token go together."""
        shop = self._graphql('query { shop { name } }').get('shop')
        if not isinstance(shop, dict):
            raise ChannelError('Shopify respondió algo que no entiendo.')
        return text_of(shop.get('name')) or self._domain

    def orders(self) -> List[Incoming]:
        """Paid orders nobody has shipped yet, the newest first. ``truncated`` says whether some were left."""
        found: List[Incoming] = []
        after = None
        self.truncated = False
        for _ in range(MAX_PAGES):
            data = self._graphql(_ORDERS, {'query': _ORDER_FILTER, 'after': after})
            found.extend(order for order in map(self._order, self._nodes(data, 'orders')) if order)
            page = (data.get('orders') or {}).get('pageInfo') or {}
            after = page.get('endCursor') if isinstance(page, dict) else None
            if not (isinstance(page, dict) and page.get('hasNextPage') and after):
                break
        else:
            self.truncated = True
        return found

    @staticmethod
    def _amount(money) -> int:
        try:
            return cents_of(money['shopMoney']['amount'])
        except (KeyError, TypeError):
            return 0

    def _order(self, node: dict) -> Optional[Incoming]:
        reference = text_of(node.get('name'), 60) or text_of(node.get('id'), 200).rsplit('/', 1)[-1]
        if not reference:
            return None
        place = node.get('shippingAddress') if isinstance(node.get('shippingAddress'), dict) else {}
        address = Address(
            name=text_of(place.get('name')), line1=text_of(place.get('address1')),
            line2=text_of(place.get('address2')), postcode=text_of(place.get('zip'), 20),
            city=text_of(place.get('city')), region=text_of(place.get('province')),
            country=text_of(place.get('countryCodeV2'), 60))
        articles = [Article(name=text_of(line.get('name'), 255) or 'Artículo', quantity=count_of(line.get('quantity')),
                            sku=text_of(line.get('sku'), 64), unit_cents=self._amount(line.get('originalUnitPriceSet')))
                    for line in self._nodes(node, 'lineItems')]
        return Incoming(external_id=reference, channel='shopify', customer_name=address.name,
                        email=text_of(node.get('email'), 254), address=address,
                        shipping_cents=self._amount(node.get('totalShippingPriceSet')),
                        total_cents=self._amount(node.get('currentTotalPriceSet')),
                        currency=text_of(node.get('currencyCode'), 3), articles=articles)

    # --- writing ---------------------------------------------------------------------------

    def push(self, quantities: Dict[str, int]) -> PushReport:
        """Sets the stock of the products whose SKU is ours. SKUs the shop does not have are told apart."""
        wanted = {sku: max(0, int(count)) for sku, count in quantities.items()}
        askable = [sku for sku in wanted if SAFE_SKU.fullmatch(sku)]
        if not askable:
            return PushReport(missing=list(wanted))
        locations = self._nodes(self._graphql(_LOCATIONS), 'locations')
        location = text_of(locations[0].get('id')) if locations else ''
        if not location:
            raise ChannelError('Esa tienda de Shopify no tiene ninguna ubicación de inventario.')
        items: Dict[str, str] = {}
        for start in range(0, len(askable), SEARCH_BATCH):
            batch = askable[start:start + SEARCH_BATCH]
            search = ' OR '.join(f'sku:"{sku}"' for sku in batch)
            for variant in self._nodes(self._graphql(_VARIANTS, {'query': search}), 'productVariants'):
                sku = variant.get('sku')
                item = variant.get('inventoryItem')
                if sku in wanted and sku not in items and isinstance(item, dict) and text_of(item.get('id')):
                    items[sku] = text_of(item.get('id'))
        found = list(items)
        for start in range(0, len(found), WRITE_BATCH):
            batch = found[start:start + WRITE_BATCH]
            data = self._graphql(_SET, {'key': str(uuid.uuid4()), 'input': {
                'name': 'available', 'reason': 'correction',
                'quantities': [{'inventoryItemId': items[sku], 'locationId': location, 'quantity': wanted[sku],
                                'changeFromQuantity': None} for sku in batch]}})
            result = data.get('inventorySetQuantities')
            errors = result.get('userErrors') if isinstance(result, dict) else None
            if errors:
                first = errors[0] if isinstance(errors, list) and isinstance(errors[0], dict) else {}
                raise ChannelError(f'Shopify no cambió el stock: {self._clean(first.get("message") or "error")}')
            if not isinstance(result, dict):
                raise ChannelError('Shopify respondió algo que no entiendo.')
        return PushReport(updated=found, missing=[sku for sku in wanted if sku not in items])
