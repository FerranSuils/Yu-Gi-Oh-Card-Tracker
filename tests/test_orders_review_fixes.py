"""What the review of the channels phase found, each pinned down."""

import builtins
import json
import os

import pytest

from src.core.models import CollectionEntry, CollectionVariant
from src.core.order_models import Order, OrderLine
from src.core.account_profile import ShopProfile
from src.services.orders import shopify as shopify_module
from src.services.orders.book import pick_list
from src.services.orders.channels import ChannelError, shopify_csv, woocommerce_csv
from src.services.orders.importer import Article, Incoming, bring_in, link, parse_orders
from src.services.orders.paper import picks_html, slip_html
from src.services.orders.sync import sync
from src.services.shop.files import read_list, write_list
from tests.test_orders_channels import rows
from tests.test_orders_sync import (GAMES, SHOPIFY_ORDER, WOO_ORDER, FakeShop, Reply, book, bought,  # noqa: F401
                                    shopify, woo)
from tests.test_sales_services import find, qty, shop  # noqa: F401  (fixture)


# 1. a collection that cannot be read stops the round before anything moves

def test_a_round_stops_before_touching_anything_when_a_collection_cannot_be_read(book):
    incoming = [bought(book)]
    (book.root / 'collections' / 'vitrina.json').write_text('{ roto', encoding='utf-8')
    online = FakeShop(incoming)
    with pytest.raises(ChannelError, match='colecci'):
        sync(book.book, online, lambda: book.inventory.items(GAMES, strict=True), 'EUR', {'OY-OLD': 3})
    assert book.book.all() == [] and online.pushes == []


def test_the_shelves_are_still_listed_leniently_by_default(book):
    (book.root / 'collections' / 'vitrina.json').write_text('{ roto', encoding='utf-8')
    assert [item.name for item in book.inventory.items(GAMES)] == ['Ragavan, Nimble Pilferer']


# 2. an article is never served from another printing

def second_printing(book, rarity='Secret Rare', set_code='LOB-EN001', quantity=5):
    collection = book.persistence.load_collection('vitrina.json')
    card = next(card for card in collection.cards if card.name.startswith('Blue-Eyes'))
    card.variants.append(CollectionVariant(variant_id='v9', set_code=set_code, rarity=rarity, image_id=89631139,
                                           entries=[CollectionEntry(quantity=quantity, list_price=90.0)]))
    book.persistence.save_collection(collection, 'vitrina.json')


def test_a_name_that_fits_several_printings_is_left_for_a_person(book):
    second_printing(book, set_code='SDK-001')
    (line,) = link([Article(name='Blue-Eyes White Dragon', quantity=1)], book.items())
    assert line.unlinked and line.kind == 'custom'


def test_a_pile_that_runs_short_is_not_made_up_from_another_rarity(book):
    second_printing(book)
    (line,) = link([Article(name='Blue-Eyes White Dragon', set_code='LOB-EN001', rarity='Ultra Rare',
                            condition='Near Mint', quantity=4)], book.items())
    assert line.unlinked


def test_the_rarity_of_an_article_chooses_between_printings_of_one_set(book):
    second_printing(book)
    (line,) = link([Article(name='Blue-Eyes White Dragon', set_code='LOB-EN001', rarity='secret rare',
                            quantity=1)], book.items())
    assert (line.unlinked, line.variant_id, line.rarity) == (False, 'v9', 'Secret Rare')


def test_cardmarket_descriptions_carry_the_rarity():
    (order,) = parse_orders(
        'OrderID;Username;Description\n9;ana;1x Blue-Eyes White Dragon (LOB) - 001 - Ultra Rare - NM - English - '
        '25,00 EUR\n'.encode(), 'cardmarket')
    assert [(a.name, a.rarity, a.condition, a.language) for a in order.articles] == [
        ('Blue-Eyes White Dragon', 'Ultra Rare', 'Near Mint', 'EN')]


def test_a_rarity_column_is_read():
    (order,) = parse_orders(b'Order;Card;Rarity\n1;Dark Hole;Rare\n', 'otro')
    assert order.articles[0].rarity == 'Rare'


def test_the_pick_sheet_says_the_rarity(book):
    pile = find(book.items(), 'Blue-Eyes', condition='Near Mint')
    order = Order(number=1, lines=[OrderLine(**{**pile.model_dump(), 'quantity': 1})])
    (pick,) = pick_list([order])
    assert pick.rarity == 'Ultra Rare' and 'Ultra Rare' in picks_html([pick])


# 3. a file without order numbers can be uploaded twice

