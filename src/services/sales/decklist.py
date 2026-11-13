"""A pasted deck list against the shop's stock: what there is, at what price, and what is missing."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

from pydantic import BaseModel

from src.core.sales_models import SaleLine
from src.services.shop.kiosk import shelf

MAX_COPIES = 99    # per card, the same ceiling the kiosk puts on a line
MAX_CARDS = 200    # different cards in one list
MAX_NAME = 120
MAX_TEXT = 20000

_COUNTED = re.compile(r'(\d+)\s*[xX]?(?:\s+(.*))?')
_APOSTROPHES = str.maketrans({'’': "'", '‘': "'", '`': "'", '´': "'"})


class Wanted(BaseModel):
    name: str
    quantity: int


class Found(BaseModel):
    name: str
    wanted: int
    in_stock: int = 0             # priced copies on the shelves when this line was looked up
    missing: int = 0
    lines: List[SaleLine] = []    # the copies to take, cheapest first
    cents: int = 0


def _key(name: str) -> str:
    return ' '.join(name.translate(_APOSTROPHES).casefold().split())


def parse(text: Optional[str]) -> List[Wanted]:
    """`3 Dark Hole`, `3x Dark Hole` or `Dark Hole` (one copy). Comments, titles and blank lines are skipped."""
    wanted: Dict[str, Wanted] = {}
    for raw in str(text or '')[:MAX_TEXT].splitlines():
        line = ' '.join(raw.split())
        if not line or line.startswith(('//', '#')) or line.endswith(':'):
            continue
        counted = _COUNTED.fullmatch(line)
        if counted:
            quantity, name = min(int(counted.group(1)), MAX_COPIES), (counted.group(2) or '')
        else:
            quantity, name = 1, line
        name = name[:MAX_NAME].strip()
        if quantity < 1 or len(name) < 2:
            continue
        key = _key(name)
        if key in wanted:
            wanted[key].quantity = min(wanted[key].quantity + quantity, MAX_COPIES)
        elif len(wanted) < MAX_CARDS:
            wanted[key] = Wanted(name=name, quantity=quantity)
    return list(wanted.values())


def match(wanted: Iterable[Wanted], items: Iterable[SaleLine]) -> List[Found]:
    """Look each card up by name in the priced stock of any game, taking the cheapest copies first."""
    piles: Dict[str, List[SaleLine]] = {}
    for line in shelf(list(items)):
        piles.setdefault(_key(line.name), []).append(line)
    for same in piles.values():
        same.sort(key=lambda line: line.unit_cents)
    left = {id(line): line.quantity for same in piles.values() for line in same}
    found = []
    for want in wanted:
        same = piles.get(_key(want.name), [])
        in_stock = sum(left[id(line)] for line in same)
        need, taken = want.quantity, []
        for line in same:
            take = min(need, left[id(line)])
            if take > 0:
                taken.append(line.model_copy(update={'quantity': take}))
                left[id(line)] -= take
                need -= take
        found.append(Found(name=want.name, wanted=want.quantity, in_stock=in_stock, missing=need, lines=taken,
                           cents=sum(line.unit_cents * line.quantity for line in taken)))
    return found


def _same_pile(line: SaleLine) -> tuple:
    return (line.game, line.collection, line.card_id, line.variant_id, line.finish, line.condition, line.language,
            line.first_edition, line.unit_cents)


def available_lines(found: Iterable[Found]) -> List[SaleLine]:
    """Everything that could be taken, as lines the counter can load."""
    merged: Dict[tuple, SaleLine] = {}
    for card in found:
        for line in card.lines:
            key = _same_pile(line)
            if key in merged:
                merged[key] = merged[key].model_copy(update={'quantity': merged[key].quantity + line.quantity})
            else:
                merged[key] = line
    return list(merged.values())


def total_cents(found: Iterable[Found]) -> int:
    return sum(card.cents for card in found)
