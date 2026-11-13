"""/lista: paste a deck list, see what the shop has of it and send what there is to the counter."""

from __future__ import annotations

import logging

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.account_scope import account_root
from src.core.sales_models import format_money
from src.services.sales import decklist
from src.services.shop.desk import desk_for
from src.services.shop.kiosk import KioskError
from src.ui.icons import icon
from src.ui.theme import page_header

logger = logging.getLogger(__name__)

ICONS = ('search', 'send', 'check', 'x')
EXAMPLE = '3 Dark Hole\n2x Raigeki\nMonster Reborn'
LIST_CSS = '''
.oy-deck { display: grid; grid-template-columns: minmax(260px, 380px) minmax(0, 1fr); gap: 24px; width: 100%;
  align-items: start; }
@media (max-width: 900px) { .oy-deck { grid-template-columns: minmax(0, 1fr); } }
.oy-deck-row { border-bottom: 1px solid var(--oy-border-soft); }
.oy-deck-total { font-family: var(--oy-font-display); font-size: 26px; line-height: 1.15; }
'''


def missing_text(missing: int) -> str:
    if missing <= 0:
        return ''
    return 'Falta 1' if missing == 1 else f'Faltan {missing}'


def decklist_page() -> None:
    ui.add_css(LIST_CSS)
    profile = load_profile()
    page_header('Lista de mazo', 'Pega una lista y mira qué hay en la tienda, a qué precio y qué falta.')
    if not profile.shop_mode:
        ui.label('La lista de mazo es parte del modo tienda. Actívalo en Ajustes → Modo tienda.').classes('oy-sub')
        return
    currency = profile.shop.currency
    desk = desk_for(account_root(), currency)
    games = enabled_games(profile)
    state = {'found': None, 'busy': False, 'code': None}

    def money(cents: int) -> str:
        return format_money(cents, currency)

    async def check() -> None:
        if state['busy']:
            return
        wanted = decklist.parse(box.value)
        if not wanted:
            ui.notify('Pega una lista: una carta por línea, con el número de copias delante.', type='warning')
            return
        state['busy'] = True
        try:
            items = await run.io_bound(desk.inventory.items, games, True)
            state['found'] = decklist.match(wanted, items)
            state['code'] = None
        except Exception as error:
            logger.error('Lista de mazo: %s', type(error).__name__)
            ui.notify('No se pudo leer el stock. Inténtalo de nuevo.', type='negative')
            return
        finally:
            state['busy'] = False
        result.refresh()

    async def send() -> None:
        if state['busy'] or not state['found']:
            return
        lines = decklist.available_lines(state['found'])
        state['busy'] = True
        try:
            order = await run.io_bound(desk.orders.add, name_box.value, lines)
        except KioskError as refusal:   # written for people
            ui.notify(str(refusal).replace('Tu lista', 'La lista').replace('Escribe tu nombre', 'Escribe un nombre'),
                      type='warning')
            return
        except Exception as error:
            logger.error('Lista de mazo: no se pudo enviar: %s', type(error).__name__)
            ui.notify('No se pudo enviar la lista al mostrador. Inténtalo de nuevo.', type='negative')
            return
        finally:
            state['busy'] = False
        state['code'] = order.code
        result.refresh()
        ui.notify('Lista enviada al mostrador.', type='positive')

    with ui.element('div').classes('oy-deck q-mt-md'):
        with ui.column().classes('w-full gap-3'):
            box = ui.textarea('Lista', placeholder=EXAMPLE).props('outlined rows=14').classes('w-full')
            ui.label('Una carta por línea: «3 Dark Hole», «3x Dark Hole» o solo el nombre (1 copia). '
                     'Las líneas que empiezan por // o # no cuentan.').classes('text-caption text-grey-5')
            with ui.button(on_click=check).props('no-caps color=secondary').classes('w-full'):
                icon('search')
                ui.label('Comprobar stock').classes('q-ml-xs')

        @ui.refreshable
        def result() -> None:
            found = state['found']
            with ui.column().classes('w-full gap-0'):
                if found is None:
                    ui.label('Aquí verás, carta a carta, lo que hay y lo que falta.').classes('oy-sub')
                    return
                for card in found:
                    with ui.row().classes('oy-deck-row w-full items-center gap-3 q-py-sm no-wrap'):
                        icon('check' if card.missing == 0 else 'x', 16)
                        with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                            ui.label(f'{card.wanted} × {card.name}').classes('text-sm ellipsis')
                            detail = ' · '.join(f'{line.quantity} a {money(line.unit_cents)}'
                                                + (f' ({line.set_code})' if line.set_code else '')
                                                for line in card.lines)
                            ui.label(detail or 'No hay en stock con precio.').classes('text-caption text-grey-5')
                        with ui.column().classes('gap-0 items-end'):
                            ui.label(money(card.cents) if card.lines else '—').classes('oy-mono')
                            if card.missing:
                                ui.label(missing_text(card.missing)).classes('text-caption text-warning')
                asked = sum(card.wanted for card in found)
                short = sum(card.missing for card in found)
                with ui.row().classes('w-full items-end q-mt-md'):
                    with ui.column().classes('gap-0'):
                        ui.label(f'{asked - short} de {asked} cartas disponibles').classes('oy-sub')
                        if short:
                            ui.label(missing_text(short)).classes('text-caption text-warning')
                    ui.space()
                    ui.label(money(decklist.total_cents(found))).classes('oy-deck-total')
                if state['code']:
                    ui.label(f'Enviada al mostrador con el código {state["code"]}. Está en Mostrador → Listas del '
                             'kiosko; caduca en 24 horas y no reserva las cartas.').classes('oy-sub q-mt-md')
                elif asked > short:
                    with ui.row().classes('w-full items-center gap-2 q-mt-md'):
                        nonlocal name_box
                        name_box = ui.input('A nombre de', value=name_box.value if name_box else '').props(
                            'outlined dense maxlength=40').style('flex: 1; min-width: 160px')
                        with ui.button(on_click=send).props('no-caps color=secondary'):
                            icon('send')
                            ui.label('Enviar al mostrador').classes('q-ml-xs')

        name_box = None
        result()