NO_NUMBERS = b'Buyer;Card;Set;Qty;Price\nAna;Blue-Eyes White Dragon;LOB-EN001;1;25,00\nBo;Dark Magician;SDY-006;1;9,00\n'


def test_the_same_file_without_order_numbers_does_not_enter_twice(book):
    first = bring_in(book.book, parse_orders(NO_NUMBERS, 'otro'), book.items())
    second = bring_in(book.book, parse_orders(NO_NUMBERS, 'otro'), book.items())
    assert (len(first.created), len(second.created), second.skipped) == (2, 0, 2)
    assert len(book.book.all()) == 2 and qty(book, 'Blue-Eyes', condition='Near Mint') == 2


def test_two_equal_rows_without_order_number_are_still_two_orders(book):
    data = b'Buyer;Card;Qty\nAna;Blue-Eyes White Dragon;1\nAna;Blue-Eyes White Dragon;1\n'
    first, second = parse_orders(data, 'otro')
    assert first.external_id and second.external_id and first.external_id != second.external_id
    assert [o.external_id for o in parse_orders(data, 'otro')] == [first.external_id, second.external_id]


# 4. piles without a price are not put on sale at 0.00

def test_piles_without_a_price_stay_out_of_the_product_files(book):
    from src.services.orders.channels import sellable

    items = book.items()
    priced, left_out = sellable(items)
    assert (len(priced), left_out) == (3, 1)
    for table in (rows(shopify_csv(items)), rows(woocommerce_csv(items))):
        assert len(table) == 3
        assert all(float(row.get('Variant Price') or row.get('Regular price')) > 0 for row in table)


# 5. Windows refusing a file for a moment is not the end of it

def test_a_write_waits_out_a_reader_holding_the_file(tmp_path, monkeypatch):
    path = str(tmp_path / 'shop' / 'orders.json')
    write_list(path, [Order(number=1)])
    real, refusals = os.replace, [PermissionError(13, 'held'), PermissionError(13, 'held')]

    def replace(source, target):
        if refusals:
            raise refusals.pop()
        return real(source, target)

    monkeypatch.setattr(os, 'replace', replace)
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    write_list(path, [Order(number=1), Order(number=2)])
    assert [order.number for order in read_list(path, Order)] == [1, 2] and not refusals


