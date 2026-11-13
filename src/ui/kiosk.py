"""/kiosko/<token>: the shop's public screen. Browse the priced stock, send a list to the counter, see offers.

Nobody is signed in here: the page only ever shows the shop's name, its priced stock and what it pays
for cards. Customers, balances, sales and where the cards are kept never reach it.
"""

from __future__ import annotations

import logging

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.sales_models import format_money
from src.services.catalog import get_provider
from src.services.prices import get_source
from src.services.sales.inventory import search
from src.services.shop.buylist import offers
from src.services.shop.desk import desk_for
from src.services.shop.kiosk import (
    MAX_COPIES,
    MAX_LINES,
    MAX_NAME,
    KioskClosed,
    KioskError,
    Throttle,
    Visit,
    account_for,
    address_of,
    ensure_open,
    shelf,
)
from src.ui.icons import icon
from src.ui.shop_common import SHOP_CSS, game_name, printing_text
from src.ui.theme import apply_theme

logger = logging.getLogger(__name__)

ICONS = ('search', 'plus', 'minus', 'trash', 'send', 'shopping-list', 'hand-coin', 'check', 'store')
RESULTS = 40
CARDS = 10
CLOSED = 'Este kiosko está cerrado. Pregunta en el mostrador.'
THROTTLE = Throttle()  # lists per shop and address; shared by every kiosk page of this process


def public_text(line) -> str:
    """A pile as a visitor sees it: never where it is kept."""
    return ' · '.join(part for part in (line.set_code, line.rarity, line.finish, line.condition, line.language,
                                        '1.ª ed.' if line.first_edition else '') if part)


def kiosk_failure(error: Exception, fallback: str) -> str:
    if isinstance(error, KioskError) and str(error):
        return str(error)
    logger.error('Kiosko: %s', type(error).__name__)
    return fallback


def public_offers(game: str, market: str, rules, text: str) -> list:
    """What the shop pays for the cards matching a name. Prices already on disk only."""
    try:
        source = get_source(game, market)
    except KeyError:
        return []
    provider = get_provider(game)
    if not provider.is_available():
        return []
    rows = []
    for card in provider.search(text, limit=CARDS):
        priced = offers(card, source, rules)
        if priced:
            rows.append((card, priced))
    return rows


