import sys
from unittest.mock import MagicMock

sys.modules["nicegui"] = MagicMock()
sys.modules["nicegui.ui"] = MagicMock()
sys.modules["nicegui.run"] = MagicMock()

from src.core.models import ApiCard, ApiCardImage, ApiCardPrice, ApiCardSet
from src.core.utils import generate_variant_id
from src.ui import collection


def make_card(*, card_sets=None, cardmarket_price="1.23"):
    return ApiCard(
        id=123,
        name="Test Card",
        type="Monster",
        frameType="normal",
        desc="Test",
        card_images=[
            ApiCardImage(
                id=100,
                image_url="https://example.com/card.jpg",
                image_url_small="https://example.com/card-small.jpg",
            )
        ],
        card_sets=card_sets or [],
        card_prices=[ApiCardPrice(cardmarket_price=cardmarket_price)],
    )


def set_daily_price(monkeypatch, card_id, variant_id, price):
    monkeypatch.setattr(
        collection.pricing_service,
        "daily_pricing",
        {
            str(card_id): {
                str(variant_id): {
                    "cardmarket": {
                        "2026-06-26": "0.01",
                        "2026-06-27": str(price),
                    }
                }
            }
        },
    )


def test_exact_variant_id_match_uses_daily_pricing(monkeypatch):
    variant_id = "exact-variant-id"
    card = make_card(
        card_sets=[
            ApiCardSet(
                variant_id=variant_id,
                set_name="Legend of Blue Eyes",
                set_code="LOB-EN001",
                set_rarity="Ultra Rare",
                set_price="2.00",
                image_id=100,
            )
        ]
    )
    set_daily_price(monkeypatch, card.id, variant_id, "8.75")

    price = collection.get_display_price_for_variant(card, variant_id=variant_id)

    assert price == 8.75


def test_attribute_matching_with_image_id_uses_matching_variant_daily_price(monkeypatch):
    variant_id = generate_variant_id(123, "LOB-EN001", "Ultra Rare", 200)
    card = make_card(
        card_sets=[
            ApiCardSet(
                variant_id=variant_id,
                set_name="Legend of Blue Eyes",
                set_code="LOB-EN001",
                set_rarity="Ultra Rare",
                set_price="2.00",
                image_id=200,
            )
        ]
    )
    set_daily_price(monkeypatch, card.id, variant_id, "7.50")

    price = collection.get_display_price_for_variant(
        card,
        set_code="LOB-EN001",
        rarity="Ultra Rare",
        image_id=200,
    )

    assert price == 7.50


def test_default_image_fallback_when_image_id_is_missing_uses_daily_price(monkeypatch):
    variant_id = generate_variant_id(123, "LOB-EN001", "Ultra Rare", 100)
    card = make_card(
        card_sets=[
            ApiCardSet(
                set_name="Legend of Blue Eyes",
                set_code="LOB-EN001",
                set_rarity="Ultra Rare",
                set_price="2.00",
                image_id=None,
            )
        ]
    )
    set_daily_price(monkeypatch, card.id, variant_id, "9.99")

    price = collection.get_display_price_for_variant(
        card,
        set_code="LOB-EN001",
        rarity="Ultra Rare",
        image_id=None,
    )

    assert price == 9.99


def test_set_price_fallback_when_no_daily_pricing_and_no_cardmarket_price(monkeypatch):
    monkeypatch.setattr(collection.pricing_service, "daily_pricing", {})
    card = make_card(
        cardmarket_price="0.00",
        card_sets=[
            ApiCardSet(
                variant_id=generate_variant_id(123, "LOB-EN001", "Ultra Rare", 100),
                set_name="Legend of Blue Eyes",
                set_code="LOB-EN001",
                set_rarity="Ultra Rare",
                set_price="4.56",
                image_id=None,
            )
        ]
    )

    price = collection.get_display_price_for_variant(
        card,
        set_code="LOB-EN001",
        rarity="Ultra Rare",
        image_id=None,
    )

    assert price == 4.56


def test_generic_card_price_fallback_when_variant_and_set_price_miss(monkeypatch):
    monkeypatch.setattr(collection.pricing_service, "daily_pricing", {})
    card = make_card(
        card_sets=[
            ApiCardSet(
                set_name="Legend of Blue Eyes",
                set_code="LOB-EN001",
                set_rarity="Ultra Rare",
                set_price=None,
                image_id=100,
            )
        ],
        cardmarket_price="1.23",
    )

    price = collection.get_display_price_for_variant(
        card,
        set_code="SDK-001",
        rarity="Common",
        image_id=100,
    )

    assert price == 1.23


def beyond_the_brave_set(set_price):
    return ApiCardSet(
        variant_id=generate_variant_id(123, "BETB-EN095", "Common", 100),
        set_name="Beyond the Brave",
        set_code="BETB-EN095",
        set_rarity="Common",
        set_price=set_price,
        image_id=None,
    )


def test_a_zero_set_price_does_not_hide_the_cardmarket_price(monkeypatch):
    # YGOPRODeck leaves most printings at "0.00": that is "unknown", not "worth nothing".
    monkeypatch.setattr(collection.pricing_service, "daily_pricing", {})
    card = make_card(card_sets=[beyond_the_brave_set("0.00")], cardmarket_price="0.11")

    price = collection.get_display_price_for_variant(card, set_code="BETB-EN095", rarity="Common")

    assert price == 0.11


def test_the_cardmarket_price_wins_over_the_tcgplayer_set_price(monkeypatch):
    # set_price is TCGplayer USD; the tile and the Value metric are shown in Cardmarket EUR.
    monkeypatch.setattr(collection.pricing_service, "daily_pricing", {})
    card = make_card(card_sets=[beyond_the_brave_set("4.56")], cardmarket_price="0.11")

    price = collection.get_display_price_for_variant(card, set_code="BETB-EN095", rarity="Common")

    assert price == 0.11
