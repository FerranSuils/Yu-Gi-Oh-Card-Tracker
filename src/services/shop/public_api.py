"""Read-only API for a shop's own website: /api/v1/shop/… with the account's key.

Nothing here returns keys, emails, addresses or customer names.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Callable, Iterable, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.core.account_profile import AccountProfile, enabled_games, load_profile
from src.core.order_models import Order
from src.core.sales_models import Sale, SaleLine
from src.services.orders.sku import sku_of
from src.services.shop import api_keys, kiosk
from src.services.shop.desk import desk_for, inventory_for

logger = logging.getLogger(__name__)

PREFIX = '/api/v1/shop'
PER_MINUTE = 60
_BEARER = re.compile(r'Bearer (oy_[0-9a-f]{48})')
_MONTH = re.compile(r'\d{4}-(0[1-9]|1[0-2])')


# --- what goes out ---------------------------------------------------------------------------

def _card(line: SaleLine, sku: str) -> dict:
    return {'name': line.name, 'game': line.game, 'set': line.set_code, 'number': line.number,
            'quantity': line.quantity, 'price_cents': line.unit_cents, 'sku': sku}


def stock_rows(items: Iterable[SaleLine]) -> List[dict]:
    """Priced stock, piles that differ only in where they are kept added up."""
    rows = []
    for line in kiosk.shelf(list(items)):
        row = _card(line, sku_of(line))
        row.update(rarity=line.rarity, condition=line.condition, language=line.language,
                   first_edition=line.first_edition, finish=line.finish)
        rows.append(row)
    return rows


def order_rows(orders: Iterable[Order]) -> List[dict]:
    """Orders with the town and country they go to, and nothing else about who ordered."""
    return [{
        'number': order.number, 'created_at': order.created_at, 'channel': order.channel, 'status': order.status,
        'city': order.address.city, 'country': order.address.country, 'carrier': order.carrier,
        'shipping_cents': order.shipping_cents, 'total_cents': order.total_cents, 'currency': order.currency,
        'paid_at': order.paid_at, 'shipped_at': order.shipped_at, 'delivered_at': order.delivered_at,
        'lines': [_card(line, line.sku or (sku_of(line) if line.kind == 'stock' and not line.unlinked else ''))
                  for line in order.lines],
    } for order in orders]


def sale_rows(sales: Iterable[Sale]) -> List[dict]:
    """Tickets that were paid and stayed paid, without the customer."""
    return [{
        'number': sale.number, 'created_at': sale.created_at, 'paid_at': sale.paid_at, 'method': sale.method,
        'subtotal_cents': sale.subtotal_cents, 'discount_cents': sale.discount_cents,
        'total_cents': sale.total_cents, 'currency': sale.currency,
        'lines': [_card(line, sku_of(line) if line.kind == 'stock' else '') for line in sale.lines],
    } for sale in sales if sale.status == 'paid']


# --- reading one account ---------------------------------------------------------------------

def stock_of(root: str, profile: AccountProfile) -> List[SaleLine]:
    return inventory_for(root).items(enabled_games(profile))


def _orders_of(root: str, profile: AccountProfile) -> List[Order]:
    return desk_for(root, profile.shop.currency).dispatch.all()


# --- the routes ------------------------------------------------------------------------------

def _refuse(status: int, detail: str, **headers: str) -> JSONResponse:
    return JSONResponse({'detail': detail}, status_code=status, headers=headers or None)


def build_router(base: str = 'data', limiter: Optional[api_keys.Limiter] = None) -> APIRouter:
    router = APIRouter(prefix=PREFIX)
    limiter = limiter or api_keys.Limiter(PER_MINUTE, 60)

    def answer(request: Request, rows: Callable[[str, AccountProfile], List[dict]]) -> JSONResponse:
        found = _BEARER.fullmatch(request.headers.get('authorization') or '')
        root = api_keys.account_for(found.group(1), base) if found else None
        profile = load_profile(root) if root else None
        if profile is None or not profile.shop_mode:
            return _refuse(401, 'Clave no válida.', **{'WWW-Authenticate': 'Bearer'})
        if not limiter.allow(api_keys.digest(found.group(1))):
            return _refuse(429, 'Demasiadas peticiones. Espera un minuto.', **{'Retry-After': '60'})
        try:
            data = rows(root, profile)
        except Exception as error:   # never the reason: it may name a file or a person
            logger.error('API %s: %s', request.url.path, type(error).__name__)
            return _refuse(500, 'No se pudieron leer los datos de la tienda.')
        return JSONResponse({'data': data}, headers={'Cache-Control': 'no-store'})

    @router.get('/stock')
    def stock(request: Request):
        return answer(request, lambda root, profile: stock_rows(stock_of(root, profile)))

    @router.get('/orders')
    def orders(request: Request):
        return answer(request, lambda root, profile: order_rows(_orders_of(root, profile)))

    @router.get('/sales')
    def sales(request: Request, month: Optional[str] = None):
        month = datetime.now(timezone.utc).strftime('%Y-%m') if month is None else month
        if not _MONTH.fullmatch(month):
            # said only to someone holding a good key: everyone else gets the same 401 as always
            checked = answer(request, lambda root, profile: [])
            return checked if checked.status_code != 200 else _refuse(400, 'El mes se escribe AAAA-MM.')
        return answer(request, lambda root, profile: sale_rows(desk_for(root, profile.shop.currency).sales.month(month, strict=True)))

    return router
