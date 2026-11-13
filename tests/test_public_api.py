import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.account_profile import AccountProfile, save_profile
from src.core.order_models import Address, Order, OrderLine
from src.core.sales_models import Sale, SaleLine
from src.services.shop import api_keys
from src.services.shop.files import shop_path, write_list


@pytest.fixture(autouse=True)
def _fresh_index():
    api_keys.forget()
    yield
    api_keys.forget()


def _shop(root, shop_mode=True):
    os.makedirs(root, exist_ok=True)
    save_profile(AccountProfile(shop_mode=shop_mode), str(root))
    return str(root)


def _line(**changes):
    values = dict(name='Dark Hole', game='yugioh', collection='tienda.json', card_id='53129443', set_code='LOB-EN052',
                  rarity='Super Rare', variant_id='v1', quantity=3, unit_cents=250, storage_location='Caja 4')
    values.update(changes)
    return SaleLine(**values)


# --- keys ------------------------------------------------------------------------------------

def test_a_key_is_shown_once_and_only_its_hash_is_kept(tmp_path):
    root = _shop(tmp_path / 'data')
    key = api_keys.create(root)
    assert api_keys.KEY.fullmatch(key)
    stored = Path(shop_path(root, 'api.json')).read_text(encoding='utf-8')
    assert key not in stored and key[3:] not in stored
    assert api_keys.hint(root) == key[-4:]
    assert api_keys.account_for(key, root) == root


def test_a_new_key_retires_the_old_one(tmp_path):
    root = _shop(tmp_path / 'data')
    old = api_keys.create(root)
    assert api_keys.account_for(old, root) == root
    new = api_keys.create(root)
    assert api_keys.account_for(old, root) is None
    assert api_keys.account_for(new, root) == root


def test_a_revoked_key_opens_nothing(tmp_path):
    root = _shop(tmp_path / 'data')
    key = api_keys.create(root)
    assert api_keys.account_for(key, root) == root
    api_keys.revoke(root)
    assert api_keys.account_for(key, root) is None
    assert api_keys.hint(root) is None
    api_keys.revoke(root)   # twice is fine


def test_a_key_opens_its_own_account_only(tmp_path):
    base = _shop(tmp_path / 'data')
    other = _shop(tmp_path / 'data' / 'users' / 'berta')
    mine, theirs = api_keys.create(base), api_keys.create(other)
    api_keys.forget()   # as after a restart: found again on disk
    assert api_keys.account_for(theirs, base) == other
    assert api_keys.account_for(mine, base) == base


@pytest.mark.parametrize('bad', [None, '', 'oy_', 'oy_' + 'g' * 48, 'xx_' + 'a' * 48, 'oy_' + 'a' * 47, 42,
                                 'oy_' + 'a' * 48 + '\n'])
def test_nonsense_is_not_a_key(tmp_path, bad):
    root = _shop(tmp_path / 'data')
    api_keys.create(root)
    assert api_keys.account_for(bad, root) is None


def test_a_damaged_key_file_opens_nothing(tmp_path):
    root = _shop(tmp_path / 'data')
    key = api_keys.create(root)
    api_keys.forget()
    Path(shop_path(root, 'api.json')).write_text('{"hash": 7', encoding='utf-8')
    assert api_keys.account_for(key, root) is None
    assert api_keys.hint(root) is None


def test_sixty_requests_a_minute_and_no_more():
    limiter = api_keys.Limiter(limit=60, seconds=60)
    assert all(limiter.allow('k', now=float(second) / 2) for second in range(60))
    assert not limiter.allow('k', now=30.0)
    assert limiter.allow('other', now=30.0)
    assert limiter.allow('k', now=61.0)


# --- rows ------------------------------------------------------------------------------------

def test_stock_rows_show_priced_cards_without_where_they_are_kept():
    from src.services.shop.public_api import stock_rows

    rows = stock_rows([_line(), _line(storage_location='Caja 9', quantity=2), _line(name='Sin precio', unit_cents=0,
                                                                                     variant_id='v2')])
    assert len(rows) == 1
    row = rows[0]
    assert row['name'] == 'Dark Hole' and row['quantity'] == 5 and row['price_cents'] == 250
    assert row['set'] == 'LOB-EN052' and row['rarity'] == 'Super Rare' and row['game'] == 'yugioh'
    assert row['condition'] == 'Near Mint' and row['language'] == 'EN'
    assert row['sku'].startswith('OY-')
    assert 'Caja' not in json.dumps(rows) and 'tienda.json' not in json.dumps(rows)


