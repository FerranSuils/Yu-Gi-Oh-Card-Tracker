"""/compras: buy cards from customers, in cash or for store credit, and put them straight into stock."""

from __future__ import annotations

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.account_scope import account_root
from src.core.constants import CARD_CONDITIONS
from src.core.sales_models import format_money, to_cents
from src.core.shop_models import PAYMENT_LABELS
from src.services.catalog import get_provider
from src.services.prices import get_source
from src.services.shop.buylist import Offer, line_for, offer_cents, offers
from src.services.shop.desk import desk_for
from src.ui.icons import icon
from src.ui.shop_common import SHOP_CSS, customer_options, game_name, printing_text, shop_failure, when
from src.ui.theme import page_header

ICONS = ('search', 'plus', 'trash', 'hand-coin', 'ban', 'history')
CARDS = 12
PRINTINGS = 8
HISTORY = 30


def price_source(game: str, market: str):
    """The downloaded prices of a game, or None when that market has none for it."""
    try:
        return get_source(game, market)
    except KeyError:
        return None


def find_offers(game: str, market: str, rules, text: str, condition: str) -> list:
    """Cards matching the text with what the shop pays for each printing. Disk only, no network."""
    provider = get_provider(game)
    source = price_source(game, market)
    rows = []
    for card in provider.search(text, limit=CARDS):
        priced = offers(card, source, rules, condition)
        if not priced:  # no market price on disk: the shop may still buy it at a price typed by hand
            priced = [Offer(printing, '' if game == 'yugioh' else (printing.finishes or ['nonfoil'])[0], 0, 0, 0)
                      for printing in card.printings[:PRINTINGS]]
        rows.append((card, priced))
    return rows


def basket_entry(card, offer: Offer, payment: str, condition: str, collection: str, rules) -> dict:
    """A purchase line priced for the condition it records, whatever condition the search was priced for."""
    cents = offer_cents(offer.market_cents, rules, payment, condition) if offer.market_cents else 0
    return {'card': card, 'offer': offer, 'condition': condition, 'collection': collection, 'quantity': 1,
            'cents': cents}


def plain(cents: int) -> str:
    return f'{cents / 100:.2f}'.replace('.', ',') if cents else ''


