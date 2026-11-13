"""Per-account profile: which games are on and whether the account runs a shop."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from src.core.account_scope import account_root
from src.core.shop_models import BuylistRules

logger = logging.getLogger(__name__)
PROFILE_FILE = 'profile.json'


class ShopProfile(BaseModel):
    name: str = ''
    address: str = ''
    city: str = ''
    country: str = ''
    currency: str = 'EUR'
    email: str = ''


class AccountProfile(BaseModel):
    shop_mode: bool = False
    enabled_games: List[str] = Field(default_factory=lambda: ['yugioh'])
    shop: ShopProfile = Field(default_factory=ShopProfile)
    # Market whose prices this account sells by: Cardmarket (EUR) or TCGplayer (USD).
    price_market: Literal['cardmarket', 'tcgplayer'] = 'cardmarket'
    # What the shop pays when it buys cards from customers.
    buylist: BuylistRules = Field(default_factory=BuylistRules)


def _path(root: Optional[str]) -> str:
    return os.path.join(root if root is not None else account_root(), PROFILE_FILE)


def load_profile(root: Optional[str] = None) -> AccountProfile:
    path = _path(root)
    if not os.path.exists(path):
        return AccountProfile()
    try:
        with open(path, 'r', encoding='utf-8') as file:
            return AccountProfile(**json.load(file))
    except Exception as exc:
        logger.error('Profile %s is unreadable: %s', path, exc)
        return AccountProfile()


def save_profile(profile: AccountProfile, root: Optional[str] = None) -> None:
    path = _path(root)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.profile-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(profile.model_dump(mode='json'), file, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def enabled_games(profile: AccountProfile) -> list[str]:
    from src.services.catalog import game_ids

    known = game_ids()
    games = ['yugioh'] + [g for g in profile.enabled_games if g != 'yugioh']
    return [g for g in dict.fromkeys(games) if g in known]
