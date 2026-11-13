"""Registered price sources, keyed by (game, market)."""

from __future__ import annotations

import os

from src.services.prices.base import PriceSource

PRICES_DIR = os.path.join('data', 'prices')
MARKETS = {'cardmarket': 'EUR', 'tcgplayer': 'USD'}
SOURCES: dict[tuple[str, str], PriceSource] = {}


def register(source: PriceSource) -> None:
    SOURCES[(source.game, source.market)] = source


def get_source(game: str, market: str) -> PriceSource:
    return SOURCES[(game, market)]


def sources() -> list[PriceSource]:
    return list(SOURCES.values())


def price_path(game: str, market: str) -> str:
    return os.path.join(PRICES_DIR, f'{game}-{market}.json')
