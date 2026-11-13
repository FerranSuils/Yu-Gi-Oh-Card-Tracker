import os

import pytest

from src.core.order_models import Address, Order, OrderLine, ShippingMethod
from src.core.sales_models import OutOfStock
from src.services.orders.book import OrderBook, OrderError, pick_list, tracking_url
from src.services.shop.desk import desk_for
from src.services.shop.files import BrokenFile
from tests.test_sales_services import find, qty, shop  # noqa: F401  (fixture)

GAMES = ['yugioh', 'magic']
CORREOS = ShippingMethod(name='Correos certificado', carrier='Correos', cents=450,
                         tracking_url='https://example.test/track?n={code}')


@pytest.fixture
def book(shop):  # noqa: F811
    shop.book = OrderBook(str(shop.root), shop.inventory)
    return shop


def blue(shop, quantity=1):  # noqa: F811
    line = find(shop.inventory.items(GAMES), 'Blue-Eyes', condition='Near Mint')
    return OrderLine(**{**line.model_dump(), 'quantity': quantity})


def ragavan(shop, quantity=1):  # noqa: F811
    line = find(shop.inventory.items(GAMES), 'Ragavan')
    return OrderLine(**{**line.model_dump(), 'quantity': quantity})


# --- creating --------------------------------------------------------------------------------

def test_an_order_takes_its_cards_out_of_stock(book):
    order = book.book.create([blue(book, 2)], customer_name='Ana', method=CORREOS)
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 1
    assert (order.label, order.status, order.channel) == ('P00001', 'new', 'manual')
    assert (order.shipping_name, order.carrier, order.shipping_cents) == ('Correos certificado', 'Correos', 450)
    assert order.total_cents == 2 * 2500 + 450
    assert [o.id for o in book.book.all()] == [order.id]


def test_orders_are_numbered_in_a_row_and_listed_newest_first(book):
    first = book.book.create([blue(book)])
    second = book.book.create([ragavan(book)], paid=True)
    assert (first.label, second.label) == ('P00001', 'P00002')
    assert (second.status, bool(second.paid_at)) == ('paid', True)
    assert [o.label for o in book.book.all()] == ['P00002', 'P00001']


def test_an_order_asking_for_too_many_copies_changes_nothing(book):
    with pytest.raises(OutOfStock):
        book.book.create([ragavan(book, 1), blue(book, 9)])
    assert (qty(book, 'Ragavan'), qty(book, 'Blue-Eyes', condition='Near Mint')) == (2, 3)
    assert book.book.all() == []


def test_an_order_without_articles_is_refused(book):
    with pytest.raises(OrderError):
        book.book.create([])


def test_stock_comes_back_when_the_order_cannot_be_saved(book, monkeypatch):
    def fail(orders):
        raise OSError('disk full at C:/secret/path')
    monkeypatch.setattr(book.book, '_save', fail)
    with pytest.raises(OSError):
        book.book.create([blue(book, 2)])
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 3


def test_the_same_outside_order_does_not_enter_twice(book):
    book.book.create([blue(book)], channel='cardmarket', external_id='1234')
    with pytest.raises(OrderError):
        book.book.create([blue(book)], channel='cardmarket', external_id='1234')
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 2
    assert book.book.has('cardmarket', '1234') and not book.book.has('shopify', '1234')
    book.book.create([blue(book)], channel='shopify', external_id='1234')
    assert len(book.book.all()) == 2


def test_lines_nobody_linked_do_not_move_stock(book):
    loose = OrderLine(kind='custom', name='Dark Hole (LOB)', quantity=2, unit_cents=300, unlinked=True)
    order = book.book.create([blue(book), loose])
    assert (order.unlinked, order.total_cents) == (1, 2500 + 600)
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 2


