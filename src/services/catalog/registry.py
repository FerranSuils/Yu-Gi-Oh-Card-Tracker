"""Registered game catalogs, in display order."""

from __future__ import annotations

import os

from src.services.catalog.base import CatalogProvider

CATALOG_DIR = os.path.join('data', 'catalog')
PROVIDERS: dict[str, CatalogProvider] = {}


def register(provider: CatalogProvider) -> None:
    PROVIDERS[provider.game] = provider


def get_provider(game: str) -> CatalogProvider:
    return PROVIDERS[game]


def game_ids() -> list[str]:
    return list(PROVIDERS)


def catalog_path(game: str) -> str:
    return os.path.join(CATALOG_DIR, f'{game}.json')
