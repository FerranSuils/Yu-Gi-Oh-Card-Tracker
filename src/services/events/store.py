"""The shop's tournaments, kept in <cuenta>/shop/events.json."""

from __future__ import annotations

import random
from datetime import date as calendar
from typing import Callable, List, Optional

from src.core.event_models import Event, Player, Round
from src.services.events.swiss import pair
from src.services.shop.files import BrokenFile, read_list, root_lock, shop_path, write_list

FILE = 'events.json'
MAX_NAME = 80
MAX_EVENTS = 500
MAX_PLAYERS = 512
MAX_ROUNDS = 20
MAX_FEE_CENTS = 10_000_000
RESULTS = ('', 'a', 'b', 'draw')


class EventError(Exception):
    """Something about a tournament that the person running it must read."""

    spoken = True


def _whole(value, label: str, top: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > top:
        raise EventError(f'{label} debe ser un número entre 0 y {top}.')
    return value


class EventStore:
    def __init__(self, root: str):
        self._path = shop_path(root, FILE)
        self._lock = root_lock(root)

    # --- reading -----------------------------------------------------------------------------

    def _read(self) -> List[Event]:
        try:
            return read_list(self._path, Event)
        except BrokenFile as error:
            raise EventError(f'El fichero {error} está dañado; no se ha tocado.') from error

    def all(self) -> List[Event]:
        """Latest date first."""
        return sorted(self._read(), key=lambda event: (event.date, event.created_at), reverse=True)

    def get(self, event_id: Optional[str]) -> Optional[Event]:
        return next((event for event in self._read() if event.id == event_id), None)

    # --- writing -----------------------------------------------------------------------------

    def _change(self, event_id: str, action: Callable[[Event], None]) -> Event:
        with self._lock:
            events = self._read()
            event = next((one for one in events if one.id == event_id), None)
            if event is None:
                raise EventError('Ese evento no existe.')
            action(event)
            write_list(self._path, events)
            return event

    def create(self, name: str, game: str, date: str, fee_cents: int = 0, capacity: int = 0) -> Event:
        name = str(name or '').strip()[:MAX_NAME]
        if not name:
            raise EventError('El evento necesita un nombre.')
        try:
            day = calendar.fromisoformat(str(date or '').strip()).isoformat()
        except ValueError as error:
            raise EventError('La fecha no es válida.') from error
        fee_cents = _whole(fee_cents, 'La inscripción', MAX_FEE_CENTS)
        capacity = _whole(capacity, 'El aforo', MAX_PLAYERS)
        with self._lock:
            events = self._read()
            if len(events) >= MAX_EVENTS:
                raise EventError(f'Hay {MAX_EVENTS} eventos guardados. Borra los antiguos para crear más.')
            event = Event(name=name, game=str(game or '').strip()[:40], date=day, fee_cents=fee_cents,
                          capacity=capacity)
            write_list(self._path, events + [event])
        return event

    def remove(self, event_id: str) -> None:
        with self._lock:
            events = self._read()
            left = [event for event in events if event.id != event_id]
            if len(left) == len(events):
                raise EventError('Ese evento no existe.')
            write_list(self._path, left)

    # --- the list of players -----------------------------------------------------------------

    def enter(self, event_id: str, name: str, customer_id: str = '') -> Event:
        name = str(name or '').strip()[:MAX_NAME]

        def action(event: Event) -> None:
            if event.status != 'open':
                raise EventError('Las inscripciones están cerradas: el evento ya ha empezado.')
            if not name:
                raise EventError('Escribe el nombre de quien se apunta.')
            if any(player.name.casefold() == name.casefold() for player in event.players):
                raise EventError(f'{name} ya está en la lista.')
            if len(event.players) >= (event.capacity or MAX_PLAYERS):
                raise EventError('El evento está lleno.')
            event.players.append(Player(name=name, customer_id=str(customer_id or '')))

        return self._change(event_id, action)

    @staticmethod
    def _player(event: Event, player_id: str) -> Player:
        player = next((one for one in event.players if one.id == player_id), None)
        if player is None:
            raise EventError('Esa persona no está en el evento.')
        return player

    def set_paid(self, event_id: str, player_id: str, paid: bool) -> Event:
        def action(event: Event) -> None:
            self._player(event, player_id).paid = bool(paid)

        return self._change(event_id, action)

    def drop(self, event_id: str, player_id: str, dropped: bool = True) -> Event:
        """Before the start the player leaves the list; once running they stop being paired.

        A match of theirs still open in the current round goes to the opponent.
        """
        def action(event: Event) -> None:
            player = self._player(event, player_id)
            if event.status == 'finished':
                raise EventError('El evento ya ha terminado.')
            if event.status == 'open':
                event.players.remove(player)
                return
            player.dropped = bool(dropped)
            if not dropped:
                return
            for match in event.rounds[-1].matches:
                if not match.bye and not match.result and player_id in (match.a, match.b):
                    match.result = 'b' if match.a == player_id else 'a'

        return self._change(event_id, action)

    # --- the rounds --------------------------------------------------------------------------

    def start(self, event_id: str, rng: Optional[random.Random] = None) -> Event:
        def action(event: Event) -> None:
            if event.status != 'open':
                raise EventError('El evento ya ha empezado.')
            if len(event.players) < 2:
                raise EventError('Hacen falta al menos dos personas para empezar.')
            event.rounds = [Round(matches=pair(event.players, [], rng))]
            event.status = 'running'

        return self._change(event_id, action)

    @staticmethod
    def _running(event: Event) -> Round:
        if event.status != 'running' or not event.rounds:
            raise EventError('El evento no está en juego.')
        return event.rounds[-1]

    def next_round(self, event_id: str, rng: Optional[random.Random] = None) -> Event:
        def action(event: Event) -> None:
            if not self._running(event).complete:
                raise EventError('Faltan resultados de la ronda en juego.')
            if len(event.rounds) >= MAX_ROUNDS:
                raise EventError(f'El evento ya tiene {MAX_ROUNDS} rondas, el máximo.')
            if sum(1 for player in event.players if not player.dropped) < 2:
                raise EventError('Quedan menos de dos personas en juego: termina el evento.')
            event.rounds.append(Round(matches=pair(event.players, event.rounds, rng)))

        return self._change(event_id, action)

    def report(self, event_id: str, table: int, result: str, round_number: Optional[int] = None) -> Event:
        """Write or correct a result of the round in play. Older rounds stay as they were.

        `round_number` is the round the screen was showing: a screen left on an older round is refused."""
        def action(event: Event) -> None:
            matches = self._running(event).matches
            if round_number is not None and round_number != len(event.rounds):
                raise EventError('Esa ronda ya no está en juego: se ha actualizado la pantalla, vuelve a anotarlo.')
            if isinstance(table, bool) or not isinstance(table, int) or not 0 <= table < len(matches):
                raise EventError('Esa mesa no existe en la ronda en juego.')
            if result not in RESULTS:
                raise EventError('Ese resultado no vale.')
            if matches[table].bye:
                raise EventError('Esa mesa es un descanso: no tiene resultado que anotar.')
            matches[table].result = result

        return self._change(event_id, action)

    def finish(self, event_id: str) -> Event:
        def action(event: Event) -> None:
            if not self._running(event).complete:
                raise EventError('Faltan resultados de la ronda en juego.')
            event.status = 'finished'

        return self._change(event_id, action)
