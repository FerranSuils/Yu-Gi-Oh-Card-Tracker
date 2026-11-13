import pytest

from src.core.catalog_models import CatalogCard, CatalogPrinting
from src.core.pricing_models import PriceQuote, PrintingPrice
from src.core.sales_models import Discount
from src.core.shop_models import BuylistRules
from src.services.sales.checkout import Checkout
from src.services.shop.buylist import Buying, BuyError, PurchaseStore, line_for, market_cents, offer_cents
from src.services.shop.consignment import ConsignmentBook
from src.services.shop.customers import CustomerStore
from tests.test_sales_services import find, qty, shop  # noqa: F401  (fixture)

RAGAVAN = CatalogCard(game='magic', card_id='c1', name='Ragavan, Nimble Pilferer', printings=[
    CatalogPrinting(printing_id='p1', set_code='MH2', set_name='Modern Horizons 2', number='138', rarity='mythic',
                    finishes=['nonfoil', 'foil'])])
BLUE = CatalogCard(game='yugioh', card_id='89631139', name='Blue-Eyes White Dragon', printings=[
    CatalogPrinting(printing_id='v1', set_code='LOB-EN001', set_name='Legend of Blue Eyes', rarity='Ultra Rare')])
SOLEMN = CatalogCard(game='yugioh', card_id='41420027', name='Solemn Judgment', printings=[
    CatalogPrinting(printing_id='v9', set_code='MRD-127', set_name='Metal Raiders', rarity='Ultra Rare')])


@pytest.fixture
def desk(shop):  # noqa: F811
    customers = CustomerStore(str(shop.root))
    shop.customers = customers
    shop.book = ConsignmentBook(str(shop.root), customers)
    shop.purchases = PurchaseStore(str(shop.root))
    shop.buying = Buying(shop.inventory, shop.purchases, customers, shop.book)
    shop.checkout = Checkout(shop.inventory, shop.store, customers=customers, consignments=shop.book)
    shop.ana = customers.add('Ana')
    return shop


def ragavan(quantity=1, paid=2000, **fields):
    fields = {'finish': 'foil', 'collection': 'magic.json', 'market': 4000, **fields}
    return line_for(RAGAVAN, RAGAVAN.printings[0], quantity=quantity, paid_cents=paid,
                    market_cents=fields.pop('market'), **fields)


# --- the offer -------------------------------------------------------------------------------

@pytest.mark.parametrize('market, payment, condition, offer', [
    (1000, 'cash', 'Near Mint', 500),
    (1000, 'credit', 'Near Mint', 650),
    (1000, 'cash', 'Played', 300),       # 50 % of 60 %
    (999, 'credit', 'Good', 519),        # 999 * 0.65 * 0.80 = 519,48
    (5, 'cash', 'Near Mint', 3),         # 2,5 rounds up
    (1000, 'cash', 'Unknown grade', 500),
    (0, 'cash', 'Near Mint', 0),
])
def test_offer_is_market_times_payment_times_condition(market, payment, condition, offer):
    assert offer_cents(market, BuylistRules(), payment, condition) == offer


def test_offers_under_the_minimum_are_not_made():
    rules = BuylistRules(min_offer_cents=50)
    assert offer_cents(99, rules, 'cash', 'Near Mint') == 50  # 49,5 rounds up and reaches the minimum
    assert offer_cents(98, rules, 'cash', 'Near Mint') == 0
    assert offer_cents(100, rules, 'cash', 'Near Mint') == 50


def test_offer_rejects_an_unknown_payment():
    with pytest.raises(BuyError):
        offer_cents(1000, BuylistRules(), 'bank', 'Near Mint')


def test_rules_reject_nonsense_percentages():
    for bad in ({'cash_percent': 101}, {'credit_percent': -1}, {'min_offer_cents': -5},
                {'cash_percent': float('nan')}):
        with pytest.raises(ValueError):
            BuylistRules(**bad)


def test_market_price_follows_the_finish():
    price = PrintingPrice(normal=PriceQuote(trend=1.5), foil=PriceQuote(trend=4.256))
    assert market_cents(price, 'nonfoil') == 150
    assert market_cents(price, 'foil') == 426
    assert market_cents(PrintingPrice(normal=PriceQuote(low=0.2)), '') == 20  # falls back to another metric
    assert market_cents(None, 'foil') is None
    assert market_cents(PrintingPrice(), 'foil') is None


# --- lines -----------------------------------------------------------------------------------

def test_line_for_a_magic_printing():
    line = ragavan(3, paid=1900, condition='Good', language='DE')
    assert (line.game, line.collection, line.card_id, line.variant_id, line.finish) == (
        'magic', 'magic.json', 'c1', 'p1', 'foil')
    assert (line.quantity, line.unit_cents, line.list_price, line.condition, line.language) == (
        3, 1900, 40.0, 'Good', 'DE')
    assert (line.set_code, line.number, line.rarity) == ('MH2', '138', 'mythic')


def test_line_for_a_yugioh_printing_has_no_finish():
    line = line_for(BLUE, BLUE.printings[0], quantity=1, paid_cents=1000, market_cents=None,
                    collection='vitrina.json', first_edition=True)
    assert (line.game, line.card_id, line.variant_id, line.finish, line.image_id, line.number) == (
        'yugioh', '89631139', 'v1', '', 89631139, None)
    assert line.list_price is None and line.first_edition is True


# --- buying ----------------------------------------------------------------------------------