def test_order_rows_keep_city_and_country_and_nothing_else_about_the_person():
    from src.services.shop.public_api import order_rows

    order = Order(number=7, channel='shopify', external_id='#1001', customer_name='Ana Secreta',
                  email='ana@example.com', customer_id='c1', note='llamar al 600111222', tracking='TRACK123',
                  address=Address(name='Ana Secreta', line1='Calle Falsa 123', line2='tel 600111222', postcode='08001',
                                  city='Barcelona', region='Cataluña', country='ES'),
                  lines=[OrderLine(name='Dark Hole', quantity=2, unit_cents=250, sku='OY-ABC')],
                  shipping_cents=300, total_cents=800, status='shipped', carrier='Correos')
    rows = order_rows([order])
    text = json.dumps(rows)
    for secret in ('Ana', 'ana@example.com', 'Calle Falsa', '08001', '600111222', 'TRACK123', 'c1"'):
        assert secret not in text, secret
    row = rows[0]
    assert row['number'] == 7 and row['city'] == 'Barcelona' and row['country'] == 'ES'
    assert row['status'] == 'shipped' and row['total_cents'] == 800 and row['shipping_cents'] == 300
    assert row['lines'] == [{'name': 'Dark Hole', 'game': 'yugioh', 'set': '', 'number': None, 'quantity': 2,
                             'price_cents': 250, 'sku': 'OY-ABC'}]


def test_sale_rows_are_the_paid_tickets_without_the_customer():
    from src.services.shop.public_api import sale_rows

    paid = Sale(number=3, lines=[_line(quantity=1)], total_cents=250, subtotal_cents=250, method='cash',
                status='paid', paid_at='2026-11-02T10:00:00+00:00', customer_id='c1', customer_name='Ana Secreta',
                note='para Ana')
    refunded = paid.model_copy(update={'number': 4, 'status': 'refunded'})
    pending = paid.model_copy(update={'number': 5, 'status': 'pending', 'stripe_url': 'https://pay/secret'})
    rows = sale_rows([paid, refunded, pending])
    assert [row['number'] for row in rows] == [3]
    text = json.dumps(rows)
    assert 'Ana' not in text and 'c1' not in text and 'Caja' not in text and 'secret' not in text
    assert rows[0]['total_cents'] == 250 and rows[0]['method'] == 'cash'
    assert rows[0]['lines'][0]['name'] == 'Dark Hole'


# --- over HTTP -------------------------------------------------------------------------------

@pytest.fixture
def served(tmp_path, monkeypatch):
    from src.services.shop import public_api

    base = _shop(tmp_path / 'data')
    other = _shop(tmp_path / 'data' / 'users' / 'berta')
    write_list(shop_path(base, 'orders.json'), [Order(number=1, customer_name='Ana Secreta', email='a@example.com',
                                                      address=Address(city='Vic', country='ES'), total_cents=100)])
    write_list(shop_path(other, 'orders.json'), [Order(number=9, address=Address(city='Lugo', country='ES'))])
    monkeypatch.setattr(public_api, 'stock_of', lambda root, profile: [_line()] if root == base else [])
    app = FastAPI()
    app.include_router(public_api.build_router(base))
    return TestClient(app), base, other


def _auth(key):
    return {'Authorization': f'Bearer {key}'}


def test_no_key_or_a_bad_one_is_401_and_says_nothing(served):
    client, base, _ = served
    key = api_keys.create(base)
    for headers in ({}, {'Authorization': 'Bearer'}, {'Authorization': 'Bearer oy_' + 'a' * 48},
                    {'Authorization': f'Basic {key}'}, {'Authorization': key}, {'Authorization': f'Bearer {key} x'},
                    {'Authorization': b'Bearer ' + 'ñ'.encode('utf-8') * 30}):
        for path in ('/api/v1/shop/stock', '/api/v1/shop/orders', '/api/v1/shop/sales'):
            answer = client.get(path, headers=headers)
            assert answer.status_code == 401, (headers, path)
            assert answer.json() == {'detail': 'Clave no válida.'}
            assert answer.headers['www-authenticate'] == 'Bearer'


