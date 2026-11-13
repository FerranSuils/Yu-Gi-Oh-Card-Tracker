"""The public kiosk: a secret link per shop, the priced stock it may show, and lists sent to the counter."""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from src.core.sales_models import SaleLine
from src.core.shop_models import KioskOrder
from src.services.sales.store import _write
from src.services.shop.files import BrokenFile, read_list, root_lock, shop_path, write_list

logger = logging.getLogger(__name__)

TOKEN = re.compile(r'[0-9a-f]{32}')
RESCAN_SECONDS = 5.0
MAX_OPEN = 30
MAX_LINES = 60
MAX_COPIES = 99
MAX_NAME = 40
MAX_PER_VISIT = 3
EXPIRES = timedelta(hours=24)


class KioskError(Exception):
    """Something the kiosk refuses, with a message a visitor can read."""

    spoken = True


class KioskClosed(KioskError):
    """The link no longer opens this shop: the kiosk was switched off or its link was changed."""

    def __init__(self, message: str = 'Este kiosko está cerrado. Pregunta en el mostrador.'):
        super().__init__(message)


# --- the secret link -------------------------------------------------------------------------

_guard = threading.Lock()
_index: Dict[str, str] = {}       # token -> account folder
_scanned: Dict[str, float] = {}   # base folder -> when it was last walked


def forget() -> None:
    with _guard:
        _index.clear()
        _scanned.clear()


def token_of(root: str) -> Optional[str]:
    """The kiosk token of an account, or None while its kiosk is closed."""
    try:
        with open(shop_path(root, 'kiosk.json'), 'r', encoding='utf-8') as file:
            token = json.load(file).get('token')
    except (OSError, ValueError, AttributeError):
        return None
    return token if isinstance(token, str) and TOKEN.fullmatch(token) else None


def _drop(root: str) -> None:
    for token in [t for t, r in _index.items() if r == root]:
        del _index[token]


def enable(root: str) -> str:
    """Open the kiosk with a fresh link. Any earlier link stops working."""
    token = secrets.token_hex(16)
    with root_lock(root):
        _write(shop_path(root, 'kiosk.json'), {'token': token})
    with _guard:
        _drop(root)
        _index[token] = root
    return token


def disable(root: str) -> None:
    with root_lock(root):
        path = shop_path(root, 'kiosk.json')
        if os.path.exists(path):
            os.remove(path)
    with _guard:
        _drop(root)


def _scan(base: str) -> Dict[str, str]:
    from src.services.prices.scheduler import account_roots

    found = {}
    for root in account_roots(base):
        token = token_of(root)
        if token:
            found[token] = root
    return found


def account_for(token, base: str = 'data') -> Optional[str]:
    """The account folder a kiosk link belongs to. Wrong guesses cost one disk walk every few seconds."""
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        return None
    with _guard:
        root = _index.get(token)
        if root is None and time.monotonic() - _scanned.get(base, float('-inf')) >= RESCAN_SECONDS:
            _scanned[base] = time.monotonic()
            try:
                _index.update(_scan(base))
            except OSError as error:
                logger.error('Kiosko: no se pudieron leer las cuentas: %s', type(error).__name__)
            root = _index.get(token)
        if root is None:
            return None
        current = token_of(root)  # the file is the truth: the link may have been regenerated or closed
        if current is None or not hmac.compare_digest(current, token):
            _index.pop(token, None)
            return None
        return root


def ensure_open(token, root: str) -> None:
    """Raise KioskClosed unless this link still opens this shop. Pages left open ask before every action."""
    from src.core.account_profile import load_profile

    current = token_of(root)
    if not isinstance(token, str) or current is None or not hmac.compare_digest(current, token):
        raise KioskClosed()
    if not load_profile(root).shop_mode:
        raise KioskClosed()


# --- keeping the queue for real customers ----------------------------------------------------

class Visit:
    """One open kiosk page. It may send a few lists, not a stream of them."""

    def __init__(self, limit: int = MAX_PER_VISIT):
        self._limit = limit
        self._count = 0

    def check(self) -> None:
        if self._count >= self._limit:
            raise KioskError('Ya has enviado varias listas. Acércate al mostrador para pedir más.')

    def sent(self) -> None:
        self._count += 1


