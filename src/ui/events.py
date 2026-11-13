"""/eventos: the shop's tournaments — who is in, who plays whom and how they stand."""

from __future__ import annotations

from datetime import date
from typing import Dict

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.account_scope import account_root
from src.core.event_models import RESULT_LABELS, STATUS_LABELS, Event, Match
from src.core.sales_models import format_money, to_cents
from src.services.events.store import EventStore
from src.services.events.swiss import standings
from src.services.shop.desk import desk_for
from src.ui.icons import icon
from src.ui.shop_common import SHOP_CSS, customer_options, game_name, shop_failure
from src.ui.theme import page_header

ICONS = ('calendar-plus', 'user-plus', 'user-minus', 'undo', 'trash', 'play', 'arrow-right', 'flag', 'trophy')


def _day(text: str) -> str:
    try:
        return date.fromisoformat(text).strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return text or ''


def fee_cents(text) -> int:
    """What it costs to enter, typed by a person. Nothing typed, or 0, is a free event."""
    return to_cents(text)


def event_line(event: Event, currency: str) -> str:
    """When, what game, how many are in and what is still owed, in one line."""
    count = len(event.players)
    parts = [_day(event.date), game_name(event.game) if event.game else '',
             f'{count} de {event.capacity} apuntados' if event.capacity else f'{count} apuntados',
             f'Inscripción {format_money(event.fee_cents, currency)}' if event.fee_cents else 'Gratis']
    owing = sum(1 for player in event.players if not player.paid) if event.fee_cents else 0
    if owing:
        parts.append(f'{owing} sin pagar')
    return ' · '.join(part for part in parts if part)


def table_text(match: Match, names: Dict[str, str]) -> str:
    first = names.get(match.a, '?')
    if match.bye:
        return f'{first} descansa (cuenta como victoria)'
    return f'{first} — {names.get(match.b, "?")}'


def result_options(match: Match, names: Dict[str, str]) -> Dict[str, str]:
    return {'': RESULT_LABELS[''], 'a': f'Gana {names.get(match.a, "?")}', 'b': f'Gana {names.get(match.b, "?")}',
            'draw': RESULT_LABELS['draw']}


def round_status(event: Event) -> str:
    if not event.rounds:
        return ''
    missing = sum(1 for match in event.rounds[-1].matches if not match.result)
    number = len(event.rounds)
    if not missing:
        return f'Ronda {number} · completa'
    return f'Ronda {number} · falta{"n" if missing > 1 else ""} {missing} resultado{"s" if missing > 1 else ""}'