def kiosk_page(token: str) -> None:
    apply_theme()
    ui.add_css(SHOP_CSS)
    state = {'desk': None, 'profile': None, 'shelf': [], 'cart': [], 'offers': None, 'code': None, 'busy': False,
             'root': None}
    visit = Visit()
    request = ui.context.client.request
    address = address_of(request.headers, request.client.host if request.client else '')
    with ui.column().classes('w-full items-center q-pa-md'):
        page = ui.column().classes('w-full gap-3').style('max-width: 1100px')

    def closed() -> None:
        page.clear()
        with page, ui.column().classes('w-full items-center gap-3').style('margin-top: 12vh'):
            icon('store', 56)
            ui.label('Kiosko cerrado').classes('oy-h1')
            ui.label(CLOSED).classes('oy-sub')

    def read():
        root = account_for(token)
        if root is None:
            return None
        profile = load_profile(root)
        if not profile.shop_mode:
            return None
        desk = desk_for(root, profile.shop.currency)
        return root, desk, profile, shelf(desk.inventory.items(enabled_games(profile)))

    async def load() -> None:
        try:
            found = await run.io_bound(read)
        except Exception as error:
            logger.error('Kiosko: no se pudo abrir: %s', type(error).__name__)
            found = None
        if found is None:
            closed()
            return
        state['root'], state['desk'], state['profile'], state['shelf'] = found
        build()

    async def reload_shelf() -> None:
        desk, profile = state['desk'], state['profile']

        def fresh():
            ensure_open(token, state['root'])
            return shelf(desk.inventory.items(enabled_games(profile)))

        try:
            state['shelf'] = await run.io_bound(fresh)
        except KioskClosed:
            closed()
            return False
        except Exception as error:
            logger.error('Kiosko: no se pudo leer el stock: %s', type(error).__name__)
        return True

    def build() -> None:
        profile = state['profile']
        currency = profile.shop.currency
        games = enabled_games(profile)

        def money(cents: int) -> str:
            return format_money(cents, currency)

        page.clear()
        with page:
            with ui.row().classes('w-full items-center gap-2'):
                icon('store', 24)
                ui.label(profile.shop.name or 'Kiosko').classes('oy-h1')
            with ui.tabs().props('no-caps align=left').classes('w-full') as tabs:
                buy_tab = ui.tab('Comprar')
                sell_tab = ui.tab('Vender mis cartas')
            with ui.tab_panels(tabs, value=buy_tab).classes('w-full').style('background: transparent'):

                # --- buying ------------------------------------------------------------------

                with ui.tab_panel(buy_tab).classes('q-pa-none'), ui.element('div').classes('oy-pos q-mt-md'):
                    with ui.column().classes('w-full gap-2'):
                        query = ui.input(placeholder='Nombre, set o número de la carta').props(
                            'outlined dense clearable debounce=300 maxlength=80').classes('w-full')

                        @ui.refreshable
                        def results() -> None:
                            if not state['shelf']:
                                ui.label('Ahora mismo no hay cartas a la venta.').classes('oy-sub')
                                return
                            found = search(state['shelf'], query.value or '', RESULTS)
                            if not found:
                                ui.label('Nada a la venta con ese texto.').classes('oy-sub')
                                return
                            for item in found:
                                with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm no-wrap'):
                                    with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                                        ui.label(item.name).classes('text-sm ellipsis w-full')
                                        ui.label(public_text(item)).classes('oy-sub text-xs ellipsis w-full')
                                    ui.label(f'×{item.quantity}').classes('oy-mono oy-sub')
                                    ui.label(money(item.unit_cents)).classes('oy-mono')
                                    with ui.button(on_click=lambda item=item: add(item)).props(
                                            'flat dense round color=primary').tooltip('Añadir a mi lista'):
                                        icon('plus')
                            if len(found) == RESULTS:
                                ui.label(f'Se muestran {RESULTS} cartas. Escribe más para afinar.').classes(
                                    'oy-sub text-xs')

                        results()
                        query.on_value_change(results.refresh)

                    with ui.column().classes('oy-pos-ticket w-full gap-2 q-pa-md'):
                        with ui.row().classes('w-full items-center gap-2'):
                            icon('shopping-list', 18)
                            ui.label('Mi lista').classes('text-subtitle1')

                        @ui.refreshable
                        def cart_view() -> None:
                            if state['code']:
                                with ui.column().classes('w-full items-center gap-2 q-py-md'):
                                    icon('check', 32)
                                    ui.label('Lista enviada. Di este código en el mostrador:').classes(
                                        'oy-sub text-center')
                                    ui.label(state['code']).classes('oy-kiosk-code')
                                    ui.label('Las cartas no quedan reservadas: pasa pronto a por ellas. '
                                             'Pagas en el mostrador.').classes('oy-sub text-xs text-center')
                                    ui.button('Hacer otra lista', on_click=again).props(
                                        'flat no-caps color=primary')
                                return
                            if not state['cart']:
                                ui.label('Añade cartas desde la búsqueda y envía la lista al mostrador. '
                                         'Allí te las preparan y pagas.').classes('oy-sub')
                                return
                            for index, entry in enumerate(state['cart']):
                                line = entry['line']
                                with ui.row().classes('oy-pos-row w-full items-center gap-2 q-py-sm no-wrap'):
                                    with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                                        ui.label(line.name).classes('text-sm ellipsis w-full')
                                        ui.label(public_text(line)).classes('oy-sub text-xs ellipsis w-full')
                                    with ui.button(on_click=lambda index=index: change(index, -1)).props(
                                            'flat dense round color=primary').tooltip('Una menos'):
                                        icon('minus' if entry['quantity'] > 1 else 'trash')
                                    ui.label(str(entry['quantity'])).classes('oy-mono')
                                    with ui.button(on_click=lambda index=index: change(index, 1)).props(
                                            'flat dense round color=primary').tooltip('Una más'):
                                        icon('plus')
                                    ui.label(money(line.unit_cents * entry['quantity'])).classes('oy-mono')
                            with ui.row().classes('w-full items-baseline q-mt-sm'):
                                ui.label('Total').classes('text-subtitle1')
                                ui.space()
                                ui.label(money(sum(e['line'].unit_cents * e['quantity'] for e in state['cart']))
                                         ).classes('oy-pos-total')
                            name = ui.input('Tu nombre').props(f'outlined dense maxlength={MAX_NAME}').classes(
                                'w-full')
                            with ui.button(on_click=lambda: send(name.value)).props(
                                    'no-caps color=secondary').classes('w-full'):
                                icon('send')
                                ui.label('Enviar al mostrador').classes('q-ml-xs')

                        cart_view()

                # --- selling -----------------------------------------------------------------

                with ui.tab_panel(sell_tab).classes('q-pa-none'), ui.column().classes('w-full gap-2 q-mt-md'):
                    with ui.row().classes('items-center gap-2'):
                        icon('hand-coin', 18)
                        ui.label('Lo que pagamos por tus cartas').classes('text-subtitle1')
                    ui.label('Precios orientativos para cartas en buen estado. La oferta final la confirma el '
                             'mostrador al ver las cartas.').classes('oy-sub')
                    with ui.row().classes('w-full items-center gap-2 no-wrap'):
                        game = ui.select({g: game_name(g) for g in games}, value=games[0], label='Juego').props(
                            'outlined dense').classes('w-40')
                        wanted = ui.input(placeholder='Nombre de tu carta').props(
                            'outlined dense clearable maxlength=80').style('min-width: 0; flex: 1')
                        with ui.button(on_click=lambda: look()).props('no-caps outline color=primary'):
                            icon('search')
                            ui.label('Buscar').classes('q-ml-xs')

                    @ui.refreshable
                    def offers_view() -> None:
                        rows = state['offers']
                        if rows is None:
                            return
                        if not rows:
                            ui.label('No tenemos oferta para esa carta ahora mismo. Pregunta en el mostrador.'
                                     ).classes('oy-sub')
                            return
                        for card, priced in rows:
                            ui.label(card.name).classes('text-sm q-mt-sm')
                            for offer in priced:
                                with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-xs no-wrap'):
                                    ui.label(printing_text(offer.printing, offer.finish)).classes(
                                        'oy-sub text-xs ellipsis').style('min-width: 0; flex: 1')
                                    if offer.cash_cents:
                                        ui.label(f'{money(offer.cash_cents)} en efectivo').classes('oy-mono')
                                    if offer.credit_cents:
                                        ui.label(f'{money(offer.credit_cents)} en saldo').classes('oy-mono')

                    offers_view()

        # --- actions -------------------------------------------------------------------------

        def stock_of(line) -> int:
            return next((item.quantity for item in state['shelf'] if item == line or (
                item.model_copy(update={'quantity': 0}) == line.model_copy(update={'quantity': 0}))), 0)

        def add(item) -> None:
            if state['code']:
                state['code'] = None
            same = item.model_copy(update={'quantity': 0})
            entry = next((e for e in state['cart'] if e['line'].model_copy(update={'quantity': 0}) == same), None)
            if entry is None:
                if len(state['cart']) >= MAX_LINES:
                    ui.notify(f'Una lista admite {MAX_LINES} cartas distintas como mucho.', type='warning')
                    return
                state['cart'].append({'line': item, 'quantity': 1})
            elif entry['quantity'] >= min(stock_of(item), MAX_COPIES):
                ui.notify(f'Solo quedan {stock_of(item)} de {item.name}.', type='warning')
                return
            else:
                entry['quantity'] += 1
            cart_view.refresh()

        def change(index: int, step: int) -> None:
            if index >= len(state['cart']):
                return
            entry = state['cart'][index]
            if step > 0 and entry['quantity'] >= min(stock_of(entry['line']), MAX_COPIES):
                ui.notify(f'Solo quedan {stock_of(entry["line"])} de {entry["line"].name}.', type='warning')
                return
            entry['quantity'] += step
            if entry['quantity'] <= 0:
                del state['cart'][index]
            cart_view.refresh()

        async def send(name) -> None:
            if state['busy']:
                return
            state['busy'] = True
            try:
                lines = [e['line'].model_copy(update={'quantity': e['quantity']}) for e in state['cart']]

                def place():
                    ensure_open(token, state['root'])
                    visit.check()
                    THROTTLE.spend(f"{state['root']}|{address}")
                    return state['desk'].orders.add(name, lines)

                order = await run.io_bound(place)
                visit.sent()
            except KioskClosed:
                closed()
                return
            except Exception as error:
                ui.notify(kiosk_failure(error, 'No se pudo enviar la lista. Pídelo en el mostrador.'),
                          type='negative', multi_line=True)
                return
            finally:
                state['busy'] = False
            state['cart'] = []
            state['code'] = order.code
            cart_view.refresh()

        async def again() -> None:
            state['code'] = None
            if not await reload_shelf():
                return
            results.refresh()
            cart_view.refresh()

        async def look() -> None:
            text = (wanted.value or '').strip()
            if len(text) < 3:
                ui.notify('Escribe al menos tres letras del nombre.', type='warning')
                return
            if state['busy']:
                return
            state['busy'] = True
            try:

                def ask():
                    ensure_open(token, state['root'])
                    return public_offers(game.value, profile.price_market, profile.buylist, text)

                state['offers'] = await run.io_bound(ask)
            except KioskClosed:
                closed()
                return
            except Exception as error:
                logger.error('Kiosko: ofertas sin leer: %s', type(error).__name__)
                state['offers'] = []
            finally:
                state['busy'] = False
            offers_view.refresh()

        wanted.on('keydown.enter', look)

    with page:
        ui.label('Abriendo el kiosko…').classes('oy-sub')
    ui.timer(0.1, load, once=True)
