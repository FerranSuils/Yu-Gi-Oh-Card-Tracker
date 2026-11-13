import json
import os
from pathlib import Path

import pytest
import requests

from src.core.account_profile import AccountProfile, ShopProfile, save_profile
from src.services.shop import kiosk, shop_map
from src.services.shop.files import shop_path


class FakeHttp:
    def __init__(self, payload=None, status=200, error=None):
        self.payload, self.status, self.error, self.calls = payload, status, error, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        outer = self

        class Reply:
            status_code = outer.status

            def json(self):
                if isinstance(outer.payload, Exception):
                    raise outer.payload
                return outer.payload

        return Reply()


FOUND = [{'lat': '41.3874', 'lon': '2.1686', 'display_name': 'Carrer Fals 1, Barcelona'}]


def _profile(**shop):
    values = dict(name='Cartas Ana', address='Carrer Fals 1', city='Barcelona', country='España',
                  email='ana@example.com')
    values.update(shop)
    return AccountProfile(shop_mode=True, shop=ShopProfile(**values))


def _shop(root, profile=None):
    os.makedirs(root, exist_ok=True)
    save_profile(profile or _profile(), str(root))
    return str(root)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(shop_map, 'PAUSE_SECONDS', 0)
    kiosk.forget()
    yield
    kiosk.forget()


# --- geocoding -------------------------------------------------------------------------------

def test_geocoding_is_one_polite_request_to_nominatim():
    http = FakeHttp(FOUND)
    assert shop_map.geocode('Carrer Fals 1, Barcelona, España', http) == (41.3874, 2.1686)
    (url, kwargs), = http.calls
    assert url == 'https://nominatim.openstreetmap.org/search'
    assert kwargs['params'] == {'q': 'Carrer Fals 1, Barcelona, España', 'format': 'jsonv2', 'limit': 1}
    assert kwargs['headers'] == {'User-Agent': 'OpenYuGi/1.0'}
    assert kwargs['timeout'] <= 15
    assert '@' not in json.dumps(kwargs)


def test_an_address_nobody_knows_is_none():
    assert shop_map.geocode('Calle Inventada 999', FakeHttp([])) is None


@pytest.mark.parametrize('payload', [[{'lat': 'x', 'lon': '2'}], [{'lat': '91', 'lon': '2'}],
                                     [{'lat': '41', 'lon': '181'}], [{'lat': 'nan', 'lon': '2'}], [{}], ['x']])
def test_coordinates_that_make_no_sense_are_none(payload):
    assert shop_map.geocode('Carrer Fals 1', FakeHttp(payload)) is None


@pytest.mark.parametrize('http', [FakeHttp(error=requests.ConnectionError('dns')), FakeHttp(FOUND, status=503),
                                  FakeHttp(ValueError('not json')), FakeHttp({'error': 'x'})])
def test_a_map_service_that_is_down_is_said_as_such(http):
    with pytest.raises(shop_map.MapError) as failure:
        shop_map.geocode('Carrer Fals 1', http)
    assert str(failure.value) == 'No se pudo consultar el mapa. Inténtalo más tarde.'


# --- publishing ------------------------------------------------------------------------------

def test_publishing_keeps_name_address_and_coordinates_and_nothing_else(tmp_path):
    root = _shop(tmp_path / 'data')
    http = FakeHttp(FOUND)
    pin = shop_map.publish(root, _profile(), http)
    assert (pin.name, pin.address, pin.city, pin.country, pin.lat, pin.lon) == (
        'Cartas Ana', 'Carrer Fals 1', 'Barcelona', 'España', 41.3874, 2.1686)
    assert http.calls[0][1]['params']['q'] == 'Carrer Fals 1, Barcelona, España'
    stored = json.loads(Path(shop_path(root, 'map.json')).read_text(encoding='utf-8'))
    assert set(stored) == {'name', 'address', 'city', 'country', 'lat', 'lon'}
    assert 'example.com' not in json.dumps(stored)
    assert shop_map.published(root) == pin


def test_an_address_not_found_is_explained_and_not_published(tmp_path):
    root = _shop(tmp_path / 'data')
    with pytest.raises(shop_map.MapError) as failure:
        shop_map.publish(root, _profile(), FakeHttp([]))
    assert str(failure.value) == 'No se encontró esa dirección en el mapa. Revísala en los datos de la tienda.'
    assert shop_map.published(root) is None and shop_map.pins(root) == []


def test_with_the_network_down_nothing_is_published(tmp_path):
    root = _shop(tmp_path / 'data')
    with pytest.raises(shop_map.MapError):
        shop_map.publish(root, _profile(), FakeHttp(error=requests.Timeout('slow')))
    assert shop_map.published(root) is None


@pytest.mark.parametrize('missing', ['name', 'address', 'city'])
def test_a_shop_without_name_or_address_asks_for_them_before_calling_anyone(tmp_path, missing):
    root = _shop(tmp_path / 'data')
    http = FakeHttp(FOUND)
    with pytest.raises(shop_map.MapError) as failure:
        shop_map.publish(root, _profile(**{missing: '  '}), http)
    assert 'nombre, la dirección y la ciudad' in str(failure.value)
    assert http.calls == [] and shop_map.published(root) is None


