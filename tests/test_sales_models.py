import pytest

from src.core.catalog_models import GameCollection, GameCollectionCard, GameCollectionVariant
from src.core.game_collections import GameCollectionEditor
from src.core.models import Collection, CollectionCard, CollectionEntry, CollectionVariant
from src.core.sales_models import (
    Discount,
    OutOfStock,
    SaleLine,
    change_cents,
    discount_cents,
    format_money,
    subtotal_cents,
    to_cents,
    total_cents,
)
from src.services.collection_editor import CollectionEditor


@pytest.mark.parametrize('value, cents', [
    (12.34, 1234), ('12,34', 1234), ('12.34', 1234), (0.1 + 0.2, 30), (1.005, 101), ('3', 300),
    (0, 0), ('', 0), (None, 0), (' 4,5 € ', 450), (19.999, 2000),
])
def test_to_cents(value, cents):
    assert to_cents(value) == cents


@pytest.mark.parametrize('value', [-1, '-0,01', 'abc', float('nan'), float('inf'), 10_000_001])
def test_to_cents_rejects(value):
    with pytest.raises(ValueError):
        to_cents(value)


@pytest.mark.parametrize('cents, currency, text', [
    (1234, 'EUR', '12,34 €'), (5, 'EUR', '0,05 €'), (123456, 'EUR', '1.234,56 €'),
    (1234, 'USD', '$12.34'), (123456, 'GBP', '£1,234.56'), (0, 'EUR', '0,00 €'),
])
def test_format_money(cents, currency, text):
    assert format_money(cents, currency) == text


def line(quantity=1, unit=100, **extra):
    return SaleLine(name='Carta', quantity=quantity, unit_cents=unit, **extra)


def test_totals():
    lines = [line(2, 150), line(1, 99)]
    assert subtotal_cents(lines) == 399
    assert total_cents(lines, Discount()) == 399
    assert discount_cents(399, Discount(kind='percent', value=10)) == 40
    assert total_cents(lines, Discount(kind='percent', value=10)) == 359
    assert total_cents(lines, Discount(kind='amount', value=1.5)) == 249


@pytest.mark.parametrize('discount, expected', [
    (Discount(kind='percent', value=150), 399), (Discount(kind='amount', value=10), 399),
    (Discount(kind='percent', value=0), 0), (Discount(kind='none', value=50), 0),
])
def test_discount_never_exceeds_subtotal(discount, expected):
    assert discount_cents(399, discount) == expected


def test_discount_rejects_negative_values():
    with pytest.raises(ValueError):
        Discount(kind='percent', value=-5)


def test_line_rejects_bad_quantity_and_price():
    with pytest.raises(ValueError):
        line(quantity=0)
    with pytest.raises(ValueError):
        line(unit=-1)


def test_change():
    assert change_cents(1250, 2000) == 750
    assert change_cents(1250, 1250) == 0
    with pytest.raises(ValueError):
        change_cents(1250, 1000)


# --- stock through the editors -------------------------------------------------------------

def ygo_collection():
    entry = CollectionEntry(condition='Near Mint', language='EN', quantity=3, list_price=2.5,
                            storage_location='Caja A')
    other = CollectionEntry(condition='Played', language='EN', quantity=1)
    variant = CollectionVariant(variant_id='v1', set_code='LOB-EN001', rarity='Ultra Rare', image_id=89631139,
                                entries=[entry, other])
    return Collection(name='Tienda', cards=[CollectionCard(card_id=89631139, name='Blue-Eyes', variants=[variant])])


def ygo_line(quantity=1, **extra):
    fields = dict(game='yugioh', collection='tienda.json', card_id='89631139', name='Blue-Eyes',
                  set_code='LOB-EN001', rarity='Ultra Rare', variant_id='v1', image_id=89631139,
                  condition='Near Mint', language='EN', storage_location='Caja A', quantity=quantity,
                  unit_cents=250, list_price=2.5)
    fields.update(extra)
    return SaleLine(**fields)


