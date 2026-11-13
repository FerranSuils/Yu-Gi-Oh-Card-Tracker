import json
import socket

import pytest
import requests

from src.services.orders.book import OrderBook
from src.services.orders.channels import ChannelError, ChannelSettings
from src.services.orders.importer import Article, Incoming
from src.services.orders.sku import sku_of
from tests.test_sales_services import find, qty, shop  # noqa: F401  (fixture)

GAMES = ['yugioh', 'magic']
TOKEN = 'shpat_0123456789abcdef0123456789abWXYZ'
CK = 'ck_0123456789abcdef0123456789abcdef0123KKKK'
CS = 'cs_0123456789abcdef0123456789abcdef0123SSSS'


class Reply:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}

        self.closed = False

    def iter_content(self, size=65536):
        data = b'<html>no</html>' if isinstance(self._body, Exception) else json.dumps(self._body).encode()
        for start in range(0, len(data), size):
            yield data[start:start + size]

    def close(self):
        self.closed = True


class FakeHttp:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def public(host, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]


def private(host, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.7', 443))]


@pytest.fixture
def book(shop):  # noqa: F811
    shop.book = OrderBook(str(shop.root), shop.inventory)
    shop.items = lambda: shop.inventory.items(GAMES)
    return shop


# --- Shopify ---------------------------------------------------------------------------------

def shopify(*replies):
    from src.services.orders.shopify import ShopifyClient

    http = FakeHttp(*replies)
    return ShopifyClient('cartas-sol.myshopify.com', TOKEN, http=http), http


SHOPIFY_ORDER = {
    'id': 'gid://shopify/Order/5001', 'name': '#1001', 'email': 'ana@example.test', 'currencyCode': 'EUR',
    'shippingAddress': {'name': 'Ana Ruiz', 'address1': 'Calle Mayor 1', 'address2': None, 'zip': '08001',
                        'city': 'Barcelona', 'province': 'Barcelona', 'countryCodeV2': 'ES'},
    'totalShippingPriceSet': {'shopMoney': {'amount': '3.90'}},
    'lineItems': {'nodes': [
        {'name': 'Blue-Eyes White Dragon', 'quantity': 2, 'sku': 'OY-AAAAAAAAAAAA',
         'originalUnitPriceSet': {'shopMoney': {'amount': '25.0'}}},
        {'name': 'Funda', 'quantity': 1, 'sku': None, 'originalUnitPriceSet': None}]},
}


def test_shopify_is_called_at_the_shops_own_admin_with_its_token_in_a_header():
    client, http = shopify(Reply(body={'data': {'shop': {'name': 'Cartas Sol'}}}))
    assert client.ping() == 'Cartas Sol'
    method, url, kwargs = http.calls[0]
    assert method == 'POST'
    assert url.startswith('https://cartas-sol.myshopify.com/admin/api/') and url.endswith('/graphql.json')
    assert kwargs['headers']['X-Shopify-Access-Token'] == TOKEN
    assert kwargs['allow_redirects'] is False and kwargs['timeout']
    assert TOKEN not in url and TOKEN not in repr(client)


def test_shopify_orders_come_paid_and_unshipped_with_their_articles():
    client, http = shopify(
        Reply(body={'data': {'orders': {'pageInfo': {'hasNextPage': True, 'endCursor': 'c1'},
                                        'nodes': [SHOPIFY_ORDER]}}}),
        Reply(body={'data': {'orders': {'pageInfo': {'hasNextPage': False, 'endCursor': None},
                                        'nodes': [{**SHOPIFY_ORDER, 'name': '#1002', 'shippingAddress': None,
                                                   'totalShippingPriceSet': None, 'email': None}]}}}))
    first, second = client.orders()
    assert (first.external_id, first.channel, first.customer_name, first.email, first.shipping_cents,
            first.currency) == ('#1001', 'shopify', 'Ana Ruiz', 'ana@example.test', 390, 'EUR')
    assert first.address.lines() == ['Ana Ruiz', 'Calle Mayor 1', '08001 Barcelona', 'Barcelona', 'ES']
    assert [(a.name, a.quantity, a.sku, a.unit_cents) for a in first.articles] == [
        ('Blue-Eyes White Dragon', 2, 'OY-AAAAAAAAAAAA', 2500), ('Funda', 1, '', 0)]
    assert (second.external_id, second.customer_name, second.shipping_cents) == ('#1002', '', 0)
    variables = [call[2]['json']['variables'] for call in http.calls]
    assert 'financial_status:paid' in variables[0]['query'] and 'fulfillment_status:unfulfilled' in variables[0]['query']
    assert variables[0]['after'] is None and variables[1]['after'] == 'c1'


def test_shopify_stops_asking_for_pages_at_some_point():
    endless = Reply(body={'data': {'orders': {'pageInfo': {'hasNextPage': True, 'endCursor': 'c'}, 'nodes': []}}})
    client, http = shopify(*[endless] * 50)
    assert client.orders() == []
    assert len(http.calls) <= 10


def test_shopify_stock_is_set_by_sku_and_unknown_skus_are_counted():
    client, http = shopify(
        Reply(body={'data': {'locations': {'nodes': [{'id': 'gid://shopify/Location/1'}]}}}),
        Reply(body={'data': {'productVariants': {'nodes': [
            {'sku': 'OY-AAAAAAAAAAAA', 'inventoryItem': {'id': 'gid://shopify/InventoryItem/11'}},
            {'sku': 'OY-CCCCCCCCCCCC', 'inventoryItem': {'id': 'gid://shopify/InventoryItem/13'}},
            {'sku': 'SOMETHING-ELSE', 'inventoryItem': {'id': 'gid://shopify/InventoryItem/99'}}]}}}),
        Reply(body={'data': {'inventorySetQuantities': {'userErrors': []}}}))
    report = client.push({'OY-AAAAAAAAAAAA': 3, 'OY-BBBBBBBBBBBB': 1, 'OY-CCCCCCCCCCCC': 0})
    assert sorted(report.updated) == ['OY-AAAAAAAAAAAA', 'OY-CCCCCCCCCCCC'] and report.missing == ['OY-BBBBBBBBBBBB']
    search = http.calls[1][2]['json']
    assert 'sku:"OY-AAAAAAAAAAAA"' in search['variables']['query']
    mutation = http.calls[2][2]['json']
    assert 'inventorySetQuantities' in mutation['query'] and '@idempotent' in mutation['query']
    assert mutation['variables']['key']
    given = mutation['variables']['input']
    assert (given['name'], given['reason']) == ('available', 'correction')
    assert sorted((q['inventoryItemId'], q['locationId'], q['quantity'], q['changeFromQuantity'])
                  for q in given['quantities']) == [
        ('gid://shopify/InventoryItem/11', 'gid://shopify/Location/1', 3, None),
        ('gid://shopify/InventoryItem/13', 'gid://shopify/Location/1', 0, None)]


def test_shopify_with_nothing_to_send_makes_no_call():
    client, http = shopify()
    report = client.push({})
    assert (report.updated, report.missing) == ([], []) and http.calls == []


def test_a_sku_that_could_break_the_search_is_never_sent():
    client, http = shopify(
        Reply(body={'data': {'locations': {'nodes': [{'id': 'gid://shopify/Location/1'}]}}}),
        Reply(body={'data': {'productVariants': {'nodes': []}}}))
    report = client.push({'OY-AAAAAAAAAAAA': 1, 'x" OR sku:*': 5})
    assert sorted(report.missing) == ['OY-AAAAAAAAAAAA', 'x" OR sku:*']
    assert ' OR sku:*' not in http.calls[1][2]['json']['variables']['query']


@pytest.mark.parametrize('reply, words', [
    (requests.ConnectionError(f'boom {TOKEN}'), 'conectar'),
    (Reply(401, {'errors': f'[API] Invalid API key or access token {TOKEN}'}), 'token'),
    (Reply(403, {'errors': 'forbidden'}), 'permiso'),
    (Reply(404, {'errors': 'Not Found'}), 'encuentro'),
    (Reply(302, {}, {'Location': 'http://10.0.0.1/'}), 'respondió'),
    (Reply(429, {}), 'demasiadas'),
    (Reply(200, ValueError('not json')), 'respondió'),
    (Reply(200, {'errors': [{'message': f'Access denied for orders field. {TOKEN}'}]}), 'Access denied'),
    (Reply(200, {'data': None}), 'respondió'),
])
def test_shopify_failures_are_worded_for_the_shop_and_never_carry_the_token(reply, words):
    client, _ = shopify(reply)
    with pytest.raises(ChannelError) as failure:
        client.ping()
    assert words.lower() in str(failure.value).lower() and TOKEN not in str(failure.value)
    assert failure.value.__cause__ is None


def test_shopify_user_errors_stop_the_push():
    client, _ = shopify(
        Reply(body={'data': {'locations': {'nodes': [{'id': 'gid://shopify/Location/1'}]}}}),
        Reply(body={'data': {'productVariants': {'nodes': [
            {'sku': 'OY-AAAAAAAAAAAA', 'inventoryItem': {'id': 'gid://shopify/InventoryItem/11'}}]}}}),
        Reply(body={'data': {'inventorySetQuantities': {'userErrors': [
            {'code': 'INVALID', 'field': ['input'], 'message': 'The quantity is not tracked'}]}}}))
    with pytest.raises(ChannelError, match='not tracked'):
        client.push({'OY-AAAAAAAAAAAA': 3})


# --- WooCommerce -----------------------------------------------------------------------------

def woo(*replies, resolve=public):
    from src.services.orders.woocommerce import WooClient

    http = FakeHttp(*replies)
    return WooClient('https://tienda.example.com', CK, CS, http=http, resolve=resolve), http


WOO_ORDER = {
    'id': 77, 'number': '1077', 'currency': 'EUR', 'shipping_total': '4.50',
    'billing': {'first_name': 'Bo', 'last_name': 'Li', 'email': 'bo@example.test'},
    'shipping': {'first_name': 'Bo', 'last_name': 'Li', 'address_1': 'Rambla 5', 'address_2': '2B',
                 'postcode': '43201', 'city': 'Reus', 'state': 'T', 'country': 'ES'},
    'line_items': [{'name': 'Dark Magician', 'quantity': 1, 'sku': 'OY-DDDDDDDDDDDD', 'price': 9.99},
                   {'name': 'Sin SKU', 'quantity': 2, 'sku': '', 'price': '1.50'}],
}


def test_woocommerce_is_called_over_basic_auth_without_following_redirects():
    client, http = woo(Reply(body=[]))
    client.ping()
    method, url, kwargs = http.calls[0]
    assert (method, url) == ('GET', 'https://tienda.example.com/wp-json/wc/v3/orders')
    assert kwargs['auth'] == (CK, CS) and kwargs['allow_redirects'] is False and kwargs['timeout']
    assert CS not in repr(client) and CK not in repr(client)


def test_woocommerce_orders_in_processing_come_with_their_articles():
    client, http = woo(Reply(body=[WOO_ORDER]))
    (order,) = client.orders()
    assert (order.external_id, order.channel, order.customer_name, order.email, order.shipping_cents,
            order.currency) == ('1077', 'woocommerce', 'Bo Li', 'bo@example.test', 450, 'EUR')
    assert order.address.lines() == ['Bo Li', 'Rambla 5', '2B', '43201 Reus', 'T', 'ES']
    assert [(a.name, a.quantity, a.sku, a.unit_cents) for a in order.articles] == [
        ('Dark Magician', 1, 'OY-DDDDDDDDDDDD', 999), ('Sin SKU', 2, '', 150)]
    assert http.calls[0][2]['params']['status'] == 'processing'


def test_woocommerce_stock_is_set_in_one_batch_by_product_id():
    client, http = woo(
        Reply(body=[{'id': 501, 'sku': 'OY-AAAAAAAAAAAA'}, {'id': 999, 'sku': 'NOT-ASKED'}]),
        Reply(body={'update': [{'id': 501, 'stock_quantity': 3}]}))
    report = client.push({'OY-AAAAAAAAAAAA': 3, 'OY-BBBBBBBBBBBB': 1})
    assert (report.updated, report.missing) == (['OY-AAAAAAAAAAAA'], ['OY-BBBBBBBBBBBB'])
    assert http.calls[0][1].endswith('/wp-json/wc/v3/products')
    assert set(http.calls[0][2]['params']['sku'].split(',')) == {'OY-AAAAAAAAAAAA', 'OY-BBBBBBBBBBBB'}
    method, url, kwargs = http.calls[1]
    assert (method, url) == ('POST', 'https://tienda.example.com/wp-json/wc/v3/products/batch')
    assert kwargs['json'] == {'update': [{'id': 501, 'manage_stock': True, 'stock_quantity': 3}]}


def test_a_product_woocommerce_refused_is_not_counted_as_updated():
    client, _ = woo(
        Reply(body=[{'id': 501, 'sku': 'OY-AAAAAAAAAAAA'}, {'id': 502, 'sku': 'OY-BBBBBBBBBBBB'}]),
        Reply(body={'update': [{'id': 501}, {'id': 502, 'error': {'code': 'x', 'message': 'no'}}]}))
    report = client.push({'OY-AAAAAAAAAAAA': 3, 'OY-BBBBBBBBBBBB': 1})
    assert (report.updated, report.missing) == (['OY-AAAAAAAAAAAA'], [])


def test_woocommerce_is_not_called_when_its_name_now_points_inside():
    client, http = woo(Reply(body=[]), resolve=private)
    with pytest.raises(ChannelError, match='privada'):
        client.ping()
    assert http.calls == []


@pytest.mark.parametrize('reply, words', [
    (requests.Timeout(f'slow {CS}'), 'conectar'),
    (Reply(301, {}, {'Location': 'http://169.254.169.254/'}), 'redirige'),
    (Reply(401, {'code': 'woocommerce_rest_cannot_view', 'message': f'nope {CS}'}), 'claves'),
    (Reply(404, {}), 'encuentro'),
    (Reply(500, {'message': f'<b>fatal</b> {CS}'}), 'respondió'),
    (Reply(200, ValueError('html page')), 'respondió'),
    (Reply(200, {'not': 'a list'}), 'respondió'),
])
def test_woocommerce_failures_are_worded_for_the_shop_and_never_carry_a_secret(reply, words):
    client, _ = woo(reply)
    with pytest.raises(ChannelError) as failure:
        client.ping()
    assert words.lower() in str(failure.value).lower()
    assert CS not in str(failure.value) and CK not in str(failure.value)


# --- the round trip --------------------------------------------------------------------------

class FakeShop:
    """An online shop that knows some SKUs."""

    def __init__(self, orders=(), known=None, fail_push=False):
        self.incoming = list(orders)
        self.known = known
        self.fail_push = fail_push
        self.pushes = []

    def orders(self):
        return list(self.incoming)

    def push(self, quantities):
        from src.services.orders.shopify import PushReport

        self.pushes.append(dict(quantities))
        if self.fail_push:
            raise ChannelError('La tienda no respondió.')
        known = set(quantities) if self.known is None else self.known
        return PushReport(updated=[s for s in quantities if s in known],
                          missing=[s for s in quantities if s not in known])


def bought(book, external_id='#1001', quantity=2):
    pile = find(book.items(), 'Blue-Eyes', condition='Near Mint')
    return Incoming(external_id=external_id, channel='shopify', customer_name='Ana',
                    articles=[Article(name='whatever the shop calls it', quantity=quantity, sku=sku_of(pile))])


def test_a_sync_enters_the_orders_and_then_sends_what_is_left(book):
    from src.services.orders.sync import sync

    pile = sku_of(find(book.items(), 'Blue-Eyes', condition='Near Mint'))
    online = FakeShop([bought(book)])
    report = sync(book.book, online, book.items, 'EUR', {})
    (order,) = book.book.all()
    assert (order.channel, order.external_id, order.status, order.unlinked) == ('shopify', '#1001', 'paid', 0)
    assert len(report.orders.created) == 1 and report.orders.skipped == 0
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 1
    assert online.pushes[0][pile] == 1 and len(online.pushes[0]) == 4
    assert (report.updated, report.missing, report.push_error) == (4, 0, '')
    assert report.pushed[pile] == 1


def test_a_second_sync_enters_nothing_twice_and_sends_only_what_changed(book):
    from src.services.orders.sync import sync

    online = FakeShop([bought(book)])
    first = sync(book.book, online, book.items, 'EUR', {})
    second = sync(book.book, online, book.items, 'EUR', first.pushed)
    assert len(book.book.all()) == 1 and second.orders.skipped == 1 and second.orders.created == []
    assert online.pushes[1] == {} and (second.updated, second.missing) == (0, 0)
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 1


def test_a_pile_that_sold_out_is_sent_as_zero_once(book):
    from src.services.orders.sync import sync

    pile = sku_of(find(book.items(), 'Blue-Eyes', condition='Near Mint'))
    online = FakeShop()
    first = sync(book.book, online, book.items, 'EUR', {})
    assert first.pushed[pile] == 3
    online.incoming = [bought(book, quantity=3)]
    second = sync(book.book, online, book.items, 'EUR', first.pushed)
    assert online.pushes[1] == {pile: 0}
    assert pile not in second.pushed            # nothing left to say about it
    third = sync(book.book, online, book.items, 'EUR', second.pushed)
    assert online.pushes[2] == {}
    assert third.updated == 0


def test_piles_the_shop_does_not_know_are_counted_and_tried_again(book):
    from src.services.orders.sync import sync

    pile = sku_of(find(book.items(), 'Blue-Eyes', condition='Near Mint'))
    online = FakeShop(known={pile})
    first = sync(book.book, online, book.items, 'EUR', {})
    assert (first.updated, first.missing) == (1, 3) and list(first.pushed) == [pile]
    second = sync(book.book, online, book.items, 'EUR', first.pushed)
    assert (second.updated, second.missing) == (0, 3) and pile not in online.pushes[1]


def test_when_sending_stock_fails_the_orders_stay_and_the_retry_does_not_repeat_them(book):
    from src.services.orders.sync import sync

    online = FakeShop([bought(book)], fail_push=True)
    report = sync(book.book, online, book.items, 'EUR', {})
    assert len(book.book.all()) == 1 and 'no respondió' in report.push_error
    assert report.pushed == {} and report.updated == 0
    online.fail_push = False
    again = sync(book.book, online, book.items, 'EUR', report.pushed)
    assert len(book.book.all()) == 1 and again.orders.skipped == 1 and again.updated == 4
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 1


def test_when_the_orders_cannot_be_read_nothing_is_touched(book):
    from src.services.orders.sync import sync

    class Down(FakeShop):
        def orders(self):
            raise ChannelError('No se pudo conectar con la tienda.')

    online = Down()
    with pytest.raises(ChannelError):
        sync(book.book, online, book.items, 'EUR', {})
    assert online.pushes == [] and book.book.all() == []


def test_an_order_for_more_than_there_is_comes_in_unlinked_and_takes_nothing(book):
    from src.services.orders.sync import sync

    online = FakeShop([bought(book, quantity=9)])
    report = sync(book.book, online, book.items, 'EUR', {})
    (order,) = book.book.all()
    assert order.unlinked == 1 and report.orders.unlinked == 1
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 3


# --- with the stored connection ---------------------------------------------------------------

def test_a_channel_is_only_connected_once_it_answers(book):
    from src.services.orders.sync import connect

    settings = ChannelSettings(str(book.root), resolve=public)
    with pytest.raises(ChannelError):
        connect(settings, 'shopify', 'x.myshopify.com', TOKEN, http=FakeHttp(Reply(401, {'errors': 'no'})))
    assert settings.summary() == {}
    name = connect(settings, 'shopify', 'x.myshopify.com', TOKEN,
                   http=FakeHttp(Reply(body={'data': {'shop': {'name': 'Cartas Sol'}}})))
    assert name == 'Cartas Sol' and settings.summary()['shopify']['last4'] == 'WXYZ'
    connect(settings, 'woocommerce', 'https://tienda.example.com', CK, CS, http=FakeHttp(Reply(body=[])))
    assert settings.summary()['woocommerce']['where'] == 'https://tienda.example.com'
    with pytest.raises(ChannelError):
        connect(settings, 'ebay', 'a', 'b')
    with pytest.raises(ChannelError):   # wrong shape never reaches the network
        connect(settings, 'shopify', 'evil.example.com', TOKEN, http=FakeHttp())


def test_syncing_a_stored_channel_remembers_what_it_sent_and_when(book):
    from src.services.orders import sync as module

    settings = ChannelSettings(str(book.root))
    with pytest.raises(ChannelError, match='conectada'):
        module.sync_channel(settings, 'shopify', book.book, book.items, 'EUR')
    settings.save_shopify('x.myshopify.com', TOKEN)
    online = FakeShop([bought(book)])
    report = module.sync_channel(settings, 'shopify', book.book, book.items, 'EUR', client=online)
    assert len(report.orders.created) == 1
    assert len(settings.pushed('shopify')) == 4 and not settings.due('shopify')
    module.sync_channel(settings, 'shopify', book.book, book.items, 'EUR', client=online)
    assert online.pushes[1] == {} and len(book.book.all()) == 1


def test_a_failed_push_is_not_stamped_so_it_is_tried_again_soon(book):
    from src.services.orders import sync as module

    settings = ChannelSettings(str(book.root))
    settings.save_shopify('x.myshopify.com', TOKEN)
    report = module.sync_channel(settings, 'shopify', book.book, book.items, 'EUR',
                                 client=FakeShop(fail_push=True))
    assert report.push_error and settings.due('shopify') and settings.pushed('shopify') == {}


def test_two_syncs_of_one_channel_never_run_at_once(book):
    from src.services.orders import sync as module

    settings = ChannelSettings(str(book.root))
    settings.save_shopify('x.myshopify.com', TOKEN)

    class Reentrant(FakeShop):
        def orders(self):
            with pytest.raises(ChannelError, match='sincronizando'):
                module.sync_channel(settings, 'shopify', book.book, book.items, 'EUR', client=FakeShop())
            return []

    module.sync_channel(settings, 'shopify', book.book, book.items, 'EUR', client=Reentrant())
