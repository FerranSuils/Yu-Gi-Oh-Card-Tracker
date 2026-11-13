from src.core.pricing_models import DEFAULT_CONDITION_FACTORS, PriceQuote, PricingRule, PrintingPrice, to_price


def test_rule_defaults():
    rule = PricingRule()
    assert rule.metric == 'trend' and rule.percent == 100.0 and rule.fixed == 0.0
    assert rule.min_price == 0.10 and rule.rounding == 'none' and rule.auto_apply is False
    assert rule.condition_factors['Excellent'] == 90
    assert rule.condition_factors == DEFAULT_CONDITION_FACTORS
    assert DEFAULT_CONDITION_FACTORS == {'Mint': 100, 'Near Mint': 100, 'Excellent': 90, 'Good': 80,
                                         'Light Played': 70, 'Played': 60, 'Poor': 40, 'Damaged': 30}


def test_rule_factors_are_not_shared_between_rules():
    a, b = PricingRule(), PricingRule()
    a.condition_factors['Good'] = 1
    assert b.condition_factors['Good'] == 80


def test_to_price():
    assert to_price('1.5') == 1.5 and to_price(2) == 2.0
    for empty in ('', 0, '0', 'abc', None, -1):
        assert to_price(empty) is None


def test_printing_price_defaults():
    price = PrintingPrice(normal=PriceQuote(trend=1.0))
    assert price.scope == 'printing' and price.foil is None and price.normal.low is None