def test_only_shops_appear_on_the_map(tmp_path):
    root = _shop(tmp_path / 'data')
    with pytest.raises(shop_map.MapError):
        shop_map.publish(root, AccountProfile(shop=_profile().shop), FakeHttp(FOUND))


def test_unpublishing_takes_the_shop_off_the_map(tmp_path):
    root = _shop(tmp_path / 'data')
    shop_map.publish(root, _profile(), FakeHttp(FOUND))
    assert len(shop_map.pins(root)) == 1
    shop_map.unpublish(root)
    assert shop_map.pins(root) == [] and shop_map.published(root) is None
    shop_map.unpublish(root)   # twice is fine


# --- the pins --------------------------------------------------------------------------------

def test_the_map_gathers_every_published_shop_with_its_kiosk_if_open(tmp_path):
    base = _shop(tmp_path / 'data')
    other = _shop(tmp_path / 'data' / 'users' / 'berta', _profile(name='Berta TCG', city='Vic'))
    _shop(tmp_path / 'data' / 'users' / 'carla')   # never published
    shop_map.publish(base, _profile(), FakeHttp(FOUND))
    shop_map.publish(other, _profile(name='Berta TCG', city='Vic'), FakeHttp([{'lat': '41.93', 'lon': '2.25'}]))
    token = kiosk.enable(other)
    pins = shop_map.pins(base)
    assert [(pin.name, pin.kiosk) for pin in pins] == [('Cartas Ana', None), ('Berta TCG', token)]


def test_a_shop_that_left_shop_mode_or_has_a_damaged_pin_is_not_shown(tmp_path):
    base = _shop(tmp_path / 'data')
    other = _shop(tmp_path / 'data' / 'users' / 'berta')
    third = _shop(tmp_path / 'data' / 'users' / 'carla')
    for root in (base, other, third):
        shop_map.publish(root, _profile(), FakeHttp(FOUND))
    save_profile(AccountProfile(shop_mode=False), other)
    Path(shop_path(third, 'map.json')).write_text('{"name": "x", "lat": 999', encoding='utf-8')
    assert [pin.name for pin in shop_map.pins(base)] == ['Cartas Ana']
    Path(shop_path(third, 'map.json')).write_text('{"name": "x", "lat": 999, "lon": 0}', encoding='utf-8')
    assert len(shop_map.pins(base)) == 1


# --- the page --------------------------------------------------------------------------------

def test_the_map_is_public_registered_and_drawn_with_openstreetmap_only():
    from src.services.auth_middleware import is_public_path
    from src.ui import shop_map as page

    assert is_public_path('/mapa') and not is_public_path('/mapas')
    assert "@ui.page('/mapa')" in Path('main.py').read_text(encoding='utf-8')
    assert page.TILES == 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
    assert 'OpenStreetMap' in page.ATTRIBUTION and 'openstreetmap.org/copyright' in page.ATTRIBUTION
    source = Path('src/ui/shop_map.py').read_text(encoding='utf-8').lower()
    for banned in ('carto', 'mapbox', 'googleapis', 'maptiler', 'stadia'):
        assert banned not in source
    assert 'filter' in page.MAP_CSS and 'data-oy-theme="dark"' in page.MAP_CSS
    for name in page.ICONS:
        assert Path('static/icons', f'{name}.svg').is_file(), name


def test_a_popup_cannot_carry_markup_from_a_shop_name():
    from src.ui.shop_map import popup_html

    pin = shop_map.Pin(name='<script>alert(1)</script>', address='Carrer "Fals" 1', city='Vic & Co', country='ES',
                       lat=41.9, lon=2.2, kiosk='a' * 32)
    html = popup_html(pin)
    assert '<script' not in html and '&lt;script&gt;' in html and 'Vic &amp; Co' in html
    assert f'href="/kiosko/{"a" * 32}"' in html
    assert 'href' not in popup_html(pin.model_copy(update={'kiosk': None}))


def test_the_map_opens_where_the_shops_are():
    from src.ui.shop_map import view

    assert view([]) == ((40.0, -3.7), 5)
    one = shop_map.Pin(name='a', lat=41.0, lon=2.0)
    assert view([one]) == ((41.0, 2.0), 13)
    centre, zoom = view([one, shop_map.Pin(name='b', lat=43.0, lon=-8.0)])
    assert centre == (42.0, -3.0) and zoom < 13


def test_settings_say_whether_the_shop_is_on_the_map():
    from src.ui.settings_shop import map_status

    assert map_status(None) == 'Tu tienda no aparece en el mapa.'
    pin = shop_map.Pin(name='Cartas Ana', address='Carrer Fals 1', city='Barcelona', lat=41.0, lon=2.0)
    assert map_status(pin) == 'En el mapa como «Cartas Ana», Carrer Fals 1, Barcelona.'
