import pytest

from src.services.orders.book import OrderBook, OrderError
from src.services.orders.importer import Article, Incoming, bring_in, link, parse_orders
from src.services.orders.sku import sku_of
from tests.test_sales_services import find, qty, shop  # noqa: F401  (fixture)

GAMES = ['yugioh', 'magic']

ROWS = (
    'Order;Buyer;Email;Address;Zip;City;Country;Qty;Card;Set;Condition;Language;Price;Shipping\n'
    'A-1;Ana Ruiz;ana@example.test;Calle Mayor 1;08001;Barcelona;ES;2;Blue-Eyes White Dragon;LOB-EN001;NM;EN;24,50;3,90\n'
    'A-1;Ana Ruiz;ana@example.test;Calle Mayor 1;08001;Barcelona;ES;1;Ragavan, Nimble Pilferer;MH2;;;;3,90\n'
    'A-2;Bo;;;;;;1;Dark Hole;LOB-EN052;NM;EN;3,00;\n'
).encode('utf-8')

CARDMARKET = (
    'OrderID;Username;Name;Street;City;Country;Article Count;Merchandise Value;Shipment Costs;Total Value;'
    'Currency;Description\n'
    '9001;anar;Ana Ruiz;Calle Mayor 1;08001 Barcelona;Spain;3;59,00;1,45;60,45;EUR;'
    '2x Blue-Eyes White Dragon (Legend of Blue Eyes White Dragon) - 001 - Ultra Rare - NM - English - 25,00 EUR'
    ' | 1x Dark Magician (Starter Deck: Yugi) - 006 - Ultra Rare - NM - German - 9,00 EUR\n'
).encode('utf-8')


@pytest.fixture
def book(shop):  # noqa: F811
    shop.book = OrderBook(str(shop.root), shop.inventory)
    shop.items = lambda: shop.inventory.items(GAMES)
    return shop


# --- reading the file ------------------------------------------------------------------------

def test_rows_of_one_order_are_gathered(book):
    first, second = parse_orders(ROWS, 'otro')
    assert (first.external_id, first.customer_name, first.email, first.shipping_cents) == (
        'A-1', 'Ana Ruiz', 'ana@example.test', 390)
    assert first.address.lines() == ['Ana Ruiz', 'Calle Mayor 1', '08001 Barcelona', 'ES']
    assert [(a.quantity, a.name, a.set_code, a.condition, a.language, a.unit_cents) for a in first.articles] == [
        (2, 'Blue-Eyes White Dragon', 'LOB-EN001', 'Near Mint', 'EN', 2450),
        (1, 'Ragavan, Nimble Pilferer', 'MH2', '', '', 0)]
    assert (second.external_id, len(second.articles), second.channel) == ('A-2', 1, 'otro')


def test_a_cardmarket_row_is_one_order_with_its_description_split(book):
    (order,) = parse_orders(CARDMARKET, 'cardmarket')
    assert (order.external_id, order.customer_name, order.shipping_cents, order.currency) == (
        '9001', 'Ana Ruiz', 145, 'EUR')
    assert order.address.lines() == ['Ana Ruiz', 'Calle Mayor 1', '08001 Barcelona', 'Spain']
    assert [(a.quantity, a.name, a.set_code, a.condition, a.language, a.unit_cents) for a in order.articles] == [
        (2, 'Blue-Eyes White Dragon', 'Legend of Blue Eyes White Dragon', 'Near Mint', 'EN', 2500),
        (1, 'Dark Magician', 'Starter Deck: Yugi', 'Near Mint', 'DE', 900)]


def test_a_description_piece_nobody_understands_is_kept_as_text(book):
    data = 'OrderID;Description\n7;Something odd without a count | 3 Dark Hole\n'.encode()
    (order,) = parse_orders(data, 'cardmarket')
    assert [(a.quantity, a.name) for a in order.articles] == [(1, 'Something odd without a count'), (3, 'Dark Hole')]


def test_a_file_without_articles_says_what_is_missing(book):
    with pytest.raises(OrderError, match='carta'):
        parse_orders(b'Order;Buyer\n1;Ana\n', 'otro')
    with pytest.raises(OrderError):
        parse_orders(b'', 'otro')


def test_a_quantity_that_is_not_a_number_names_its_row(book):
    with pytest.raises(OrderError, match='Fila 2'):
        parse_orders(b'Order;Card;Qty\n1;Dark Hole;many\n', 'otro')
    with pytest.raises(OrderError, match='Fila 2'):
        parse_orders(b'Order;Card;Qty\n1;Dark Hole;0\n', 'otro')


def test_rows_without_an_order_number_are_one_order_each(book):
    orders = parse_orders(b'Card;Qty\nDark Hole;1\nRaigeki;2\n', 'otro')
    assert [(o.made_up, o.articles[0].name) for o in orders] == [(True, 'Dark Hole'), (True, 'Raigeki')]


def test_formulas_in_a_file_stay_text(book):
    (order,) = parse_orders('Order;Buyer;Card\n1;=HYPERLINK("http://x");=cmd|calc\n'.encode(), 'otro')
    assert (order.customer_name, order.articles[0].name) == ('=HYPERLINK("http://x")', '=cmd|calc')


# --- linking to piles ------------------------------------------------------------------------

