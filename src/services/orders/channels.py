"""The shop's own online shops (Shopify, WooCommerce): product files to load there, and the connection
kept in <cuenta>/shop/channels.json with its secrets sealed. Nothing here talks to the network."""

from __future__ import annotations

import csv
import io
import ipaddress
import json
import logging
import os
import re
import socket
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from src.core import secret_box
from src.core.sales_models import SaleLine, now_iso
from src.services.csv_suite import _guard
from src.services.orders.sku import sku_of
from src.services.shop.files import root_lock, shop_path

logger = logging.getLogger(__name__)

CHANNELS = ('shopify', 'woocommerce')
SYNC_MINUTES = 10
_SHOPIFY_DOMAIN = re.compile(r'[a-z0-9][a-z0-9-]{0,60}\.myshopify\.com')
_TOKEN = re.compile(r'[A-Za-z0-9_\-]{20,255}')
_WOO_KEY = re.compile(r'ck_[A-Za-z0-9]{16,128}')
_WOO_SECRET = re.compile(r'cs_[A-Za-z0-9]{16,128}')
_HOST = re.compile(r'[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?')
_PATH = re.compile(r'(/[A-Za-z0-9._~-]+)*')


class ChannelError(Exception):
    """Something about an online shop's connection, worded for the shop."""

    spoken = True


# --- product files ---------------------------------------------------------------------------

def title_of(item: SaleLine) -> str:
    """What the pile is called in an online shop: the card and what tells this pile from its siblings."""
    printing = ' '.join(part for part in (item.set_code, item.number or '') if part)
    parts = [item.name, printing, item.rarity, item.finish, item.condition, item.language,
             '1.ª edición' if item.first_edition else '']
    return ' · '.join(part for part in parts if part)[:255]


def _price(item: SaleLine) -> str:
    return f'{item.unit_cents / 100:.2f}'


def _table(headers: List[str], rows: Iterable[dict]) -> bytes:
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=headers, lineterminator='\r\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({name: _guard(row.get(name, '')) for name in headers})
    return out.getvalue().encode('utf-8')


_SHOPIFY_HEADERS = [
    'Handle', 'Title', 'Vendor', 'Type', 'Published', 'Option1 Name', 'Option1 Value', 'Variant SKU',
    'Variant Inventory Tracker', 'Variant Inventory Qty', 'Variant Inventory Policy',
    'Variant Fulfillment Service', 'Variant Price', 'Variant Requires Shipping', 'Variant Taxable', 'Status']
_WOO_HEADERS = ['Type', 'SKU', 'Name', 'Published', 'Visibility in catalog', 'In stock?', 'Stock',
                'Regular price', 'Categories']
_GAME_NAMES = {'yugioh': 'Yu-Gi-Oh!', 'magic': 'Magic: The Gathering', 'pokemon': 'Pokémon'}


def sellable(items: Iterable[SaleLine]) -> tuple[List[SaleLine], int]:
    """The piles that can go on sale online, because they have a price, and how many were left out."""
    items = list(items)
    priced = [item for item in items if item.unit_cents > 0]
    return priced, len(items) - len(priced)


def shopify_csv(items: Iterable[SaleLine], vendor: str = '') -> bytes:
    """Shopify's product import file: one product per priced pile, found again later by its SKU."""
    return _table(_SHOPIFY_HEADERS, ({
        'Handle': sku_of(item).lower(), 'Title': title_of(item), 'Vendor': vendor,
        'Type': _GAME_NAMES.get(item.game, item.game), 'Published': 'TRUE', 'Option1 Name': 'Title',
        'Option1 Value': 'Default Title', 'Variant SKU': sku_of(item), 'Variant Inventory Tracker': 'shopify',
        'Variant Inventory Qty': str(item.quantity), 'Variant Inventory Policy': 'deny',
        'Variant Fulfillment Service': 'manual', 'Variant Price': _price(item),
        'Variant Requires Shipping': 'TRUE', 'Variant Taxable': 'TRUE', 'Status': 'active'}
        for item in sellable(items)[0]))


