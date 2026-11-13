import pytest

from src.core.sales_models import Discount, SaleLine
from src.services.sales.checkout import Checkout, SaleError
from src.services.shop.consignment import ConsignmentBook, ConsignmentError
from src.services.shop.customers import CustomerStore
from tests.test_sales_services import find, qty, shop  # noqa: F401  (fixture)


@pytest.fixture
def desk(shop):  # noqa: F811
    customers = CustomerStore(str(shop.root))
    book = ConsignmentBook(str(shop.root), customers)
    shop.customers, shop.book = customers, book
    shop.checkout = Checkout(shop.inventory, shop.store, customers=customers, consignments=book)
    shop.ana = customers.add('Ana')
    return shop


def line(desk, name, quantity=1, **fields):
    return find(desk.inventory.items(['yugioh', 'magic']), name, **fields).model_copy(update={'quantity': quantity})


# --- store credit at the counter -------------------------------------------------------------

def test_paying_with_store_credit_spends_the_balance(desk):
    desk.customers.post(desk.ana.id, 'credit', 3000, 'Compra')
    sale = desk.checkout.charge([line(desk, 'Blue-Eyes', condition='Near Mint')], Discount(), 'credit', 'EUR',
                                customer_id=desk.ana.id)
    assert (sale.status, sale.method, sale.total_cents, sale.customer_id, sale.customer_name) == (
        'paid', 'credit', 2500, desk.ana.id, 'Ana')
    assert desk.customers.balance(desk.ana.id, 'credit') == 500
    entry = desk.customers.entries(desk.ana.id)[0]
    assert (entry.cents, entry.ref, entry.reason) == (-2500, sale.id, 'Venta 000001')
    assert qty(desk, 'Blue-Eyes', condition='Near Mint') == 2


def test_not_enough_credit_sells_nothing(desk):
    desk.customers.post(desk.ana.id, 'credit', 2499, 'Compra')
    with pytest.raises(SaleError) as error:
        desk.checkout.charge([line(desk, 'Blue-Eyes', condition='Near Mint')], Discount(), 'credit', 'EUR',
                             customer_id=desk.ana.id)
    assert 'Saldo insuficiente' in str(error.value)
    assert desk.customers.balance(desk.ana.id, 'credit') == 2499
    assert qty(desk, 'Blue-Eyes', condition='Near Mint') == 3 and desk.store.months() == []


@pytest.mark.parametrize('customer', [None, 'nobody'])
def test_credit_needs_a_known_customer(desk, customer):
    with pytest.raises(SaleError):
        desk.checkout.charge([line(desk, 'Dark')], Discount(), 'credit', 'EUR', customer_id=customer)
    assert qty(desk, 'Dark') == 2


def test_credit_without_a_customer_book_is_refused(shop):  # noqa: F811
    with pytest.raises(SaleError):
        shop.checkout.charge([find(shop.inventory.items(['yugioh']), 'Dark')], Discount(), 'credit', 'EUR',
                             customer_id='x')


def test_refunding_a_credit_sale_puts_the_credit_back_once(desk):
    desk.customers.post(desk.ana.id, 'credit', 3000, 'Compra')
    sale = desk.checkout.charge([line(desk, 'Dark')], Discount(), 'credit', 'EUR', customer_id=desk.ana.id)
    assert desk.customers.balance(desk.ana.id, 'credit') == 2001
    desk.checkout.refund(sale.id)
    assert desk.customers.balance(desk.ana.id, 'credit') == 3000 and qty(desk, 'Dark') == 2
    with pytest.raises(SaleError):
        desk.checkout.refund(sale.id)
    assert desk.customers.balance(desk.ana.id, 'credit') == 3000


def test_a_cash_sale_can_carry_the_customer(desk):
    sale = desk.checkout.charge([line(desk, 'Dark')], Discount(), 'cash', 'EUR', received_cents=1000,
                                customer_id=desk.ana.id)
    assert (sale.customer_id, sale.customer_name) == (desk.ana.id, 'Ana')
    assert desk.customers.entries(desk.ana.id) == []


# --- consignment -----------------------------------------------------------------------------

def test_open_a_consignment_on_a_collection(desk):
    con = desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 25)
    assert desk.book.of('yugioh', 'vitrina.json').id == con.id
    assert desk.book.of('magic', 'magic.json') is None
    with pytest.raises(ConsignmentError):
        desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 10)  # already consigned
    with pytest.raises(ConsignmentError):
        desk.book.open('nobody', 'magic', 'magic.json', 10)
    with pytest.raises(ConsignmentError):
        desk.book.open(desk.ana.id, 'magic', 'magic.json', 101)
    with pytest.raises(ConsignmentError):
        desk.book.open(desk.ana.id, 'magic', '../x.json', 10)