def test_a_read_waits_out_a_writer_swapping_the_file(tmp_path, monkeypatch):
    path = str(tmp_path / 'shop' / 'orders.json')
    write_list(path, [Order(number=7)])
    real, refusals = builtins.open, [PermissionError(13, 'held'), PermissionError(13, 'held')]

    def opened(file, *args, **kwargs):
        if refusals and str(file) == path:
            raise refusals.pop()
        return real(file, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', opened)
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    assert [order.number for order in read_list(path, Order)] == [7] and not refusals


def test_an_order_that_cannot_be_saved_does_not_stop_the_rest(book, monkeypatch):
    real, calls = book.book.create, []

    def create(lines, **fields):
        calls.append(fields['external_id'])
        if len(calls) == 1:
            raise PermissionError(13, 'held')
        return real(lines, **fields)

    monkeypatch.setattr(book.book, 'create', create)
    report = bring_in(book.book, [bought(book, '#1', 1), bought(book, '#2', 1)], book.items())
    assert [order.external_id for order in report.created] == ['#2']
    assert len(report.failed) == 1 and report.failed[0].startswith('#1')


# 6. a shop cannot answer without end

def test_shop_replies_are_read_as_a_stream(book):
    client, http = shopify(Reply(body={'data': {'shop': {'name': 'Sol'}}}))
    client.ping()
    store, web = woo(Reply(body=[]))
    store.ping()
    assert http.calls[0][2]['stream'] is True and web.calls[0][2]['stream'] is True


def test_a_reply_that_is_too_big_is_refused():
    huge = Reply(body={'data': {'shop': {'name': 'x' * (shopify_module.MAX_BYTES + 10)}}})
    client, _ = shopify(huge)
    with pytest.raises(ChannelError, match='demasiado'):
        client.ping()
    store, _ = woo(Reply(body=['x' * (shopify_module.MAX_BYTES + 10)]))
    with pytest.raises(ChannelError, match='demasiado'):
        store.ping()
    assert huge.closed


def test_a_reply_that_drips_for_too_long_is_refused():
    ticks = iter(range(0, 10_000, 30))
    with pytest.raises(ChannelError, match='tarda'):
        shopify_module.read_body(Reply(body={'a': 'b' * 500_000}), 0, clock=lambda: next(ticks))


# 7. what the shop charged is kept and printed

def test_shopify_and_woocommerce_bring_what_the_buyer_paid():
    client, _ = shopify(Reply(body={'data': {'orders': {'pageInfo': {'hasNextPage': False}, 'nodes': [
        {**SHOPIFY_ORDER, 'currentTotalPriceSet': {'shopMoney': {'amount': '48.90'}}}]}}}))
    store, _ = woo(Reply(body=[{**WOO_ORDER, 'total': '15.00'}]))
    assert client.orders()[0].total_cents == 4890 and store.orders()[0].total_cents == 1500


def test_an_order_keeps_what_the_shop_charged_and_the_slip_prints_it(book):
    incoming = bought(book, '#9', 1)
    incoming.total_cents = 2000
    (order,) = bring_in(book.book, [incoming], book.items()).created
    assert (order.total_cents, order.charged_cents, order.income_cents) == (2500, 2000, 2000)
    html = slip_html(order, ShopProfile(name='Sol'))
    assert 'Cobrado en la tienda' in html and '20,00' in html


def test_an_order_of_our_own_has_no_separate_charge(book):
    (order,) = bring_in(book.book, [bought(book, '#9', 1)], book.items()).created
    assert (order.charged_cents, order.income_cents) == (0, 2500)
    assert 'Cobrado en la tienda' not in slip_html(order, ShopProfile(name='Sol'))


def test_the_report_counts_what_the_shop_charged():
    from datetime import date, timezone

    from src.services.reports.summary import build

    stamp = '2026-11-04T12:00:00+00:00'
    order = Order(created_at=stamp, paid_at=stamp, total_cents=2500, charged_cents=2000, channel='shopify',
                  status='paid', lines=[OrderLine(name='Dark Hole', quantity=1, unit_cents=2500)])
    assert build([], [order], [], date(2026, 11, 1), date(2026, 11, 30), tz=timezone.utc).revenue_cents == 2000


# 8. the newest orders first, and a warning when some are left behind

def test_shopify_is_asked_for_the_newest_orders_first():
    client, http = shopify(Reply(body={'data': {'orders': {'pageInfo': {'hasNextPage': False}, 'nodes': []}}}))
    client.orders()
    assert 'reverse: true' in http.calls[0][2]['json']['query'] and client.truncated is False


def test_orders_left_behind_are_told(book):
    endless = Reply(body={'data': {'orders': {'pageInfo': {'hasNextPage': True, 'endCursor': 'c'}, 'nodes': []}}})
    client, _ = shopify(*[endless] * 50)
    client.orders()
    assert client.truncated is True
    online = FakeShop([])
    online.truncated = True
    assert sync(book.book, online, book.items, 'EUR', {}).truncated is True
    assert sync(book.book, FakeShop([]), book.items, 'EUR', {}).truncated is False


def test_the_summary_of_a_round_warns_about_orders_left_behind():
    from src.services.orders.sync import SyncReport
    from src.ui.settings_channels import sync_lines

    assert any('más pedidos' in line for line in sync_lines(SyncReport(truncated=True)))
    assert not any('más pedidos' in line for line in sync_lines(SyncReport()))


# the order total in a file, and the shelves before an import

def test_a_shopify_orders_file_brings_the_order_total():
    data = b'Name;Lineitem name;Lineitem quantity;Lineitem price;Total\n#7;Dark Hole;1;3,00;7,50\n#7;Raigeki;1;4,00;\n'
    (order,) = parse_orders(data, 'shopify')
    assert order.total_cents == 750


def test_a_total_column_in_a_plain_list_is_not_taken_for_the_order_total():
    (order,) = parse_orders(b'Order;Card;Qty;Price;Total\n1;Dark Hole;2;3,00;6,00\n', 'otro')
    assert order.total_cents == 0


def test_an_import_refuses_to_start_when_a_collection_cannot_be_read(book):
    from src.services.orders.book import OrderError
    from src.services.orders.importer import shelves_or_refuse

    (book.root / 'collections' / 'vitrina.json').write_text('{ roto', encoding='utf-8')
    with pytest.raises(OrderError, match='colecci'):
        shelves_or_refuse(book.inventory, GAMES)


def test_rows_without_a_reference_are_marked_as_such():
    first, second = parse_orders(b'Card;Qty\nDark Hole;1\nRaigeki;2\n', 'otro')
    assert first.made_up and second.made_up
    (numbered,) = parse_orders(b'Order;Card\n9;Dark Hole\n', 'otro')
    assert not numbered.made_up and numbered.external_id == '9'
