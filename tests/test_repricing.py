import pytest

from src.core.catalog_models import GameCollection, GameCollectionCard, GameCollectionVariant
from src.core.models import CollectionEntry
from src.core.pricing_models import PriceQuote, PricingRule, PrintingPrice
from src.services.repricing import (apply, collection_values, compute_price, preview, quote_for,
                                    validate_rule)


def _rule(**kwargs):
    return PricingRule(**{'min_price': 0.10, **kwargs})


@pytest.mark.parametrize('base, expected', [
    (1.20, 1.49), (1.49, 1.49), (1.50, 1.99), (1.99, 1.99), (2.00, 2.49), (0.01, 0.49),
])
def test_rounding_x49_x99(base, expected):
    assert compute_price(_rule(rounding='x49_x99'), PriceQuote(trend=base), 'Near Mint') == expected


@pytest.mark.parametrize('rounding, base, expected', [
    ('step_005', 1.23, 1.25), ('step_005', 1.22, 1.20), ('none', 1.234, 1.23),
])
def test_other_roundings(rounding, base, expected):
    assert compute_price(_rule(rounding=rounding), PriceQuote(trend=base), 'Near Mint') == expected


def test_minimum_applies_after_rounding():
    assert compute_price(_rule(min_price=0.25), PriceQuote(trend=0.05), 'Near Mint') == 0.25


def test_formula_percent_fixed_and_condition():
    rule = _rule(percent=95, fixed=0.5)
    assert compute_price(rule, PriceQuote(trend=10), 'Excellent') == 9.05


def test_missing_metric_falls_back_to_trend_then_avg_then_low():
    rule = _rule(metric='avg30')
    assert compute_price(rule, PriceQuote(trend=2.0, avg=3.0), 'Near Mint') == 2.0
    assert compute_price(rule, PriceQuote(avg=3.0, low=1.0), 'Near Mint') == 3.0
    assert compute_price(rule, PriceQuote(low=1.0), 'Near Mint') == 1.0
    assert compute_price(rule, PriceQuote(), 'Near Mint') is None
    assert compute_price(rule, None, 'Near Mint') is None


def test_unknown_condition_uses_factor_100():
    assert compute_price(_rule(), PriceQuote(trend=4.0), 'Signed') == 4.0


def test_quote_for_foil_falls_back_to_normal():
    both = PrintingPrice(normal=PriceQuote(trend=1), foil=PriceQuote(trend=5))
    assert quote_for(both, 'foil').trend == 5 and quote_for(both, 'etched').trend == 5
    assert quote_for(both, 'nonfoil').trend == 1
    assert quote_for(PrintingPrice(normal=PriceQuote(trend=1)), 'foil').trend == 1
    assert quote_for(None, 'foil') is None


def _collection():
    entries = [CollectionEntry(quantity=2, list_price=1.0),
               CollectionEntry(condition='Good', quantity=1, list_price=3.0, price_locked=True),
               CollectionEntry(condition='Played', quantity=1, list_price=4.0)]
    return GameCollection(game='magic', name='M', cards=[
        GameCollectionCard(card_id='o1', name='Bolt', variants=[
            GameCollectionVariant(printing_id='p1', set_code='m10', entries=entries[:2]),
            GameCollectionVariant(printing_id='p1', set_code='m10', finish='foil', entries=[entries[2]])]),
        GameCollectionCard(card_id='o2', name='Nothing', variants=[
            GameCollectionVariant(printing_id='p-none', set_code='x', entries=[CollectionEntry(quantity=5)])]),
    ])


PRICES = {'p1': PrintingPrice(normal=PriceQuote(trend=2.0), foil=PriceQuote(trend=10.0))}


def test_preview_statuses_and_apply_writes_only_changes():
    collection = _collection()
    rows = preview(collection, PRICES.get, _rule())
    assert [r.status for r in rows] == ['cambia', 'bloqueada', 'cambia', 'sin precio']
    assert rows[0].new == 2.0 and rows[0].delta == 1.0 and rows[0].market == 2.0
    assert rows[2].new == 6.0  # foil 10.0 × Played 60 %
    assert rows[1].new is None or rows[1].ref.entry.list_price == 3.0
    assert apply(collection, rows) == 2
    entries = [r.ref.entry for r in rows]
    assert [e.list_price for e in entries] == [2.0, 3.0, 6.0, None]
    again = preview(collection, PRICES.get, _rule())
    assert again[0].status == 'igual'
    assert apply(collection, again) == 0


def test_collection_values():
    collection = _collection()
    market, sale = collection_values(collection, PRICES.get)
    # market: 2×2.0 + 1×2.0 + 1×10.0 ; sale: 2×1.0 + 1×3.0 + 1×4.0
    assert (market, sale) == (16.0, 9.0)


def test_validate_rule():
    assert validate_rule(_rule()) == []
    assert validate_rule(_rule(percent=0))
    bad = _rule()
    bad.condition_factors['Good'] = -5
    assert validate_rule(bad)
    assert validate_rule(_rule(min_price=-1))


def test_card_level_prices_are_reference_only_unless_the_rule_allows_them():
    collection = GameCollection(game='magic', name='M', cards=[GameCollectionCard(card_id='o', name='BEWD', variants=[
        GameCollectionVariant(printing_id='v-lob', set_code='LOB', entries=[CollectionEntry(list_price=80.0)])])])
    card_level = {'v-lob': PrintingPrice(normal=PriceQuote(trend=0.5), scope='card')}
    rows = preview(collection, card_level.get, _rule())
    assert rows[0].status == 'por carta' and rows[0].market == 0.5
    assert apply(collection, rows) == 0 and collection.cards[0].variants[0].entries[0].list_price == 80.0
    rows = preview(collection, card_level.get, _rule(use_card_prices=True))
    assert rows[0].status == 'cambia' and rows[0].new == 0.5