class Throttle:
    """At most `limit` lists per key (shop and address) in a sliding window. In memory: a restart forgets."""

    def __init__(self, limit: int = 10, seconds: float = 600):
        self._limit = limit
        self._seconds = seconds
        self._lock = threading.Lock()
        self._seen: Dict[str, List[float]] = {}

    def spend(self, key: str, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            for other in [k for k, times in self._seen.items() if not times or now - times[-1] >= self._seconds]:
                del self._seen[other]
            recent = [t for t in self._seen.get(key, []) if now - t < self._seconds]
            if len(recent) >= self._limit:
                self._seen[key] = recent
                raise KioskError('Se han enviado muchas listas desde aquí. Acércate al mostrador y pídelo allí.')
            self._seen[key] = recent + [now]


def address_of(headers, fallback: str = '') -> str:
    """Who is asking. The proxy in front appends the real address as the last X-Forwarded-For entry."""
    last = (headers.get('x-forwarded-for') or '').split(',')[-1].strip()
    if last.count(':') == 1:  # IPv4 with a port
        last = last.split(':')[0]
    return (last or fallback or 'unknown')[:64]


# --- what the public sees --------------------------------------------------------------------

def _public_key(line: SaleLine) -> tuple:
    return (line.game, line.collection, line.card_id, line.variant_id, line.finish, line.condition, line.language,
            line.first_edition)


def shelf(items: List[SaleLine]) -> List[SaleLine]:
    """Priced stock only, without where it is kept. Piles that differ only in storage show as one."""
    merged: Dict[tuple, SaleLine] = {}
    for line in items:
        if line.kind != 'stock' or line.unit_cents <= 0:
            continue
        key = (*_public_key(line), line.unit_cents)
        if key in merged:
            merged[key].quantity += line.quantity
        else:
            merged[key] = line.model_copy(update={'storage_location': None})
    return list(merged.values())


def fit_to_stock(wanted: List[SaleLine], items: List[SaleLine]) -> Tuple[List[SaleLine], List[str]]:
    """Turn a kiosk list into ticket lines on the real piles, at today's prices. Nothing was reserved."""
    piles: Dict[tuple, List[SaleLine]] = {}
    for line in items:
        if line.kind == 'stock' and line.unit_cents > 0:
            piles.setdefault(_public_key(line), []).append(line.model_copy())
    lines, short = [], []
    for want in wanted:
        left = want.quantity
        for pile in piles.get(_public_key(want), []):
            take = min(left, pile.quantity)
            if take <= 0:
                continue
            lines.append(pile.model_copy(update={'quantity': take}))
            pile.quantity -= take  # pydantic does not re-validate on assignment: 0 marks the pile as used up
            left -= take
        got = want.quantity - left
        if got == 0:
            short.append(f'{want.name} (ya no queda)')
        elif left:
            short.append(f'{want.name} (pedía {want.quantity}, quedan {got})')
    return lines, short


# --- lists sent to the counter ---------------------------------------------------------------

def _clean_name(name) -> str:
    if not isinstance(name, str):
        return ''
    text = ''.join(' ' if unicodedata.category(ch).startswith('C') else ch for ch in name)
    return ' '.join(text.split())[:MAX_NAME].strip()


def _utc(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _alive(order: KioskOrder, now: datetime) -> bool:
    if order.status != 'open':
        return False
    try:
        return now - datetime.fromisoformat(order.created_at) < EXPIRES
    except (TypeError, ValueError):
        return False


class KioskOrders:
    def __init__(self, root: str):
        self._path = shop_path(root, 'kiosk_orders.json')
        self.lock = root_lock(root)

    def _live(self, now: datetime) -> List[KioskOrder]:
        try:
            return [order for order in read_list(self._path, KioskOrder) if _alive(order, now)]
        except BrokenFile as error:
            raise KioskError('El kiosko no está disponible ahora mismo. Pregunta en el mostrador.') from error

    def open(self, now: Optional[datetime] = None) -> List[KioskOrder]:
        """Lists waiting at the counter, oldest first."""
        return sorted(self._live(_utc(now)), key=lambda order: order.created_at)

    def add(self, name, lines: List[SaleLine], now: Optional[datetime] = None) -> KioskOrder:
        now = _utc(now)
        name = _clean_name(name)
        if not name:
            raise KioskError('Escribe tu nombre para que el mostrador sepa de quién es la lista.')
        if not lines:
            raise KioskError('Tu lista está vacía.')
        if len(lines) > MAX_LINES:
            raise KioskError(f'Una lista admite {MAX_LINES} cartas distintas como mucho.')
        for line in lines:
            if line.kind != 'stock' or line.unit_cents <= 0 or line.quantity > MAX_COPIES:
                raise KioskError(f'{line.name}: no se puede pedir desde el kiosko.')
        with self.lock:
            live = self._live(now)
            if len(live) >= MAX_OPEN:
                raise KioskError('El mostrador tiene muchas listas esperando. Acércate y pídelo allí.')
            used = {order.code for order in live}
            code = next(c for c in (f'{secrets.randbelow(10000):04d}' for _ in iter(int, 1)) if c not in used)
            order = KioskOrder(code=code, name=name, created_at=now.isoformat(timespec='seconds'),
                               lines=[line.model_copy(update={'storage_location': None}) for line in lines])
            write_list(self._path, live + [order])
        return order

    def get(self, order_id: str, now: Optional[datetime] = None) -> KioskOrder:
        """Look at a waiting list without taking it out of the queue."""
        order = next((o for o in self._live(_utc(now)) if o.id == order_id), None)
        if order is None:
            raise KioskError('Esa lista ya no está: se cargó antes o ha caducado.')
        return order

    def discard(self, order_id: str, now: Optional[datetime] = None) -> KioskOrder:
        """The counter throws a list away (nobody came, or it was a prank)."""
        return self.take(order_id, now)

    def take(self, order_id: str, now: Optional[datetime] = None) -> KioskOrder:
        """The counter picks a list up: it leaves the queue."""
        with self.lock:
            live = self._live(_utc(now))
            order = next((o for o in live if o.id == order_id), None)
            if order is None:
                raise KioskError('Esa lista ya no está: se cargó antes o ha caducado.')
            write_list(self._path, [o for o in live if o.id != order_id])
        order.status = 'taken'
        return order