def test_a_sale_credits_the_consignor_minus_the_commission(desk):
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 20)
    sale = desk.checkout.charge(
        [line(desk, 'Blue-Eyes', 2, condition='Near Mint'), line(desk, 'Ragavan')], Discount(), 'cash', 'EUR',
        received_cents=9000)
    # 2 x 25,00 from the consigned collection; the Magic card is the shop's own.
    assert desk.customers.balance(desk.ana.id, 'consignment') == 4000
    entry = desk.customers.entries(desk.ana.id, 'consignment')[0]
    assert entry.ref == sale.id and 'Blue-Eyes' in entry.reason and '000001' in entry.reason


def test_a_ticket_discount_is_shared_between_the_lines(desk):
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 10)
    desk.checkout.charge(
        [line(desk, 'Dark'), line(desk, 'Ragavan')], Discount(kind='amount', value=10.0), 'card', 'EUR')
    # Ticket 9,99 + 40,00 = 49,99, minus 10,00. The consigned line keeps 999 * 3999 / 4999 = 799 (rounded).
    assert desk.customers.balance(desk.ana.id, 'consignment') == 799 - 80


def test_a_free_line_owes_nothing(desk):
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 10)
    desk.checkout.charge([line(desk, 'Blue-Eyes', condition='Played'), line(desk, 'Ragavan')], Discount(), 'card',
                         'EUR')
    assert desk.customers.entries(desk.ana.id) == []


def test_refund_takes_back_exactly_what_was_credited(desk):
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 15)
    sale = desk.checkout.charge([line(desk, 'Dark', 2)], Discount(kind='percent', value=7), 'card', 'EUR')
    owed = desk.customers.balance(desk.ana.id, 'consignment')
    assert owed > 0
    desk.checkout.refund(sale.id)
    assert desk.customers.balance(desk.ana.id, 'consignment') == 0
    assert qty(desk, 'Dark') == 2
    assert desk.book.reverse(desk.store.get(sale.id)) == []  # nothing left to take back


def test_refund_after_paying_out_leaves_a_visible_debt(desk):
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 20)
    sale = desk.checkout.charge([line(desk, 'Blue-Eyes', condition='Near Mint')], Discount(), 'card', 'EUR')
    desk.book.pay_out(desk.ana.id, 'cash')
    assert desk.customers.balance(desk.ana.id, 'consignment') == 0
    desk.checkout.refund(sale.id)
    assert desk.customers.balance(desk.ana.id, 'consignment') == -2000


def test_pay_out_in_cash_or_as_store_credit(desk):
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 20)
    desk.checkout.charge([line(desk, 'Blue-Eyes', 2, condition='Near Mint')], Discount(), 'card', 'EUR')
    assert desk.book.pay_out(desk.ana.id, 'cash', 1500) == 1500
    assert desk.customers.balance(desk.ana.id, 'consignment') == 2500
    assert desk.book.pay_out(desk.ana.id, 'credit') == 2500
    assert desk.customers.balance(desk.ana.id, 'consignment') == 0
    assert desk.customers.balance(desk.ana.id, 'credit') == 2500
    for amount in (None, 1, 0, -5):
        with pytest.raises(ConsignmentError):
            desk.book.pay_out(desk.ana.id, 'cash', amount)
    with pytest.raises(ConsignmentError):
        desk.book.pay_out(desk.ana.id, 'bank')


def test_a_closed_consignment_earns_nothing_more(desk):
    con = desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 20)
    desk.book.close(con.id)
    assert desk.book.of('yugioh', 'vitrina.json') is None and desk.book.active() == []
    assert len(desk.book.all()) == 1
    desk.checkout.charge([line(desk, 'Dark')], Discount(), 'card', 'EUR')
    assert desk.customers.entries(desk.ana.id) == []
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 30)  # can be consigned again


def test_a_stripe_sale_settles_the_consignment_when_it_is_paid(desk):
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 20)

    class Gateway:
        state = 'open'

        def create_checkout(self, sale, url):
            return 'cs_1', 'https://pay'

        def status(self, session):
            return self.state

    gateway = Gateway()
    sale = desk.checkout.start_stripe([line(desk, 'Blue-Eyes', condition='Near Mint')], Discount(), 'EUR',
                                      'https://shop/ok', gateway)
    assert desk.customers.entries(desk.ana.id) == []
    gateway.state = 'paid'
    desk.checkout.settle_stripe(sale.id, gateway)
    desk.checkout.settle_stripe(sale.id, gateway)
    assert desk.customers.balance(desk.ana.id, 'consignment') == 2000


def test_a_failing_consignment_book_does_not_lose_the_sale(desk):
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 20)

    def boom(sale):
        raise OSError('disk')

    desk.book.settle = boom
    sale = desk.checkout.charge([line(desk, 'Dark')], Discount(), 'card', 'EUR')
    assert sale.status == 'paid' and 'consigna' in desk.store.get(sale.id).note.lower()


def test_custom_lines_never_count_as_consigned(desk):
    desk.book.open(desk.ana.id, 'yugioh', 'vitrina.json', 20)
    desk.checkout.charge([SaleLine(kind='custom', name='Fundas', unit_cents=500, collection='vitrina.json')],
                         Discount(), 'card', 'EUR')
    assert desk.customers.entries(desk.ana.id) == []