def test_ygo_take_stock_lowers_the_pile():
    collection = ygo_collection()
    CollectionEditor.take_stock(collection, ygo_line(2))
    assert collection.cards[0].variants[0].entries[0].quantity == 1
    assert collection.cards[0].variants[0].entries[1].quantity == 1


def test_ygo_take_stock_removes_empty_pile_variant_and_card():
    collection = ygo_collection()
    CollectionEditor.take_stock(collection, ygo_line(3))
    CollectionEditor.take_stock(collection, ygo_line(1, condition='Played', storage_location=None))
    assert collection.cards == []


def test_ygo_take_more_than_owned_changes_nothing():
    collection = ygo_collection()
    with pytest.raises(OutOfStock) as caught:
        CollectionEditor.take_stock(collection, ygo_line(4))
    assert caught.value.available == 3
    assert collection.cards[0].variants[0].entries[0].quantity == 3


def test_ygo_take_missing_pile_reports_zero():
    with pytest.raises(OutOfStock) as caught:
        CollectionEditor.take_stock(ygo_collection(), ygo_line(1, language='DE'))
    assert caught.value.available == 0


def test_ygo_return_stock_rebuilds_what_the_sale_emptied():
    collection = ygo_collection()
    sold = ygo_line(3)
    CollectionEditor.take_stock(collection, sold)
    CollectionEditor.take_stock(collection, ygo_line(1, condition='Played', storage_location=None))
    CollectionEditor.return_stock(collection, sold)
    card = collection.cards[0]
    assert (card.card_id, card.name) == (89631139, 'Blue-Eyes')
    variant = card.variants[0]
    assert (variant.variant_id, variant.set_code, variant.rarity, variant.image_id) == (
        'v1', 'LOB-EN001', 'Ultra Rare', 89631139)
    entry = variant.entries[0]
    assert (entry.quantity, entry.list_price, entry.storage_location) == (3, 2.5, 'Caja A')


def test_ygo_return_stock_adds_to_an_existing_pile():
    collection = ygo_collection()
    CollectionEditor.return_stock(collection, ygo_line(2))
    assert collection.cards[0].variants[0].entries[0].quantity == 5


def game_collection():
    entry = CollectionEntry(condition='Near Mint', language='EN', quantity=2, list_price=4.0)
    variant = GameCollectionVariant(printing_id='p1', set_code='MH3', number='12', rarity='rare', finish='foil',
                                    entries=[entry])
    return GameCollection(game='magic', name='Tienda',
                          cards=[GameCollectionCard(card_id='c1', name='Ragavan', variants=[variant])])


def game_line(quantity=1, **extra):
    fields = dict(game='magic', collection='tienda.json', card_id='c1', name='Ragavan', set_code='MH3', number='12',
                  rarity='rare', variant_id='p1', finish='foil', quantity=quantity, unit_cents=400, list_price=4.0)
    fields.update(extra)
    return SaleLine(**fields)


def test_game_take_and_return_round_trip():
    collection = game_collection()
    GameCollectionEditor.take_stock(collection, game_line(2))
    assert collection.cards == []
    GameCollectionEditor.return_stock(collection, game_line(2))
    variant = collection.cards[0].variants[0]
    assert (variant.printing_id, variant.finish, variant.number, variant.rarity) == ('p1', 'foil', '12', 'rare')
    assert (variant.entries[0].quantity, variant.entries[0].list_price) == (2, 4.0)


def test_game_take_other_finish_is_out_of_stock():
    with pytest.raises(OutOfStock):
        GameCollectionEditor.take_stock(game_collection(), game_line(1, finish='nonfoil'))


def test_custom_lines_never_touch_stock():
    collection = ygo_collection()
    CollectionEditor.take_stock(collection, SaleLine(kind='custom', name='Fundas', unit_cents=500))
    CollectionEditor.return_stock(collection, SaleLine(kind='custom', name='Fundas', unit_cents=500))
    assert collection.total_cards == 4