def events_page() -> None:
    ui.add_css(SHOP_CSS)
    profile = load_profile()
    page_header('Eventos', 'Torneos de la tienda: inscripciones, emparejamientos y clasificación.')
    if not profile.shop_mode:
        ui.label('Los eventos son parte del modo tienda. Actívalo en Ajustes → Modo tienda.').classes('oy-sub')
        return

    currency = profile.shop.currency
    root = account_root()
    store = EventStore(root)
    desk = desk_for(root, currency)
    games = {game: game_name(game) for game in enabled_games(profile)}
    state = {'events': [], 'customers': [], 'open': None, 'loaded': False, 'busy': False}
    holder = ui.element('div')

    def read():
        try:
            customers = desk.customers.all()
        except Exception:  # the events still show; players are then entered by name only
            customers = []
        return store.all(), customers

    async def load() -> None:
        try:
            state['events'], state['customers'] = await run.io_bound(read)
        except Exception as error:
            with holder:
                ui.notify(shop_failure(error, 'No se pudieron leer los eventos. Recarga la página.'), type='negative')
            return
        state['loaded'] = True
        if state['open'] not in [event.id for event in state['events']]:
            state['open'] = None
        listing.refresh()
        detail.refresh()

    async def attempt(action, *args, done: str = '', fallback: str = 'No se pudo guardar. Inténtalo de nuevo.'):
        """Run one change off the UI thread. True when it went through."""
        if state['busy']:
            return False
        state['busy'] = True
        try:
            await run.io_bound(action, *args)
        except Exception as error:
            with holder:
                ui.notify(shop_failure(error, fallback), type='negative', multi_line=True)
            await load()   # what is on screen may be stale: show what the book really says
            return False
        finally:
            state['busy'] = False
        await load()
        if done:
            with holder:
                ui.notify(done, type='positive')
        return True

    def show(event_id) -> None:
        state['open'] = event_id
        listing.refresh()
        detail.refresh()

    # --- dialogs -----------------------------------------------------------------------------

    def create() -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 340px'):
            ui.label('Nuevo evento').classes('text-h6')
            name = ui.input('Nombre').props('outlined dense maxlength=80 autofocus').classes('w-full')
            game = ui.select(games, label='Juego', value=next(iter(games), None)).props('outlined dense').classes(
                'w-full')
            day = ui.input('Fecha', value=date.today().isoformat()).props('outlined dense type=date').classes('w-full')
            fee = ui.input('Inscripción', value='0').props(f'outlined dense suffix={currency}').classes('w-full')
            capacity = ui.number('Aforo (0 = sin límite)', value=0, min=0, max=512, step=1, format='%d').props(
                'outlined dense').classes('w-full')

            async def save() -> None:
                try:
                    cents = fee_cents(fee.value)
                except ValueError:
                    ui.notify('La inscripción no es un importe válido.', type='warning')
                    return
                made = {}

                def make() -> None:
                    made['event'] = store.create(name.value, game.value or '', day.value, cents,
                                                 int(capacity.value or 0))

                if await attempt(make, done='Evento creado.'):
                    dialog.close()
                    show(made['event'].id)

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Crear', on_click=save).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    def confirm(title: str, text: str, label: str, action, *args, done: str = '', danger: bool = False) -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('max-width: 420px'):
            ui.label(title).classes('text-h6')
            ui.label(text).classes('oy-sub')

            async def go() -> None:
                dialog.close()
                await attempt(action, *args, done=done)

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button(label, on_click=go).props(f'no-caps color={"negative" if danger else "secondary"}')
        dialog.on('hide', dialog.delete)
        dialog.open()

    # --- the list ----------------------------------------------------------------------------

    with ui.row().classes('w-full items-center justify-end q-mt-md'):
        with ui.button(on_click=create).props('no-caps color=secondary'):
            icon('calendar-plus')
            ui.label('Nuevo evento').classes('q-ml-xs')

    @ui.refreshable
    def listing() -> None:
        if not state['loaded']:
            ui.label('Cargando eventos…').classes('oy-sub')
            return
        if not state['events']:
            ui.label('Todavía no hay eventos. Crea el primero para abrir inscripciones.').classes('oy-sub')
            return
        for event in state['events']:
            chosen = event.id == state['open']
            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm no-wrap'):
                with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                    ui.label(event.name).classes('text-sm ellipsis w-full' + (' text-weight-bold' if chosen else ''))
                    ui.label(event_line(event, currency)).classes('oy-sub text-xs ellipsis w-full')
                ui.label(STATUS_LABELS[event.status]).classes('oy-sub text-xs')
                with ui.button(on_click=lambda e=event: show(e.id)).props('flat dense round color=primary').tooltip(
                        'Abrir'):
                    icon('arrow-right')
                with ui.button(on_click=lambda e=event: confirm(
                        f'¿Borrar {e.name}?', 'Se borran sus inscripciones, rondas y clasificación.', 'Borrar',
                        store.remove, e.id, done='Evento borrado.', danger=True)).props(
                        'flat dense round color=primary').tooltip('Borrar'):
                    icon('trash')

    # --- one event ---------------------------------------------------------------------------

    def players_block(event: Event) -> None:
        ui.label('Inscripciones').classes('text-subtitle1 q-mt-md')
        if event.status == 'open':
            with ui.row().classes('w-full items-center gap-2'):
                name = ui.input(placeholder='Nombre').props('outlined dense maxlength=80').style(
                    'min-width: 0; flex: 1')
                who = ui.select(customer_options(state['customers'], {}, currency, None), label='Cliente (opcional)',
                                with_input=True, clearable=True).props('outlined dense').style('min-width: 200px')

                async def enter() -> None:
                    customer = next((c for c in state['customers'] if c.id == who.value), None)
                    typed = (name.value or '').strip() or (customer.name if customer else '')
                    await attempt(store.enter, event.id, typed, customer.id if customer else '')

                name.on('keydown.enter', enter)
                with ui.button(on_click=enter).props('no-caps color=secondary'):
                    icon('user-plus')
                    ui.label('Apuntar').classes('q-ml-xs')
        if not event.players:
            ui.label('Nadie apuntado todavía.').classes('oy-sub')
        for player in event.players:
            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-xs no-wrap'):
                label = ui.label(player.name).classes('text-sm ellipsis').style('min-width: 0; flex: 1')
                if player.dropped:
                    label.classes('oy-sub')
                    ui.label('Retirado').classes('oy-sub text-xs')
                if event.fee_cents:
                    ui.checkbox('Pagado', value=player.paid, on_change=lambda e, p=player: attempt(
                        store.set_paid, event.id, p.id, bool(e.value))).props('dense')
                if event.status == 'finished':
                    continue
                if player.dropped:
                    with ui.button(on_click=lambda p=player: attempt(store.drop, event.id, p.id, False)).props(
                            'flat dense round color=primary').tooltip('Vuelve a jugar desde la ronda siguiente'):
                        icon('undo')
                elif event.status == 'open':
                    with ui.button(on_click=lambda p=player: attempt(store.drop, event.id, p.id)).props(
                            'flat dense round color=primary').tooltip('Quitar de la lista'):
                        icon('user-minus')
                else:
                    with ui.button(on_click=lambda p=player: confirm(
                            f'¿Retirar a {p.name}?',
                            'No se le empareja más. Si su mesa de esta ronda no tiene resultado, gana su rival.',
                            'Retirar', store.drop, event.id, p.id)).props('flat dense round color=primary').tooltip(
                            'Retirar del evento'):
                        icon('user-minus')

    def rounds_block(event: Event, names: Dict[str, str]) -> None:
        if not event.rounds:
            return
        ui.label(round_status(event)).classes('text-subtitle1 q-mt-md')
        for table, match in enumerate(event.rounds[-1].matches):
            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-xs no-wrap'):
                ui.label(f'Mesa {table + 1}').classes('oy-sub text-xs').style('width: 56px')
                ui.label(table_text(match, names)).classes('text-sm ellipsis').style('min-width: 0; flex: 1')
                if match.bye:
                    continue
                if event.status == 'running':
                    ui.select(result_options(match, names), value=match.result,
                              on_change=lambda e, t=table: attempt(store.report, event.id, t, e.value or '', len(event.rounds))).props(
                        'outlined dense options-dense').style('min-width: 170px')
                else:
                    ui.label(result_options(match, names)[match.result]).classes('oy-sub text-xs')
        if len(event.rounds) > 1:
            with ui.expansion('Rondas anteriores').classes('w-full'):
                for number, one in enumerate(event.rounds[:-1], start=1):
                    ui.label(f'Ronda {number}').classes('oy-sub text-xs q-mt-sm')
                    for match in one.matches:
                        text = table_text(match, names)
                        if not match.bye:
                            text += f' · {result_options(match, names)[match.result]}'
                        ui.label(text).classes('text-sm')

    def standings_block(event: Event) -> None:
        if not event.rounds:
            return
        with ui.row().classes('items-center gap-2 q-mt-md'):
            icon('trophy')
            ui.label('Clasificación').classes('text-subtitle1')
        for place, row in enumerate(standings(event), start=1):
            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-xs no-wrap'):
                ui.label(str(place)).classes('oy-mono').style('width: 28px')
                label = ui.label(row.name + (' (retirado)' if row.dropped else '')).classes('text-sm ellipsis').style(
                    'min-width: 0; flex: 1')
                if row.dropped:
                    label.classes('oy-sub')
                ui.label(f'{row.wins}-{row.draws}-{row.losses}').classes('oy-sub text-xs').tooltip(
                    'Victorias, empates y derrotas')
                ui.label(f'{round(row.opponents * 100)} %').classes('oy-sub text-xs').style(
                    'width: 48px; text-align: right').tooltip('Porcentaje de victorias de sus rivales')
                ui.label(f'{row.points} pts').classes('oy-mono').style('width: 64px; text-align: right')

    @ui.refreshable
    def detail() -> None:
        event = next((one for one in state['events'] if one.id == state['open']), None)
        if event is None:
            return
        names = {player.id: player.name for player in event.players}
        with ui.column().classes('oy-pos-ticket w-full q-pa-md q-mt-lg gap-1'):
            with ui.row().classes('w-full items-center gap-2'):
                with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                    ui.label(event.name).classes('text-h6 ellipsis w-full')
                    ui.label(f'{STATUS_LABELS[event.status]} · {event_line(event, currency)}').classes(
                        'oy-sub text-xs')
                if event.status == 'open':
                    with ui.button(on_click=lambda: confirm(
                            '¿Empezar el evento?', 'Se cierran las inscripciones y se empareja la primera ronda.',
                            'Empezar', store.start, event.id)).props('no-caps color=secondary'):
                        icon('play')
                        ui.label('Empezar').classes('q-ml-xs')
                elif event.status == 'running':
                    with ui.button(on_click=lambda: attempt(store.next_round, event.id)).props(
                            'no-caps color=secondary'):
                        icon('arrow-right')
                        ui.label('Siguiente ronda').classes('q-ml-xs')
                    with ui.button(on_click=lambda: confirm(
                            '¿Terminar el evento?', 'La clasificación queda como está y no se juegan más rondas.',
                            'Terminar', store.finish, event.id, done='Evento terminado.')).props(
                            'flat no-caps color=primary'):
                        icon('flag')
                        ui.label('Terminar').classes('q-ml-xs')
            rounds_block(event, names)
            standings_block(event)
            players_block(event)

    listing()
    detail()
    ui.timer(0.1, load, once=True)