def test_an_article_finds_its_pile_by_name_and_set(book):
    (line,) = link([Article('blue-eyes white dragon', 'LOB-EN001', 'Near Mint', 'EN', 2, 2450)], book.items())
    assert (line.kind, line.unlinked, line.collection, line.variant_id, line.storage_location) == (
        'stock', False, 'vitrina.json', 'v1', 'Caja A')
    assert (line.quantity, line.unit_cents) == (2, 2450)


def test_without_a_price_the_pile_keeps_its_own(book):
    (line,) = link([Article('Ragavan, Nimble Pilferer', 'MH2')], book.items())
    assert (line.game, line.unit_cents, line.finish) == ('magic', 4000, 'foil')


def test_condition_and_language_choose_between_piles(book):
    (played,) = link([Article('Blue-Eyes White Dragon', 'LOB-EN001', 'Played')], book.items())
    assert (played.condition, played.unlinked) == ('Played', False)
    (wrong,) = link([Article('Dark Magician', 'SDY-006', 'Near Mint', 'EN')], book.items())
    assert (wrong.kind, wrong.unlinked) == ('custom', True)       # we only hold it in German


def test_a_set_written_as_a_name_still_links_when_only_one_printing_fits(book):
    (line,) = link([Article('Dark Magician', 'Starter Deck: Yugi', 'Near Mint', 'DE')], book.items())
    assert (line.kind, line.variant_id) == ('stock', 'v2')


def test_the_short_code_of_a_set_is_enough(book):
    (line,) = link([Article('Blue-Eyes White Dragon', 'LOB', 'Near Mint')], book.items())
    assert line.variant_id == 'v1'


def test_what_is_not_in_stock_stays_unlinked_with_its_words(book):
    (line,) = link([Article('Dark Hole', 'LOB-EN052', 'Near Mint', 'EN', 1, 300)], book.items())
    assert (line.kind, line.unlinked, line.name, line.quantity, line.unit_cents) == (
        'custom', True, 'Dark Hole (LOB-EN052)', 1, 300)


def test_two_articles_cannot_share_the_last_copies(book):
    first, second = link([Article('Blue-Eyes White Dragon', 'LOB-EN001', 'Near Mint', '', 2),
                          Article('Blue-Eyes White Dragon', 'LOB-EN001', 'Near Mint', '', 2)], book.items())
    assert (first.unlinked, second.unlinked) == (False, True)


def test_a_sku_goes_straight_to_its_pile(book):
    pile = find(book.items(), 'Blue-Eyes', condition='Played')
    (line,) = link([Article('Whatever the shop calls it', sku=sku_of(pile))], book.items())
    assert (line.kind, line.condition, line.name) == ('stock', 'Played', 'Blue-Eyes White Dragon')


def test_a_sku_is_stable_and_tells_piles_apart(book):
    items = book.items()
    skus = {sku_of(item) for item in items}
    assert len(skus) == len(items) and all(len(s) == 15 and s.startswith('OY-') for s in skus)
    assert {sku_of(item) for item in book.items()} == skus


# --- bringing orders in ----------------------------------------------------------------------

def test_orders_from_a_file_enter_paid_and_take_stock(book):
    report = bring_in(book.book, parse_orders(ROWS, 'otro'), book.items())
    assert (len(report.created), report.skipped, report.unlinked, report.failed) == (2, 0, 1, [])
    first = next(o for o in report.created if o.external_id == 'A-1')
    assert (first.status, first.channel, first.total_cents) == ('paid', 'otro', 2 * 2450 + 4000 + 390)
    assert (qty(book, 'Blue-Eyes', condition='Near Mint'), qty(book, 'Ragavan')) == (1, 1)


def test_bringing_the_same_file_twice_changes_nothing_the_second_time(book):
    bring_in(book.book, parse_orders(ROWS, 'otro'), book.items())
    report = bring_in(book.book, parse_orders(ROWS, 'otro'), book.items())
    assert (report.created, report.skipped) == ([], 2)
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 1
    assert len(book.book.all()) == 2


def test_two_orders_in_one_file_do_not_both_get_the_last_copies(book):
    data = ('Order;Card;Set;Condition;Qty\n1;Blue-Eyes White Dragon;LOB-EN001;NM;2\n'
            '2;Blue-Eyes White Dragon;LOB-EN001;NM;2\n').encode()
    report = bring_in(book.book, parse_orders(data, 'otro'), book.items())
    assert (len(report.created), report.unlinked, report.failed) == (2, 1, [])
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 1


def test_stock_that_left_meanwhile_fails_that_order_only(book):
    items = book.items()                      # read before someone sells the cards at the counter
    book.inventory.take([find(items, 'Ragavan').model_copy(update={'quantity': 2})])
    report = bring_in(book.book, parse_orders(ROWS, 'otro'), items)
    assert [o.external_id for o in report.created] == ['A-2']
    assert len(report.failed) == 1 and 'A-1' in report.failed[0]
    assert qty(book, 'Blue-Eyes', condition='Near Mint') == 3


def test_an_incoming_order_without_articles_is_reported(book):
    report = bring_in(book.book, [Incoming(external_id='E1', channel='otro')], book.items())
    assert report.created == [] and 'E1' in report.failed[0]
