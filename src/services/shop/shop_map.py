"""The public map of shops: a shop chooses to appear, its address is looked up once, and a pin is kept.

Only the name, address, town, country and coordinates are ever published.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from typing import List, Optional, Tuple

import requests
from pydantic import BaseModel, ValidationError, field_validator

from src.core.account_profile import AccountProfile, load_profile
from src.services.sales.store import _write
from src.services.shop import kiosk
from src.services.shop.files import root_lock, shop_path

logger = logging.getLogger(__name__)

FILE = 'map.json'
NOMINATIM = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = 'OpenYuGi/1.0'
PAUSE_SECONDS = 1.0   # Nominatim asks for no more than one request a second

DOWN = 'No se pudo consultar el mapa. Inténtalo más tarde.'
NOT_FOUND = 'No se encontró esa dirección en el mapa. Revísala en los datos de la tienda.'
INCOMPLETE = 'Rellena el nombre, la dirección y la ciudad de la tienda antes de aparecer en el mapa.'
NOT_A_SHOP = 'Activa el modo tienda para aparecer en el mapa.'

_polite = threading.Lock()
_last_call = [float('-inf')]


class MapError(Exception):
    """Something the person can read and act on."""


class Pin(BaseModel):
    name: str
    address: str = ''
    city: str = ''
    country: str = ''
    lat: float
    lon: float
    kiosk: Optional[str] = None   # never stored: read from the kiosk file when the map is drawn

    @field_validator('lat')
    @classmethod
    def _latitude(cls, value: float) -> float:
        if not math.isfinite(value) or not -90 <= value <= 90:
            raise ValueError('latitude')
        return value

    @field_validator('lon')
    @classmethod
    def _longitude(cls, value: float) -> float:
        if not math.isfinite(value) or not -180 <= value <= 180:
            raise ValueError('longitude')
        return value


def geocode(address: str, http=None) -> Optional[Tuple[float, float]]:
    """Where an address is, asked once to Nominatim. None when it does not know the place."""
    http = http or requests
    with _polite:
        wait = PAUSE_SECONDS - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        try:
            reply = http.get(NOMINATIM, params={'q': address, 'format': 'jsonv2', 'limit': 1},
                             headers={'User-Agent': USER_AGENT}, timeout=10)
            if reply.status_code != 200:
                raise MapError(DOWN)
            found = reply.json()
        except MapError:
            raise
        except (requests.RequestException, ValueError) as error:
            logger.error('Mapa: Nominatim no respondió: %s', type(error).__name__)
            raise MapError(DOWN) from None
    if not isinstance(found, list):
        raise MapError(DOWN)
    if not found or not isinstance(found[0], dict):
        return None
    try:
        lat, lon = float(found[0]['lat']), float(found[0]['lon'])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def publish(root: str, profile: AccountProfile, http=None) -> Pin:
    """Put the shop on the map where its address is. Raises MapError, and publishes nothing, when it cannot."""
    if not profile.shop_mode:
        raise MapError(NOT_A_SHOP)
    shop = profile.shop
    name, address, city, country = (shop.name.strip(), shop.address.strip(), shop.city.strip(), shop.country.strip())
    if not (name and address and city):
        raise MapError(INCOMPLETE)
    place = geocode(', '.join(part for part in (address, city, country) if part), http)
    if place is None:
        raise MapError(NOT_FOUND)
    pin = Pin(name=name, address=address, city=city, country=country, lat=place[0], lon=place[1])
    with root_lock(root):
        _write(shop_path(root, FILE), pin.model_dump(exclude={'kiosk'}))
    return pin


def unpublish(root: str) -> None:
    with root_lock(root):
        path = shop_path(root, FILE)
        if os.path.exists(path):
            os.remove(path)


def published(root: str) -> Optional[Pin]:
    """The pin of an account, or None when it is not on the map or its file is damaged."""
    try:
        with open(shop_path(root, FILE), 'r', encoding='utf-8') as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return None
        data.pop('kiosk', None)
        return Pin(**data)
    except (OSError, ValueError, TypeError, ValidationError):
        return None


def pins(base: str = 'data') -> List[Pin]:
    """Every shop that chose to be on the map and is still a shop."""
    from src.services.prices.scheduler import account_roots

    shown = []
    for root in account_roots(base):
        pin = published(root)
        if pin is None or not load_profile(root).shop_mode:
            continue
        shown.append(pin.model_copy(update={'kiosk': kiosk.token_of(root)}))
    return shown