def buylist_page() -> None:
    ui.add_css(SHOP_CSS)
    profile = load_profile()
    page_header('Compras', 'Compra cartas a tus clientes: entran en tu stock al momento.')
    if not profile.shop_mode:
        ui.label('Las compras son parte del modo tienda. Actívalo en Ajustes → Modo tienda.').classes('oy-sub')
        return

    currency = profile.shop.currency
    rules = profile.buylist
    market = profile.price_market
    games = enabled_games(profile)
    desk = desk_for(account_root(), currency)
    state = {'rows': None, 'basket': [], 'collections': {}, 'customers': [], 'balances': {}, 'purchases': [],
             'busy': False, 'loaded': False}
    holder = ui.element('div')

    def money(cents: int) -> str:
        return format_money(cents, currency)

    def read():
        book = {(c.game, c.collection) for c in desk.book.active()}
        collections = {game: [name for name in desk.inventory.collections(game) if (game, name) not in book]
                       for game in games}
        return collections, desk.customers.all(), desk.customers.balances(), desk.purchases.all()

    async def load() -> None:
        try:
            (state['collections'], state['customers'], state['balances'],
             state['purchases']) = await run.io_bound(read)
        except Exception as error:
            with holder:
                ui.notify(shop_failure(error, 'No se pudieron leer las compras. Recarga la página.'), type='negative')
            return
        state['loaded'] = True
        set_game()
        customer.set_options(customer_options(state['customers'], state['balances'], currency))
        history.refresh()

    # --- search ------------------------------------------------------------------------------

    with ui.element('div').classes('oy-pos q-mt-md'):
        with ui.column().classes('w-full gap-2'):
            with ui.row().classes('w-full items-center gap-2'):
                game = ui.select({g: game_name(g) for g in games}, value=games[0], label='Juego').props(
                    'outlined dense').classes('w-40')
                target = ui.select([], label='Entra en la colección').props('outlined dense').style(
                    'min-width: 180px; flex: 1')
                condition = ui.select(CARD_CONDITIONS, value='Near Mint', label='Estado').props(
                    'outlined dense').classes('w-40')
            with ui.row().classes('w-full items-center gap-2 no-wrap'):
                query = ui.input(placeholder='Nombre de la carta que te traen').props(
                    'outlined dense clearable').style('min-width: 0; flex: 1')
                with ui.button(on_click=lambda: look()).props('no-caps outline color=primary'):
                    icon('search')
                    ui.label('Buscar').classes('q-ml-xs')

            @ui.refreshable
            def results() -> None:
                rows = state['rows']
                if rows is None:
                    ui.label(f'Pagas el {rules.cash_percent:g} % del precio de mercado en efectivo y el '
                             f'{rules.credit_percent:g} % en saldo. Cámbialo en Ajustes → Compras.').classes('oy-sub')
                    return
                if not rows:
                    ui.label('Ninguna carta con ese nombre en el catálogo descargado.').classes('oy-sub')
                    return
                for card, priced in rows:
                    ui.label(card.name).classes('text-sm q-mt-sm')
                    for offer in priced:
                        with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-xs no-wrap'):
                            ui.label(printing_text(offer.printing, offer.finish)).classes(
                                'oy-sub text-xs ellipsis').style('min-width: 0; flex: 1')
                            if offer.market_cents:
                                ui.label(money(offer.market_cents)).classes('oy-mono oy-sub text-xs').tooltip(
                                    'Precio de mercado')
                                ui.label(money(offer.cash_cents) if offer.cash_cents else '—').classes(
                                    'oy-mono').tooltip('Oferta en efectivo')
                                ui.label(money(offer.credit_cents) if offer.credit_cents else '—').classes(
                                    'oy-mono').tooltip('Oferta en saldo de tienda')
                            else:
                                ui.label('sin precio').classes('oy-sub text-xs')
                            with ui.button(on_click=lambda card=card, offer=offer: add(card, offer)).props(
                                    'flat dense round color=primary').tooltip('Añadir a la compra'):
                                icon('plus')

            results()

        # --- the purchase --------------------------------------------------------------------

        with ui.column().classes('oy-pos-ticket w-full gap-2 q-pa-md'):
            with ui.row().classes('w-full items-center gap-2'):
                icon('hand-coin', 18)
                ui.label('Compra').classes('text-subtitle1')

            @ui.refreshable
            def basket_view() -> None:
                if not state['basket']:
                    ui.label('Añade las cartas desde la búsqueda.').classes('oy-sub')
                    return
                for index, item in enumerate(state['basket']):
                    with ui.column().classes('oy-pos-row w-full gap-1 q-py-sm'):
                        with ui.row().classes('w-full items-center gap-2 no-wrap'):
                            with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                                ui.label(item['card'].name).classes('text-sm ellipsis w-full')
                                ui.label(' · '.join((printing_text(item['offer'].printing, item['offer'].finish),
                                                     item['condition'], item['collection']))).classes(
                                    'oy-sub text-xs ellipsis w-full')
                            with ui.button(on_click=lambda index=index: drop(index)).props(
                                    'flat dense round color=primary').tooltip('Quitar'):
                                icon('trash')
                        with ui.row().classes('w-full items-center gap-2 no-wrap'):
                            units = ui.number(value=item['quantity'], min=1, max=99, step=1, format='%d').props(
                                'outlined dense').classes('w-20')
                            ui.label('×').classes('oy-sub')
                            price = ui.input(value=plain(item['cents']), placeholder='0,00').props(
                                f'outlined dense suffix={currency}').classes('w-28')
                            ui.space()
                            ui.label(money(item['cents'] * item['quantity'])).classes('oy-mono')
                            units.on_value_change(lambda event, index=index: set_units(index, event.value))
                            price.on('change', lambda _, index=index, price=price: set_price(index, price))

            basket_view()

            payment = ui.toggle(PAYMENT_LABELS, value='cash').props('no-caps unelevated toggle-color=secondary')
            customer = ui.select({}, label='Cliente (obligatorio si pagas en saldo)', with_input=True,
                                 clearable=True).props('outlined dense').classes('w-full')

            @ui.refreshable
            def total() -> None:
                with ui.row().classes('w-full items-baseline'):
                    ui.label('A pagar').classes('text-subtitle1')
                    ui.space()
                    ui.label(money(sum(i['cents'] * i['quantity'] for i in state['basket']))).classes('oy-pos-total')

            total()
            with ui.button(on_click=lambda: buy()).props('no-caps color=secondary').classes('w-full'):
                icon('hand-coin')
                ui.label('Registrar la compra').classes('q-ml-xs')

    # --- history -----------------------------------------------------------------------------

    ui.label('Últimas compras').classes('text-subtitle1 q-mt-lg')

    @ui.refreshable
    def history() -> None:
        if not state['loaded']:
            ui.label('Cargando…').classes('oy-sub')
            return
        if not state['purchases']:
            ui.label('Todavía no has comprado nada.').classes('oy-sub')
            return
        for purchase in sorted(state['purchases'], key=lambda p: p.created_at, reverse=True)[:HISTORY]:
            cancelled = purchase.status != 'done'
            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm no-wrap'):
                ui.label(purchase.label).classes('oy-mono')
                with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                    ui.label(purchase.customer_name or 'Sin cliente').classes('text-sm ellipsis w-full')
                    ui.label(f'{when(purchase.created_at)} · {purchase.units} cartas · '
                             f'{PAYMENT_LABELS.get(purchase.payment, purchase.payment)}'
                             + (' · anulada' if cancelled else '')).classes('oy-sub text-xs ellipsis w-full')
                ui.label(format_money(purchase.total_cents, purchase.currency)).classes(
                    'oy-mono' + (' oy-sub' if cancelled else ''))
                if not cancelled:
                    with ui.button(on_click=lambda p=purchase: ask_cancel(p)).props(
                            'flat dense round color=primary').tooltip('Anular la compra'):
                        icon('ban')

    history()

    # --- actions -----------------------------------------------------------------------------

    def set_game() -> None:
        names = state['collections'].get(game.value, [])
        target.set_options(names, value=target.value if target.value in names else (names[0] if names else None))

    def paid(offer: Offer) -> int:
        return offer.cash_cents if payment.value == 'cash' else offer.credit_cents

    async def look() -> None:
        text = (query.value or '').strip()
        if len(text) < 2:
            ui.notify('Escribe al menos dos letras del nombre.', type='warning')
            return
        try:
            if not await run.io_bound(get_provider(game.value).is_available):
                ui.notify(f'El catálogo de {game_name(game.value)} no está descargado. Descárgalo en Ajustes → '
                          'Juegos.', type='warning', multi_line=True)
                return
            state['rows'] = await run.io_bound(find_offers, game.value, market, rules, text, condition.value)
        except Exception as error:
            ui.notify(shop_failure(error, 'No se pudo buscar en el catálogo.'), type='negative')
            return
        results.refresh()

    def add(card, offer: Offer) -> None:
        if not target.value:
            ui.notify(f'No tienes ninguna colección de {game_name(card.game)} donde meter la carta. Crea una antes.',
                      type='warning', multi_line=True)
            return
        if len(state['basket']) >= 200:
            ui.notify('Una compra admite 200 líneas como mucho; repártela en varias.', type='warning')
            return
        entry = basket_entry(card, offer, payment.value, condition.value, target.value, rules)
        if offer.market_cents and not entry['cents']:
            ui.notify('Esa carta queda por debajo de tu oferta mínima. Puedes ponerle precio a mano.', type='info')
        state['basket'].append(entry)
        basket_view.refresh()
        total.refresh()

    def drop(index: int) -> None:
        if index < len(state['basket']):
            del state['basket'][index]
        basket_view.refresh()
        total.refresh()

    def set_units(index: int, value) -> None:
        if value is None or index >= len(state['basket']):
            return
        state['basket'][index]['quantity'] = max(1, min(99, int(value)))
        basket_view.refresh()
        total.refresh()

    def set_price(index: int, price) -> None:
        if index >= len(state['basket']):
            return
        try:
            cents = to_cents(price.value or '0')
            if cents < 0:
                raise ValueError
        except ValueError:
            price.props('error')
            ui.notify('Ese precio no es un número. Usa, por ejemplo, 2,50.', type='warning')
            return
        state['basket'][index]['cents'] = cents
        basket_view.refresh()
        total.refresh()

    def reprice() -> None:
        """The offer depends on how the customer is paid: switching it puts every line back on its offer."""
        for item in state['basket']:
            offer = item['offer']
            if offer.market_cents:
                item['cents'] = offer_cents(offer.market_cents, rules, payment.value, item['condition'])
        basket_view.refresh()
        total.refresh()

    async def buy() -> None:
        if state['busy']:
            return
        if not state['basket']:
            ui.notify('La compra está vacía.', type='warning')
            return
        if any(item['cents'] <= 0 for item in state['basket']):
            ui.notify('Hay cartas sin precio de compra. Escríbelo o quítalas.', type='warning')
            return
        if payment.value == 'credit' and not customer.value:
            ui.notify('Elige el cliente que recibe el saldo.', type='warning')
            return
        state['busy'] = True
        try:
            lines = [line_for(item['card'], item['offer'].printing, item['quantity'], item['cents'],
                              item['offer'].market_cents or None, item['collection'], item['offer'].finish,
                              item['condition']) for item in state['basket']]
            purchase = await run.io_bound(desk.buying.buy, lines, payment.value, currency, customer.value or None)
        except Exception as error:
            ui.notify(shop_failure(error, 'No se pudo guardar la compra. Inténtalo de nuevo.'), type='negative',
                      multi_line=True)
            return
        finally:
            state['busy'] = False
        state['basket'] = []
        customer.set_value(None)
        basket_view.refresh()
        total.refresh()
        await load()
        with holder:
            ui.notify(f'Compra {purchase.label} registrada: {money(purchase.total_cents)}, '
                      f'{purchase.units} cartas en stock.', type='positive')

    def ask_cancel(purchase) -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('max-width: 440px'):
            ui.label(f'¿Anular la compra {purchase.label}?').classes('text-h6')
            ui.label('Las cartas salen de tu stock y, si pagaste en saldo, se le retira al cliente. '
                     'Si ya has vendido alguna de esas cartas, no se puede anular.').classes('oy-sub')

            async def confirm() -> None:
                dialog.close()
                if state['busy']:
                    return
                state['busy'] = True
                try:
                    await run.io_bound(desk.buying.cancel, purchase.id)
                except Exception as error:
                    with holder:
                        ui.notify(shop_failure(error, 'No se pudo anular la compra.'), type='negative',
                                  multi_line=True)
                    return
                finally:
                    state['busy'] = False
                await load()
                with holder:
                    ui.notify(f'Compra {purchase.label} anulada.', type='positive')

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Anular', on_click=confirm).props('no-caps color=negative')
        dialog.on('hide', dialog.delete)
        dialog.open()

    game.on_value_change(lambda: (set_game(), state.update(rows=None), results.refresh()))
    payment.on_value_change(reprice)

    async def recondition() -> None:
        """The offers on screen are priced for one condition: changing it prices them again."""
        if state['rows'] is not None:
            await look()

    condition.on_value_change(recondition)
    query.on('keydown.enter', look)
    ui.timer(0.1, load, once=True)
