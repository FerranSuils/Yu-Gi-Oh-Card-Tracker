"""/consigna: collections whose cards belong to a customer, and what the shop owes for those sold."""

from __future__ import annotations

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.account_scope import account_root
from src.core.sales_models import format_money
from src.services.shop.desk import desk_for
from src.ui.icons import icon
from src.ui.shop_common import SHOP_CSS, customer_options, game_name, shop_failure, when
from src.ui.theme import page_header

ICONS = ('plus', 'x', 'cash-payment', 'wallet', 'percent', 'check')


def consignment_page() -> None:
    ui.add_css(SHOP_CSS)
    profile = load_profile()
    page_header('Consigna', 'Vende cartas de tus clientes y quédate una comisión de cada venta.')
    if not profile.shop_mode:
        ui.label('La consigna es parte del modo tienda. Actívalo en Ajustes → Modo tienda.').classes('oy-sub')
        return

    currency = profile.shop.currency
    games = enabled_games(profile)
    desk = desk_for(account_root(), currency)
    state = {'book': [], 'customers': [], 'balances': {}, 'collections': {}, 'loaded': False, 'busy': False}
    holder = ui.element('div')

    def money(cents: int) -> str:
        return format_money(cents, currency)

    def read():
        return (desk.book.all(), desk.customers.all(), desk.customers.balances(),
                {game: desk.inventory.collections(game) for game in games})

    async def load() -> None:
        try:
            (state['book'], state['customers'], state['balances'],
             state['collections']) = await run.io_bound(read)
        except Exception as error:
            with holder:
                ui.notify(shop_failure(error, 'No se pudo leer la consigna. Recarga la página.'), type='negative')
            return
        state['loaded'] = True
        owner.set_options(customer_options(state['customers'], state['balances'], currency, kind=None))
        set_game()
        pending.refresh()
        listing.refresh()

    async def attempt(action, *args, done=None, fallback: str = 'No se pudo guardar. Inténtalo de nuevo.'):
        if state['busy']:
            return False
        state['busy'] = True
        try:
            result = await run.io_bound(action, *args)
        except Exception as error:
            with holder:
                ui.notify(shop_failure(error, fallback), type='negative', multi_line=True)
            return False
        finally:
            state['busy'] = False
        await load()
        if done:
            with holder:
                ui.notify(done(result) if callable(done) else done, type='positive')
        return True

    def name_of(customer_id: str) -> str:
        return next((c.name for c in state['customers'] if c.id == customer_id), 'Cliente borrado')

    # --- what the shop owes ------------------------------------------------------------------

    ui.label('Por liquidar').classes('text-subtitle1 q-mt-md')

    @ui.refreshable
    def pending() -> None:
        if not state['loaded']:
            ui.label('Cargando…').classes('oy-sub')
            return
        owed = [(c, state['balances'].get(c.id, {}).get('consignment', 0)) for c in state['customers']]
        debts = [(c, -cents) for c, cents in owed if cents < 0]
        owed = [(c, cents) for c, cents in owed if cents > 0]
        for customer, cents in sorted(debts, key=lambda pair: pair[0].name.casefold()):
            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm'):
                with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                    ui.label(customer.name).classes('text-sm ellipsis w-full')
                    ui.label('Te debe dinero: se devolvió una venta que ya le habías liquidado.').classes(
                        'oy-sub text-xs')
                ui.label(f'Te debe {money(cents)}').classes('oy-mono text-negative')
                with ui.button(on_click=lambda c=customer, n=cents: ask_write_off(c, n)).props(
                        'no-caps outline color=primary'):
                    icon('check')
                    ui.label('Regularizar').classes('q-ml-xs')
        if not owed:
            if not debts:
                ui.label('No debes nada a nadie por cartas en consigna.').classes('oy-sub')
            return
        for customer, cents in sorted(owed, key=lambda pair: pair[0].name.casefold()):
            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm'):
                ui.label(customer.name).classes('text-sm ellipsis').style('min-width: 0; flex: 1')
                ui.label(money(cents)).classes('oy-mono')
                with ui.button(on_click=lambda c=customer, n=cents: ask_pay(c, n, 'cash')).props(
                        'no-caps outline color=primary'):
                    icon('cash-payment')
                    ui.label('Pagar en efectivo').classes('q-ml-xs')
                with ui.button(on_click=lambda c=customer, n=cents: ask_pay(c, n, 'credit')).props(
                        'no-caps outline color=primary'):
                    icon('wallet')
                    ui.label('Pasar a saldo').classes('q-ml-xs')

    pending()

    def ask_pay(customer, cents: int, to: str) -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('max-width: 440px'):
            ui.label(f'Liquidar a {customer.name}').classes('text-h6')
            ui.label(f'Le entregas {money(cents)} en efectivo y la aplicación lo anota como pagado.' if to == 'cash'
                     else f'Sus {money(cents)} pasan a saldo de tienda, para gastar en el mostrador.').classes(
                'oy-sub')

            async def confirm() -> None:
                dialog.close()
                await attempt(desk.book.pay_out, customer.id, to, cents,
                              done=lambda amount: f'Liquidados {money(amount)} a {customer.name}.',
                              fallback='No se pudo liquidar. Inténtalo de nuevo.')

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Liquidar', on_click=confirm).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    def ask_write_off(customer, cents: int) -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 340px; max-width: 440px'):
            ui.label(f'Regularizar la deuda de {customer.name}').classes('text-h6')
            ui.label(f'{customer.name} te debe {money(cents)}. Cuando lo hayáis resuelto, anota cómo: la deuda '
                     'queda a cero y el motivo se guarda en sus movimientos.').classes('oy-sub')
            reason = ui.input('Cómo se ha resuelto', placeholder='Devolvió el efectivo, se lo perdono…').props(
                'outlined dense maxlength=150').classes('w-full q-mt-sm')

            async def confirm() -> None:
                if not (reason.value or '').strip():
                    ui.notify('Indica cómo se ha resuelto la deuda.', type='warning')
                    return
                dialog.close()
                await attempt(desk.book.write_off, customer.id, reason.value,
                              done=lambda amount: f'Deuda de {money(amount)} de {customer.name} regularizada.',
                              fallback='No se pudo regularizar. Inténtalo de nuevo.')

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Regularizar', on_click=confirm).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    # --- opening -----------------------------------------------------------------------------

    ui.label('Abrir una consigna').classes('text-subtitle1 q-mt-lg')
    ui.label('Elige una colección que contenga solo las cartas de ese cliente. Cada venta de esa colección le '
             'apunta el importe menos tu comisión.').classes('oy-sub')
    with ui.row().classes('w-full items-center gap-2 q-mt-sm'):
        owner = ui.select({}, label='Cliente', with_input=True).props('outlined dense').style(
            'min-width: 200px; flex: 1')
        game = ui.select({g: game_name(g) for g in games}, value=games[0], label='Juego').props(
            'outlined dense').classes('w-40')
        collection = ui.select([], label='Colección').props('outlined dense').style('min-width: 180px; flex: 1')
        commission = ui.number('Comisión', value=20, min=0, max=100, step=1, format='%g').props(
            'outlined dense suffix=%').classes('w-28')
        with ui.button(on_click=lambda: open_one()).props('no-caps color=secondary'):
            icon('plus')
            ui.label('Abrir').classes('q-ml-xs')

    def set_game() -> None:
        taken = {c.collection for c in state['book'] if c.closed_at is None and c.game == game.value}
        names = [name for name in state['collections'].get(game.value, []) if name not in taken]
        collection.set_options(names, value=collection.value if collection.value in names else None)

    game.on_value_change(set_game)

    async def open_one() -> None:
        if not owner.value or not collection.value:
            ui.notify('Elige el cliente y la colección.', type='warning')
            return
        if commission.value is None:
            ui.notify('Escribe la comisión, entre 0 y 100 %.', type='warning')
            return
        if await attempt(desk.book.open, owner.value, game.value, collection.value, float(commission.value),
                         done='Consigna abierta.'):
            owner.set_value(None)

    # --- the book ----------------------------------------------------------------------------

    ui.label('Consignas').classes('text-subtitle1 q-mt-lg')

    @ui.refreshable
    def listing() -> None:
        if not state['loaded']:
            ui.label('Cargando…').classes('oy-sub')
            return
        if not state['book']:
            ui.label('Todavía no hay ninguna colección en consigna.').classes('oy-sub')
            return
        for item in sorted(state['book'], key=lambda c: (c.closed_at is not None, c.opened_at)):
            closed = item.closed_at is not None
            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm no-wrap'):
                with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                    ui.label(f'{name_of(item.customer_id)} · {item.collection}').classes('text-sm ellipsis w-full')
                    ui.label(f'{game_name(item.game)} · abierta el {when(item.opened_at)}'
                             + (f' · cerrada el {when(item.closed_at)}' if closed else '')).classes(
                        'oy-sub text-xs ellipsis w-full')
                ui.label(f'{item.commission_percent:g} %').classes('oy-mono' + (' oy-sub' if closed else '')).tooltip(
                    'Tu comisión')
                if not closed:
                    with ui.button(on_click=lambda c=item: ask_close(c)).props(
                            'flat dense round color=primary').tooltip('Cerrar la consigna'):
                        icon('x')

    listing()

    def ask_close(item) -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('max-width: 440px'):
            ui.label('¿Cerrar esta consigna?').classes('text-h6')
            ui.label(f'Las cartas de {item.collection} se quedan donde están y dejan de apuntar ventas a '
                     f'{name_of(item.customer_id)}. Lo pendiente de liquidar se mantiene.').classes('oy-sub')

            async def confirm() -> None:
                dialog.close()
                await attempt(desk.book.close, item.id, done='Consigna cerrada.')

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Cerrar la consigna', on_click=confirm).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    ui.timer(0.1, load, once=True)