def woocommerce_csv(items: Iterable[SaleLine]) -> bytes:
    """WooCommerce's product import file: one simple product per priced pile."""
    return _table(_WOO_HEADERS, ({
        'Type': 'simple', 'SKU': sku_of(item), 'Name': title_of(item), 'Published': '1',
        'Visibility in catalog': 'visible', 'In stock?': '1' if item.quantity > 0 else '0',
        'Stock': str(item.quantity), 'Regular price': _price(item),
        'Categories': _GAME_NAMES.get(item.game, item.game)} for item in sellable(items)[0]))


# --- where a shop of somebody else's may live -------------------------------------------------

def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split('%', 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, 'ipv4_mapped', None)
    if mapped is not None:
        ip = mapped
    return ip.is_global and not ip.is_multicast


def check_public_https(url: str, resolve: Optional[Callable] = None) -> str:
    """The tidy base address of an https site on the public internet, or a ChannelError.

    Every address the name resolves to must be public: this server must not be talked into calling
    itself, the machine next to it or a cloud metadata service."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
        host = (parts.hostname or '').lower().rstrip('.')
    except ValueError:
        raise ChannelError('La dirección de la tienda no es válida.') from None
    if parts.scheme.lower() != 'https':
        raise ChannelError('La dirección de la tienda debe empezar por https://')
    if parts.username is not None or parts.password is not None or '@' in parts.netloc:
        raise ChannelError('La dirección de la tienda no puede llevar usuario ni contraseña.')
    if parts.query or parts.fragment or port not in (None, 443):
        raise ChannelError('Escribe solo la dirección de la tienda, sin puerto ni parámetros.')
    path = parts.path.rstrip('/')
    if not host or len(host) > 253 or not _HOST.fullmatch(host) or not _PATH.fullmatch(path) or len(path) > 200:
        raise ChannelError('La dirección de la tienda no es válida.')
    try:
        answers = (resolve or socket.getaddrinfo)(host, 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise ChannelError('No encuentro esa dirección en internet.') from None
    addresses = [str(answer[4][0]) for answer in answers]
    if not addresses:
        raise ChannelError('No encuentro esa dirección en internet.')
    if not all(_is_public(address) for address in addresses):
        raise ChannelError('Esa dirección apunta a una red privada; la tienda debe estar en internet.')
    return f'https://{host}{path}'


def check_shopify(domain: str, token: str) -> Tuple[str, str]:
    """The tidy (domain, token) of a Shopify shop, or a ChannelError that never repeats the token."""
    domain, token = domain.strip().lower(), token.strip()
    if not _SHOPIFY_DOMAIN.fullmatch(domain):
        raise ChannelError('El dominio debe ser el de Shopify: tu-tienda.myshopify.com')
    if not _TOKEN.fullmatch(token):
        raise ChannelError('Eso no parece un token de la Admin API de Shopify (empieza por shpat_).')
    return domain, token


def check_woocommerce(url: str, key: str, secret: str, resolve: Optional[Callable] = None) -> Tuple[str, str, str]:
    """The tidy (address, key, secret) of a WooCommerce shop on the public internet, or a ChannelError."""
    key, secret = key.strip(), secret.strip()
    if not _WOO_KEY.fullmatch(key):
        raise ChannelError('La clave de cliente de WooCommerce empieza por ck_')
    if not _WOO_SECRET.fullmatch(secret):
        raise ChannelError('La clave secreta de WooCommerce empieza por cs_')
    return check_public_https(url, resolve=resolve), key, secret


# --- the connection on disk -------------------------------------------------------------------

class ChannelSettings:
    """What this account has connected. Secrets are sealed; `summary` is all a screen may show."""

    def __init__(self, root: str, resolve: Optional[Callable] = None, now: Callable[[], float] = time.time):
        self.root = root
        self._path = shop_path(root, 'channels.json')
        self.resolve = resolve
        self._resolve = resolve
        self._now = now
        self.lock = root_lock(root)

    # reading and writing

    def _read(self) -> Dict[str, dict]:
        try:
            with open(self._path, 'r', encoding='utf-8') as file:
                data = json.load(file)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.error('Canales: channels.json no se puede leer; hay que volver a conectar las tiendas.')
            return {}
        if not isinstance(data, dict):
            return {}
        return {name: entry for name, entry in data.items()
                if name in CHANNELS and isinstance(entry, dict) and entry.get('secrets')}

    def _write(self, data: Dict[str, dict]) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        temporary = self._path + '.tmp'
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
            json.dump(data, file)
        os.replace(temporary, self._path)

    @staticmethod
    def _known(channel: str) -> None:
        if channel not in CHANNELS:
            raise ChannelError('No conozco ese tipo de tienda.')

    def _connect(self, channel: str, where: str, last4: str, secrets: Dict[str, str]) -> None:
        with self.lock:
            data = self._read()
            data[channel] = {'where': where, 'last4': last4, 'secrets': secret_box.protect(json.dumps(secrets)),
                             'connected_at': now_iso(), 'synced_at': '', 'synced_ts': 0, 'pushed': {}}
            self._write(data)

    # connecting

    def save_shopify(self, domain: str, token: str) -> None:
        domain, token = check_shopify(domain, token)
        self._connect('shopify', domain, token[-4:], {'domain': domain, 'token': token})

    def save_woocommerce(self, url: str, key: str, secret: str) -> None:
        base, key, secret = check_woocommerce(url, key, secret, resolve=self._resolve)
        self._connect('woocommerce', base, key[-4:], {'url': base, 'key': key, 'secret': secret})

    def forget(self, channel: str) -> None:
        self._known(channel)
        with self.lock:
            data = self._read()
            if data.pop(channel, None) is not None:
                self._write(data)

    # what is connected

    def summary(self) -> Dict[str, dict]:
        """What may be shown on screen: where, the last four characters, and when. Never a secret."""
        return {channel: {name: str(entry.get(name) or '') for name in ('where', 'last4', 'connected_at',
                                                                        'synced_at')}
                for channel, entry in self._read().items()}

    def secrets(self, channel: str) -> Optional[Dict[str, str]]:
        self._known(channel)
        entry = self._read().get(channel)
        if not entry:
            return None
        try:
            secrets = json.loads(secret_box.reveal(str(entry['secrets'])))
        except (ValueError, UnicodeDecodeError, TypeError):
            logger.error('Canales: la conexión de %s no se puede leer; hay que volver a conectarla.', channel)
            return None
        if not isinstance(secrets, dict) or not all(isinstance(value, str) for value in secrets.values()):
            return None
        return secrets

    def client(self, channel: str, http=None):
        """Something that can talk to the connected shop, or None when it is not connected."""
        secrets = self.secrets(channel)
        if not secrets:
            return None
        try:
            if channel == 'shopify':
                from src.services.orders.shopify import ShopifyClient
                return ShopifyClient(secrets['domain'], secrets['token'], http=http)
            from src.services.orders.woocommerce import WooClient
            return WooClient(secrets['url'], secrets['key'], secrets['secret'], http=http, resolve=self._resolve)
        except KeyError:
            return None

    # when to talk again, and what was said last time

    def due(self, channel: str, minutes: int = SYNC_MINUTES) -> bool:
        self._known(channel)
        entry = self._read().get(channel)
        if not entry:
            return False
        try:
            last = float(entry.get('synced_ts') or 0)
        except (TypeError, ValueError):
            last = 0.0
        return not last or self._now() - last >= minutes * 60 or self._now() < last

    def _update(self, channel: str, **changes) -> None:
        self._known(channel)
        with self.lock:
            data = self._read()
            if channel in data:
                data[channel].update(changes)
                self._write(data)

    def stamp(self, channel: str) -> None:
        self._update(channel, synced_at=now_iso(), synced_ts=self._now())

    def pushed(self, channel: str) -> Dict[str, int]:
        """SKU → the quantity last sent to the shop, so only changes travel and sold-out piles go to zero."""
        self._known(channel)
        sent = (self._read().get(channel) or {}).get('pushed')
        if not isinstance(sent, dict):
            return {}
        return {str(sku): count for sku, count in sent.items() if isinstance(count, int) and count >= 0}

    def remember(self, channel: str, pushed: Dict[str, int]) -> None:
        self._update(channel, pushed=dict(pushed))
