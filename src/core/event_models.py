"""Shop tournaments: who entered, who played whom and how it ended. Integer cents."""

from __future__ import annotations

import uuid
from typing import List, Literal

from pydantic import BaseModel, Field

from src.core.sales_models import now_iso

EventStatus = Literal['open', 'running', 'finished']
Result = Literal['', 'a', 'b', 'draw']
STATUS_LABELS = {'open': 'Inscripciones abiertas', 'running': 'En juego', 'finished': 'Terminado'}
RESULT_LABELS = {'': 'Sin resultado', 'a': 'Gana A', 'b': 'Gana B', 'draw': 'Empate'}
WIN, DRAW = 3, 1


def _id() -> str:
    return uuid.uuid4().hex


class Player(BaseModel):
    id: str = Field(default_factory=_id)
    name: str
    customer_id: str = ''
    paid: bool = False
    dropped: bool = False


class Match(BaseModel):
    """One table. An empty b is a bye: a rests and takes the win."""
    a: str
    b: str = ''
    result: Result = ''

    @property
    def bye(self) -> bool:
        return not self.b


class Round(BaseModel):
    matches: List[Match] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return all(match.result for match in self.matches)


class Event(BaseModel):
    id: str = Field(default_factory=_id)
    name: str
    game: str = ''
    date: str = ''
    fee_cents: int = Field(0, ge=0)
    capacity: int = Field(0, ge=0)   # 0: no limit
    status: EventStatus = 'open'
    players: List[Player] = Field(default_factory=list)
    rounds: List[Round] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class Standing(BaseModel):
    player_id: str
    name: str
    points: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    byes: int = 0
    opponents: float = 0.0   # mean win rate of the people faced, 0..1
    dropped: bool = False
