"""The order book of one account: orders to ship, the stock they hold, and how they travel."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Iterable, List, Optional
from urllib.parse import quote

from src.core.order_models import Address, Order, OrderLine, ShippingMethod
from src.core.sales_models import now_iso
from src.services.sales.inventory import Inventory, line_key
from src.services.sales.store import _write
from src.services.shop.files import read_list, root_lock, shop_path, write_list

logger = logging.getLogger(__name__)

_TEMPLATES = (
    ('Correos', 'https://www.correos.es/es/es/herramientas/localizador/envios/detalle?tracking-number={code}'),
    ('SEUR', 'https://www.seur.com/livetracking/?segOnlineIdentificador={code}'),
    ('MRW', 'https://www.mrw.es/seguimiento_envios/MRW_resultados_consultas.asp?modo=nacional&envio={code}'),
    ('GLS', 'https://www.gls-spain.es/es/recibir-paquetes/seguimiento-envio/?match={code}'),
    ('DHL', 'https://www.dhl.com/es-es/home/tracking.html?tracking-id={code}'),
    ('UPS', 'https://www.ups.com/track?tracknum={code}'),
    ('Royal Mail', 'https://www.royalmail.com/track-your-item#/tracking-results/{code}'),
)
# What each step may follow. Shipping, cancelling and returning have their own doors.
_STEPS = {'paid': ('new',), 'packed': ('paid',), 'delivered': ('shipped',)}
_STAMP = {'paid': 'paid_at', 'packed': 'packed_at', 'delivered': 'delivered_at'}


class OrderError(Exception):
    """Something about an order that the person at the desk can fix."""

    spoken = True


@dataclass
class Pick:
    """One pile to visit when preparing orders."""
    name: str
    set_code: str
    game: str
    collection: str
    storage_location: Optional[str]
    condition: str
    language: str
    first_edition: bool
    quantity: int = 0
    rarity: str = ''
    orders: List[str] = field(default_factory=list)


def default_methods() -> List[ShippingMethod]:
    return [ShippingMethod(id=name.lower().replace(' ', '-'), name=name, carrier=name, tracking_url=url)
            for name, url in _TEMPLATES]


def tracking_url(order: Order) -> str:
    """Where to follow the parcel, or '' when there is no number or no trustworthy template."""
    template, code = order.tracking_template.strip(), order.tracking.strip()
    if not code or not template.startswith('https://') or '{code}' not in template:
        return ''
    return template.replace('{code}', quote(code, safe=''))


def pick_list(orders: Iterable[Order]) -> List[Pick]:
    """The piles to visit for these orders, added up and in walking order (place, collection, name)."""
    picks: dict[tuple, Pick] = {}
    for order in orders:
        for line in order.lines:
            if line.kind != 'stock':
                continue
            pick = picks.setdefault(line_key(line), Pick(
                name=line.name, set_code=line.set_code, game=line.game, collection=line.collection,
                storage_location=line.storage_location, condition=line.condition, language=line.language,
                first_edition=line.first_edition, rarity=line.rarity))
            pick.quantity += line.quantity
            if order.label not in pick.orders:
                pick.orders.append(order.label)
    return sorted(picks.values(), key=lambda pick: (
        (pick.storage_location or '').lower(), pick.collection.lower(), pick.name.lower(), pick.set_code))


class OrderBook:
    def __init__(self, root: str, inventory: Inventory):
        self._inventory = inventory
        self._path = shop_path(root, 'orders.json')
        self._counter = shop_path(root, 'orders-counter.json')
        self._shipping = shop_path(root, 'shipping.json')
        self.lock = root_lock(root)

    # --- reading -----------------------------------------------------------------------------

    def _read(self) -> List[Order]:
        return read_list(self._path, Order)

    def _save(self, orders: List[Order]) -> None:
        write_list(self._path, orders)

    def all(self) -> List[Order]:
        """Every order, newest first."""
        return sorted(self._read(), key=lambda order: (order.created_at, order.number or 0), reverse=True)

    def get(self, order_id: str) -> Optional[Order]:
        return next((order for order in self._read() if order.id == order_id), None)

    def has(self, channel: str, external_id: str) -> bool:
        reference = external_id.strip()
        return bool(reference) and any(
            order.channel == channel and order.external_id == reference for order in self._read())

    # --- creating ----------------------------------------------------------------------------

    def _next_number(self, orders: List[Order]) -> int:
        used = max((order.number or 0 for order in orders), default=0)
        try:
            with open(self._counter, 'r', encoding='utf-8') as file:
                used = max(used, int(json.load(file).get('last', 0)))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        _write(self._counter, {'last': used + 1})
        return used + 1

    def create(self, lines: List[OrderLine], *, channel: str = 'manual', external_id: str = '',
               customer_name: str = '', email: str = '', address: Optional[Address] = None,
               method: Optional[ShippingMethod] = None, shipping_cents: Optional[int] = None,
               currency: str = 'EUR', paid: bool = False, note: str = '',
               customer_id: Optional[str] = None, charged_cents: int = 0) -> Order:
        """Writes the order down and takes its cards out of stock: both happen, or neither."""
        lines = [OrderLine(**line.model_dump()) for line in lines]
        if not lines:
            raise OrderError('El pedido no tiene artículos.')
        reference = external_id.strip()
        postage = method.cents if shipping_cents is None and method else (shipping_cents or 0)
        if postage < 0:
            raise OrderError('El envío no puede costar menos de cero.')
        with self.lock:
            orders = self._read()   # a file we cannot read stops us before any card moves
            if reference and any(o.channel == channel and o.external_id == reference for o in orders):
                raise OrderError('Ese pedido ya está en la lista.')
            now = now_iso()
            order = Order(
                channel=channel, external_id=reference, customer_id=customer_id,
                customer_name=customer_name.strip(), email=email.strip(), address=address or Address(),
                lines=lines, shipping_name=method.name if method else '', carrier=method.carrier if method else '',
                tracking_template=method.tracking_url if method else '', shipping_cents=postage,
                total_cents=sum(line.total_cents for line in lines) + postage,
                charged_cents=max(0, charged_cents), currency=currency,
                status='paid' if paid else 'new', paid_at=now if paid else None, note=note.strip(), created_at=now)
            self._inventory.take(lines)
            try:
                order.number = self._next_number(orders)
                self._save(orders + [order])
            except Exception:
                self._back(lines)
                raise
            return order

    def _back(self, lines: List[OrderLine]) -> None:
        try:
            self._inventory.give_back(lines)
        except Exception as error:  # the first failure is the one worth telling
            logger.error('Pedidos: no se pudo devolver el stock: %s', type(error).__name__)

    # --- moving along ------------------------------------------------------------------------

    def _change(self, order_id: str, allowed: tuple, refusal: str) -> tuple[List[Order], Order]:
        orders = self._read()
        order = next((item for item in orders if item.id == order_id), None)
        if order is None:
            raise OrderError('Ese pedido ya no existe.')
        if order.status not in allowed:
            raise OrderError(refusal)
        return orders, order

    def mark(self, order_id: str, status: str) -> Order:
        """Cobrado, preparado or entregado: one step forward, never a jump."""
        if status not in _STEPS:
            raise OrderError('Ese paso no existe.')
        with self.lock:
            orders, order = self._change(order_id, _STEPS[status], 'Ese pedido no está en el paso anterior.')
            order.status = status
            setattr(order, _STAMP[status], now_iso())
            self._save(orders)
            return order

    def ship(self, order_id: str, carrier: str, tracking: str = '') -> Order:
        carrier = carrier.strip()
        if not carrier:
            raise OrderError('Indica con qué transportista sale.')
        with self.lock:
            orders, order = self._change(order_id, ('paid', 'packed'),
                                         'Solo se envía un pedido cobrado y sin enviar.')
            if carrier != order.carrier:
                known = next((m for m in self.methods() if m.carrier.lower() == carrier.lower()), None)
                order.tracking_template = known.tracking_url if known else ''
            order.carrier, order.tracking = carrier, tracking.strip()
            order.status, order.shipped_at = 'shipped', now_iso()
            self._save(orders)
            return order

    def _restock(self, orders: List[Order], order: Order) -> None:
        """Puts the order's cards back and saves; if saving fails the cards leave again."""
        self._inventory.give_back(order.lines)
        try:
            self._save(orders)
        except Exception:
            try:
                self._inventory.take(order.lines)
            except Exception as error:
                logger.error('Pedidos: no se pudo deshacer la devolución de stock: %s', type(error).__name__)
            raise

    def cancel(self, order_id: str) -> Order:
        with self.lock:
            orders, order = self._change(order_id, ('new', 'paid', 'packed'),
                                         'Ese pedido ya salió o ya está anulado. Si ha vuelto, anota la devolución.')
            order.status, order.cancelled_at, order.restocked = 'cancelled', now_iso(), True
            self._restock(orders, order)
            return order

    def returned(self, order_id: str, restock: bool) -> Order:
        with self.lock:
            orders, order = self._change(order_id, ('shipped', 'delivered'),
                                         'Solo se devuelve un pedido que ya salió.')
            order.status, order.returned_at, order.restocked = 'returned', now_iso(), bool(restock)
            if restock:
                self._restock(orders, order)
            else:
                self._save(orders)
            return order

    # --- shipping methods --------------------------------------------------------------------

    def methods(self) -> List[ShippingMethod]:
        if not os.path.exists(self._shipping):
            return default_methods()
        return read_list(self._shipping, ShippingMethod)

    def save_methods(self, methods: List[ShippingMethod]) -> None:
        clean = []
        for method in methods:
            name, link = method.name.strip(), method.tracking_url.strip()
            if not name:
                raise OrderError('Cada método de envío necesita un nombre.')
            if link and (not link.startswith('https://') or '{code}' not in link):
                raise OrderError(f'El enlace de seguimiento de {name} debe empezar por https:// y llevar {{code}}.')
            clean.append(method.model_copy(update={
                'name': name, 'carrier': method.carrier.strip() or name, 'tracking_url': link}))
        with self.lock:
            write_list(self._shipping, clean)