def test_a_broken_order_file_is_left_alone(book):
    path = os.path.join(str(book.root), 'shop', 'orders.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file:
        file.write('{not json')
    with pytest.raises(BrokenFile):
        book.book.create([blue(book)])
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 3
    with open(path, encoding='utf-8') as file:
        assert file.read() == '{not json'


# --- the way to the door ---------------------------------------------------------------------

def test_an_order_walks_from_new_to_delivered(book):
    order = book.book.create([blue(book)], method=CORREOS)
    assert book.book.mark(order.id, 'paid').status == 'paid'
    assert book.book.mark(order.id, 'packed').status == 'packed'
    shipped = book.book.ship(order.id, 'Correos', ' PQ123 ')
    assert (shipped.status, shipped.carrier, shipped.tracking, bool(shipped.shipped_at)) == (
        'shipped', 'Correos', 'PQ123', True)
    done = book.book.mark(order.id, 'delivered')
    assert (done.status, bool(done.delivered_at)) == ('delivered', True)
    assert book.book.get(order.id).status == 'delivered'


def test_steps_cannot_be_skipped_backwards(book):
    order = book.book.create([blue(book)])
    with pytest.raises(OrderError):
        book.book.mark(order.id, 'delivered')
    with pytest.raises(OrderError):
        book.book.ship(order.id, 'Correos')        # not paid yet
    with pytest.raises(OrderError):
        book.book.mark('nope', 'paid')


def test_shipping_needs_a_carrier(book):
    order = book.book.create([blue(book)], paid=True)
    with pytest.raises(OrderError):
        book.book.ship(order.id, '  ')
    assert book.book.get(order.id).status == 'paid'


def test_the_tracking_link_comes_from_the_method(book):
    order = book.book.create([blue(book)], paid=True, method=CORREOS)
    shipped = book.book.ship(order.id, 'Correos', 'PQ 1&x=2')
    assert tracking_url(shipped) == 'https://example.test/track?n=PQ%201%26x%3D2'


def test_a_tracking_link_is_only_ever_https():
    for template in ('javascript:alert({code})', 'http://example.test/{code}', '', 'https://example.test/none'):
        order = Order(lines=[], tracking='A1', tracking_template=template)
        assert tracking_url(order) == ''
    assert tracking_url(Order(lines=[], tracking='', tracking_template='https://e.test/{code}')) == ''


def test_cancelling_puts_the_cards_back(book):
    order = book.book.create([blue(book, 2)], paid=True)
    cancelled = book.book.cancel(order.id)
    assert (cancelled.status, bool(cancelled.cancelled_at)) == ('cancelled', True)
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 3
    with pytest.raises(OrderError):
        book.book.cancel(order.id)
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 3


def test_a_shipped_order_cannot_be_cancelled_only_returned(book):
    order = book.book.create([blue(book, 2)], paid=True)
    book.book.ship(order.id, 'SEUR')
    with pytest.raises(OrderError):
        book.book.cancel(order.id)
    back = book.book.returned(order.id, restock=True)
    assert (back.status, back.restocked) == ('returned', True)
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 3


def test_a_return_that_never_came_back_leaves_stock_alone(book):
    order = book.book.create([blue(book, 2)], paid=True)
    book.book.ship(order.id, 'SEUR')
    assert book.book.returned(order.id, restock=False).restocked is False
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 1
    with pytest.raises(OrderError):
        book.book.returned(order.id, restock=True)


def test_a_cancel_that_cannot_be_saved_takes_the_cards_again(book, monkeypatch):
    order = book.book.create([blue(book, 2)], paid=True)
    monkeypatch.setattr(book.book, '_save', lambda orders: (_ for _ in ()).throw(OSError('x')))
    with pytest.raises(OSError):
        book.book.cancel(order.id)
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 1


# --- shipping methods ------------------------------------------------------------------------

def test_shipping_methods_start_with_the_usual_carriers(book):
    names = [method.carrier for method in book.book.methods()]
    assert {'Correos', 'SEUR', 'MRW', 'GLS', 'DHL', 'UPS', 'Royal Mail'} <= set(names)
    assert all(m.tracking_url.startswith('https://') and '{code}' in m.tracking_url for m in book.book.methods())


def test_shipping_methods_can_be_replaced(book):
    book.book.save_methods([CORREOS])
    assert [(m.name, m.cents) for m in book.book.methods()] == [('Correos certificado', 450)]


def test_a_method_with_a_strange_link_is_refused(book):
    with pytest.raises(OrderError):
        book.book.save_methods([ShippingMethod(name='X', carrier='X', tracking_url='http://x.test/{code}')])
    with pytest.raises(OrderError):
        book.book.save_methods([ShippingMethod(name=' ', carrier='X')])


# --- picking ---------------------------------------------------------------------------------

def test_the_pick_list_adds_up_piles_and_sorts_by_place(book):
    first = book.book.create([blue(book, 1), ragavan(book, 1)], paid=True)
    second = book.book.create([blue(book, 2)], paid=True)
    picks = pick_list([first, second])
    assert [(p.name[:9], p.storage_location, p.quantity, p.orders) for p in picks] == [
        ('Ragavan, ', None, 1, ['P00001']),
        ('Blue-Eyes', 'Caja A', 3, ['P00001', 'P00002']),
    ]


def test_the_pick_list_skips_lines_without_stock(book):
    loose = OrderLine(kind='custom', name='Fundas', unit_cents=300)
    order = book.book.create([loose], paid=True)
    assert pick_list([order]) == []


# --- wiring ----------------------------------------------------------------------------------

def test_the_desk_carries_the_order_book(tmp_path):
    desk = desk_for(str(tmp_path))
    assert isinstance(desk.dispatch, OrderBook)
    assert desk.dispatch.all() == []


def test_an_address_prints_only_the_lines_it_has():
    address = Address(name='Ana Ruiz', line1='Calle Mayor 1', postcode='08001', city='Barcelona', country='ES')
    assert address.lines() == ['Ana Ruiz', 'Calle Mayor 1', '08001 Barcelona', 'ES']
    assert Address().lines() == []