def test_a_key_reads_its_own_shop_and_not_the_neighbours(served):
    client, base, other = served
    mine, theirs = api_keys.create(base), api_keys.create(other)
    orders = client.get('/api/v1/shop/orders', headers=_auth(mine))
    assert orders.status_code == 200
    assert [row['number'] for row in orders.json()['data']] == [1]
    assert 'Ana' not in orders.text and 'example.com' not in orders.text
    assert [row['number'] for row in client.get('/api/v1/shop/orders', headers=_auth(theirs)).json()['data']] == [9]
    stock = client.get('/api/v1/shop/stock', headers=_auth(mine)).json()['data']
    assert [row['name'] for row in stock] == ['Dark Hole']
    assert client.get('/api/v1/shop/stock', headers=_auth(theirs)).json() == {'data': []}


def test_a_revoked_key_is_401(served):
    client, base, _ = served
    key = api_keys.create(base)
    assert client.get('/api/v1/shop/stock', headers=_auth(key)).status_code == 200
    api_keys.revoke(base)
    assert client.get('/api/v1/shop/stock', headers=_auth(key)).status_code == 401


def test_a_key_stops_working_when_shop_mode_goes_off(served):
    client, base, _ = served
    key = api_keys.create(base)
    save_profile(AccountProfile(shop_mode=False), base)
    assert client.get('/api/v1/shop/stock', headers=_auth(key)).status_code == 401


def test_sales_of_a_month_with_empty_books_and_a_bad_month(served):
    client, base, _ = served
    key = api_keys.create(base)
    assert client.get('/api/v1/shop/sales', headers=_auth(key)).json() == {'data': []}
    assert client.get('/api/v1/shop/sales?month=2026-11', headers=_auth(key)).json() == {'data': []}
    for bad in ('2026-13', 'noviembre', '2026-1', '../2026-11'):
        answer = client.get('/api/v1/shop/sales', params={'month': bad}, headers=_auth(key))
        assert answer.status_code == 400, bad
        assert answer.json() == {'detail': 'El mes se escribe AAAA-MM.'}


def test_the_sixty_first_request_in_a_minute_is_429(served):
    client, base, _ = served
    key = api_keys.create(base)
    codes = [client.get('/api/v1/shop/orders', headers=_auth(key)).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429
    late = client.get('/api/v1/shop/orders', headers=_auth(key))
    assert late.json() == {'detail': 'Demasiadas peticiones. Espera un minuto.'}
    assert late.headers['retry-after'] == '60'


def test_a_damaged_book_is_a_500_that_leaks_nothing(served):
    client, base, _ = served
    key = api_keys.create(base)
    Path(shop_path(base, 'orders.json')).write_text('[{"number":', encoding='utf-8')
    answer = client.get('/api/v1/shop/orders', headers=_auth(key))
    assert answer.status_code == 500
    assert answer.json() == {'detail': 'No se pudieron leer los datos de la tienda.'}


# --- wiring ----------------------------------------------------------------------------------

def test_the_api_is_reachable_without_a_session_and_mounted():
    from src.services.auth_middleware import is_public_path

    assert is_public_path('/api/v1/shop/stock')
    assert not is_public_path('/api/v1/shopkeeper') and not is_public_path('/api/v1/collections')
    source = Path('main.py').read_text(encoding='utf-8')
    assert 'build_router' in source


def test_settings_show_only_the_end_of_the_key():
    from src.ui.settings_shop import ICONS, key_hint

    assert key_hint('ab12') == 'oy_…ab12'
    assert key_hint(None) == ''
    for name in ICONS:
        assert Path('static/icons', f'{name}.svg').is_file(), name


def test_a_damaged_month_of_sales_is_an_error_not_an_empty_month(served):
    import os
    client, base, _ = served
    os.makedirs(os.path.join(base, 'sales'), exist_ok=True)
    with open(os.path.join(base, 'sales', '2026-11.json'), 'w', encoding='utf-8') as file:
        file.write('{not json')
    answer = client.get('/api/v1/shop/sales?month=2026-11', headers=_auth(api_keys.create(base)))
    assert answer.status_code == 500
    assert answer.json() == {'detail': 'No se pudieron leer los datos de la tienda.'}