def test_buying_for_cash_puts_the_cards_in_stock(desk):
    purchase = desk.buying.buy([ragavan(2)], 'cash', 'EUR')
    assert (purchase.label, purchase.total_cents, purchase.payment, purchase.status, purchase.units) == (
        'C00001', 4000, 'cash', 'done', 2)
    assert qty(desk, 'Ragavan') == 4
    assert desk.purchases.get(purchase.id).total_cents == 4000
    assert desk.buying.buy([ragavan(1)], 'cash', 'EUR', customer_id=desk.ana.id).label == 'C00002'
    assert desk.customers.entries(desk.ana.id) == []  # cash leaves no balance


def test_a_new_pile_goes_on_sale_at_the_market_price(desk):
    desk.buying.buy([line_for(SOLEMN, SOLEMN.printings[0], quantity=2, paid_cents=300, market_cents=650,
                              collection='vitrina.json', condition='Excellent')], 'cash', 'EUR')
    pile = find(desk.inventory.items(['yugioh']), 'Solemn')
    assert (pile.quantity, pile.unit_cents, pile.condition, pile.collection) == (2, 650, 'Excellent', 'vitrina.json')


def test_an_existing_pile_keeps_its_own_price(desk):
    desk.buying.buy([ragavan(1, market=9900)], 'cash', 'EUR')
    assert find(desk.inventory.items(['magic']), 'Ragavan').unit_cents == 4000


def test_buying_for_credit_adds_store_credit(desk):
    purchase = desk.buying.buy([ragavan(1, paid=2600)], 'credit', 'EUR', customer_id=desk.ana.id)
    assert (purchase.customer_id, purchase.customer_name) == (desk.ana.id, 'Ana')
    assert desk.customers.balance(desk.ana.id, 'credit') == 2600
    entry = desk.customers.entries(desk.ana.id)[0]
    assert (entry.ref, entry.reason) == (purchase.id, 'Compra C00001')


@pytest.mark.parametrize('customer', [None, 'nobody'])
def test_credit_needs_a_known_customer(desk, customer):
    with pytest.raises(BuyError):
        desk.buying.buy([ragavan(1)], 'credit', 'EUR', customer_id=customer)
    assert qty(desk, 'Ragavan') == 2 and desk.purchases.all() == []


def test_refused_purchases_change_nothing(desk):
    bad = [
        lambda: ([], 'cash'),
        lambda: ([ragavan(1)], 'bank'),
        lambda: ([ragavan(0)], 'cash'),
        lambda: ([ragavan(1, paid=-5)], 'cash'),
        lambda: ([ragavan(1, collection='')], 'cash'),
        lambda: ([ragavan(1, collection='../x.json')], 'cash'),
        lambda: ([ragavan(1)] * 201, 'cash'),
    ]
    for make in bad:
        with pytest.raises(BuyError):
            lines, payment = make()
            desk.buying.buy(lines, payment, 'EUR')
    assert qty(desk, 'Ragavan') == 2 and desk.purchases.all() == []


def test_cards_cannot_be_bought_into_a_consigned_collection(desk):
    desk.book.open(desk.ana.id, 'magic', 'magic.json', 20)
    with pytest.raises(BuyError) as error:
        desk.buying.buy([ragavan(1)], 'cash', 'EUR')
    assert 'consigna' in str(error.value).lower()


def test_a_free_card_can_be_taken_in(desk):
    purchase = desk.buying.buy([ragavan(1, paid=0)], 'cash', 'EUR')
    assert purchase.total_cents == 0 and qty(desk, 'Ragavan') == 3


# --- cancelling ------------------------------------------------------------------------------

def test_cancelling_takes_the_cards_and_the_credit_back(desk):
    purchase = desk.buying.buy([ragavan(2, paid=1300)], 'credit', 'EUR', customer_id=desk.ana.id)
    cancelled = desk.buying.cancel(purchase.id)
    assert cancelled.status == 'cancelled' and cancelled.cancelled_at
    assert qty(desk, 'Ragavan') == 2
    assert desk.customers.balance(desk.ana.id, 'credit') == 0
    with pytest.raises(BuyError):
        desk.buying.cancel(purchase.id)
    assert qty(desk, 'Ragavan') == 2 and desk.customers.balance(desk.ana.id, 'credit') == 0


def test_cannot_cancel_once_the_cards_were_sold(desk):
    purchase = desk.buying.buy([ragavan(1)], 'cash', 'EUR')
    desk.checkout.charge([find(desk.inventory.items(['magic']), 'Ragavan')], Discount(), 'card', 'EUR')
    with pytest.raises(BuyError) as error:
        desk.buying.cancel(purchase.id)
    assert 'Ragavan' in str(error.value)
    assert desk.purchases.get(purchase.id).status == 'done' and qty(desk, 'Ragavan') == 0


def test_cannot_cancel_once_the_credit_was_spent(desk):
    purchase = desk.buying.buy([ragavan(1, paid=2600)], 'credit', 'EUR', customer_id=desk.ana.id)
    desk.customers.post(desk.ana.id, 'credit', -100, 'Ajuste')
    with pytest.raises(BuyError) as error:
        desk.buying.cancel(purchase.id)
    assert 'saldo' in str(error.value).lower()
    assert qty(desk, 'Ragavan') == 3 and desk.customers.balance(desk.ana.id, 'credit') == 2500
    assert desk.purchases.get(purchase.id).status == 'done'


def test_cancelling_an_unknown_purchase(desk):
    with pytest.raises(BuyError):
        desk.buying.cancel('nope')


def test_a_broken_purchases_file_is_not_overwritten(desk):
    desk.buying.buy([ragavan(1)], 'cash', 'EUR')
    path = desk.root / 'shop' / 'purchases.json'
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(BuyError):
        desk.buying.buy([ragavan(1)], 'cash', 'EUR')
    assert path.read_text(encoding='utf-8') == '{broken'
    assert qty(desk, 'Ragavan') == 3  # the second purchase put nothing in
