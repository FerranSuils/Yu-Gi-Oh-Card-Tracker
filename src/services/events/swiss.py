"""Swiss pairing and standings. Pure sums: nothing here reads or writes a file."""

from __future__ import annotations

import random
from typing import Dict, FrozenSet, List, Optional, Sequence, Set

from src.core.event_models import DRAW, WIN, Event, Match, Player, Round, Standing

FLOOR = 1 / 3          # nobody counts for less than this as an opponent
SEARCH_BUDGET = 20_000  # tries before settling for a rematch


class _Record:
    def __init__(self):
        self.points = self.wins = self.draws = self.losses = self.byes = 0
        self.faced: List[str] = []

    @property
    def rate(self) -> float:
        """Share of the points on offer in matches really played; byes are left out."""
        played = self.wins + self.draws + self.losses - self.byes
        if played <= 0:
            return 0.0
        return (self.points - WIN * self.byes) / (WIN * played)


def _records(player_ids: Sequence[str], rounds: Sequence[Round]) -> Dict[str, _Record]:
    table = {player_id: _Record() for player_id in player_ids}

    def note(player_id: str, outcome: str, rival: str = '') -> None:
        record = table.get(player_id)
        if record is None:
            return
        if outcome == 'win':
            record.points += WIN
            record.wins += 1
        elif outcome == 'draw':
            record.points += DRAW
            record.draws += 1
        else:
            record.losses += 1
        if rival:
            record.faced.append(rival)

    for one in rounds:
        for match in one.matches:
            if match.bye:
                note(match.a, 'win')
                if match.a in table:
                    table[match.a].byes += 1
            elif match.result == 'draw':
                note(match.a, 'draw', match.b)
                note(match.b, 'draw', match.a)
            elif match.result in ('a', 'b'):
                winner, loser = (match.a, match.b) if match.result == 'a' else (match.b, match.a)
                note(winner, 'win', loser)
                note(loser, 'loss', winner)
    return table


def standings(event: Event) -> List[Standing]:
    """Points, then how well the people you faced did (never below a third), then the name."""
    table = _records([player.id for player in event.players], event.rounds)
    rows = []
    for player in event.players:
        record = table[player.id]
        rates = [max(FLOOR, table[rival].rate) for rival in record.faced if rival in table]
        rows.append(Standing(
            player_id=player.id, name=player.name, points=record.points, wins=record.wins, draws=record.draws,
            losses=record.losses, byes=record.byes, opponents=sum(rates) / len(rates) if rates else 0.0,
            dropped=player.dropped))
    return sorted(rows, key=lambda row: (-row.points, -row.opponents, row.name.casefold()))


def _met(rounds: Sequence[Round]) -> Set[FrozenSet[str]]:
    return {frozenset((match.a, match.b)) for one in rounds for match in one.matches if match.b}


def _match_up(order: List[str], met: Set[FrozenSet[str]]) -> Optional[List[tuple]]:
    """Pair neighbours in the order given without a rematch, or None if the search gives up."""
    budget = [SEARCH_BUDGET]

    def search(left: List[str]) -> Optional[List[tuple]]:
        if not left:
            return []
        budget[0] -= 1
        if budget[0] < 0:
            return None
        first, rest = left[0], left[1:]
        for index, rival in enumerate(rest):
            if frozenset((first, rival)) in met:
                continue
            others = search(rest[:index] + rest[index + 1:])
            if others is not None:
                return [(first, rival)] + others
            if budget[0] < 0:
                return None
        return None

    return search(order)


def _settle(order: List[str], met: Set[FrozenSet[str]]) -> List[tuple]:
    """No clean pairing exists: take a new rival where there is one, a rematch where there is not."""
    pairs, left = [], list(order)
    while left:
        first = left.pop(0)
        index = next((i for i, rival in enumerate(left) if frozenset((first, rival)) not in met), 0)
        pairs.append((first, left.pop(index)))
    return pairs


def pair(players: Sequence[Player], rounds: Sequence[Round], rng: Optional[random.Random] = None) -> List[Match]:
    """The next round for the players still in: by points, no rematch while one can be avoided.

    With an odd field the last player who has not rested yet gets the bye, which counts as a win.
    """
    active = [player.id for player in players if not player.dropped]
    table = _records(active, rounds)
    (rng or random.Random()).shuffle(active)
    active.sort(key=lambda player_id: -table[player_id].points)   # stable: the shuffle breaks ties

    resting = ''
    if len(active) % 2:
        fresh = [player_id for player_id in active if not table[player_id].byes]
        if fresh:
            resting = fresh[-1]
        else:   # everybody has rested: the one who has rested least, lowest first
            resting = min(reversed(active), key=lambda player_id: table[player_id].byes)
        active.remove(resting)

    met = _met(rounds)
    pairs = _match_up(active, met)
    if pairs is None:
        pairs = _settle(active, met)
    matches = [Match(a=a, b=b) for a, b in pairs]
    if resting:
        matches.append(Match(a=resting, result='a'))
    return matches
