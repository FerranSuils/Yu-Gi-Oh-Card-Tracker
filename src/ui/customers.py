"""/clientes: the people the shop deals with, their store credit and what they are owed."""

from __future__ import annotations

from nicegui import run, ui

from src.core.account_profile import load_profile
from src.core.account_scope import account_root
from src.core.sales_models import format_money
from src.core.shop_models import LEDGER_LABELS
from src.services.shop.desk import desk_for
from src.ui.icons import icon
from src.ui.shop_common import SHOP_CSS, amount_cents, shop_failure, when
from src.ui.theme import page_header

ICONS = ('user-plus', 'edit', 'trash', 'history', 'wallet', 'coin')
SHOWN = 100


def amount_text(kind: str, cents: int, currency: str) -> str:
    """One movement as the history shows it: money, or points for the points book."""
    sign = '+' if cents > 0 else '−'
    return f'{sign}{abs(cents)} pts' if kind == 'points' else sign + format_money(abs(cents), currency)


def customers_page() -> None:
    ui.add_css(SHOP_CSS)
    profile = load_profile()
    page_header('Clientes', 'Quién compra, quién vende y cuánto saldo tiene cada uno.')
    if not profile.shop_mode:
        ui.label('Los clientes son parte del modo tienda. Actívalo en Ajustes → Modo tienda.').classes('oy-sub')
        return

    currency = profile.shop.currency
    desk = desk_for(account_root(), currency)
    state = {'customers': [], 'balances': {}, 'rules': None, 'loaded': False, 'busy': False}
    holder = ui.element('div')

    def money(cents: int) -> str:
        return format_money(cents, currency)

    def read():
        try:
            rules = desk.loyalty.rules()
        except Exception:  # the customers still show; redeeming says what is wrong when tried
            rules = None
        return desk.customers.all(), desk.customers.balances(), rules

    async def load() -> None:
        try:
            state['customers'], state['balances'], state['rules'] = await run.io_bound(read)
        except Exception as error:
            with holder:
                ui.notify(shop_failure(error, 'No se pudieron leer los clientes. Recarga la página.'),
                          type='negative')
            return
        state['loaded'] = True
        listing.refresh()

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
            return False
        finally:
            state['busy'] = False
        await load()
        if done:
            with holder:
                ui.notify(done, type='positive')
        return True

    # --- dialogs -----------------------------------------------------------------------------

    def edit(customer=None) -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 340px'):
            ui.label('Editar cliente' if customer else 'Nuevo cliente').classes('text-h6')
            name = ui.input('Nombre', value=customer.name if customer else '').props(
                'outlined dense autofocus maxlength=80').classes('w-full')
            email = ui.input('Email', value=customer.email if customer else '').props(
                'outlined dense maxlength=120').classes('w-full')
            phone = ui.input('Teléfono', value=customer.phone if customer else '').props(
                'outlined dense maxlength=40').classes('w-full')
            note = ui.textarea('Nota', value=customer.note if customer else '').props(
                'outlined dense autogrow maxlength=500').classes('w-full')

            async def save() -> None:
                fields = {'name': name.value or '', 'email': email.value or '', 'phone': phone.value or '',
                          'note': note.value or ''}
                if customer:
                    ok = await attempt(lambda: desk.customers.update(customer.id, **fields), done='Cliente guardado.')
                else:
                    ok = await attempt(lambda: desk.customers.add(**fields), done='Cliente añadido.')
                if ok:
                    dialog.close()

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Guardar', on_click=save).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    def adjust(customer) -> None:
        have = state['balances'].get(customer.id, {}).get('credit', 0)
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 340px'):
            ui.label(f'Saldo de {customer.name}').classes('text-h6')
            ui.label(f'Saldo de tienda actual: {money(have)}').classes('oy-mono')
            direction = ui.toggle({'add': 'Añadir saldo', 'take': 'Quitar saldo'}, value='add').props(
                'no-caps unelevated toggle-color=secondary')
            amount = ui.input('Importe', placeholder='0,00').props(f'outlined dense suffix={currency}').classes(
                'w-full')
            reason = ui.input('Motivo', placeholder='Regalo, corrección, devolución…').props(
                'outlined dense maxlength=200').classes('w-full')

            async def save() -> None:
                try:
                    cents = amount_cents(amount.value)
                except ValueError:
                    ui.notify('Escribe un importe mayor que cero, como 5 o 2,50.', type='warning')
                    return
                signed = cents if direction.value == 'add' else -cents
                if await attempt(desk.customers.post, customer.id, 'credit', signed, reason.value or '',
                                 done='Saldo actualizado.'):
                    dialog.close()

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Anotar', on_click=save).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    async def history(customer) -> None:
        try:
            entries = await run.io_bound(desk.customers.entries, customer.id)
        except Exception as error:
            ui.notify(shop_failure(error, 'No se pudieron leer los movimientos.'), type='negative')
            return
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 360px; max-width: 560px'):
            ui.label(f'Movimientos de {customer.name}').classes('text-h6')
            if not entries:
                ui.label('Todavía no hay movimientos.').classes('oy-sub')
            with ui.scroll_area().style('height: min(60vh, 420px)') if len(entries) > 8 else ui.column().classes(
                    'w-full gap-0'):
                for entry in sorted(entries, key=lambda e: e.at, reverse=True):
                    with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm no-wrap'):
                        with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                            ui.label(entry.reason).classes('text-sm ellipsis w-full')
                            ui.label(f'{LEDGER_LABELS.get(entry.kind, entry.kind)} · {when(entry.at)}').classes(
                                'oy-sub text-xs ellipsis w-full')
                        ui.label(amount_text(entry.kind, entry.cents, currency)).classes('oy-mono')
            with ui.row().classes('w-full justify-end q-mt-md'):
                ui.button('Cerrar', on_click=dialog.close).props('flat no-caps color=primary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    def redeem(customer) -> None:
        rules = state['rules']
        have = state['balances'].get(customer.id, {}).get('points', 0)
        blocks = have // rules.redeem_points if have > 0 else 0
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('max-width: 420px'):
            ui.label(f'Puntos de {customer.name}').classes('text-h6')
            ui.label(f'Tiene {have} puntos. Cada {rules.redeem_points} valen {money(rules.redeem_cents)} de '
                     'saldo de tienda.').classes('oy-sub')
            if blocks:
                ui.label(f'Se canjean {blocks * rules.redeem_points} puntos por '
                         f'{money(blocks * rules.redeem_cents)}.').classes('oy-mono')
            else:
                ui.label('Todavía no llega para canjear.').classes('oy-sub')

            async def confirm() -> None:
                dialog.close()
                await attempt(desk.loyalty.redeem, customer.id, done='Puntos canjeados por saldo de tienda.',
                              fallback='No se pudieron canjear los puntos. Inténtalo de nuevo.')

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                if blocks:
                    ui.button('Canjear', on_click=confirm).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    def remove(customer) -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('max-width: 420px'):
            ui.label(f'¿Borrar a {customer.name}?').classes('text-h6')
            ui.label('Se borra su ficha. Sus ventas y compras pasadas siguen en el historial con su nombre.').classes(
                'oy-sub')

            async def confirm() -> None:
                dialog.close()
                await attempt(desk.book.remove_customer, customer.id, done='Cliente borrado.',
                              fallback='No se pudo borrar. Inténtalo de nuevo.')

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Borrar', on_click=confirm).props('no-caps color=negative')
        dialog.on('hide', dialog.delete)
        dialog.open()

    # --- the list ----------------------------------------------------------------------------

    with ui.row().classes('w-full items-center gap-2 q-mt-md no-wrap'):
        query = ui.input(placeholder='Nombre, email o teléfono').props('outlined dense clearable debounce=250').style(
            'min-width: 0; flex: 1')
        with ui.button(on_click=lambda: edit()).props('no-caps color=secondary'):
            icon('user-plus')
            ui.label('Nuevo cliente').classes('q-ml-xs')

    @ui.refreshable
    def listing() -> None:
        if not state['loaded']:
            ui.label('Cargando clientes…').classes('oy-sub')
            return
        if not state['customers']:
            ui.label('Todavía no hay clientes. Añade el primero para darle saldo o abrirle una consigna.').classes(
                'oy-sub')
            return
        words = (query.value or '').casefold().split()
        found = [c for c in sorted(state['customers'], key=lambda c: c.name.casefold())
                 if all(word in f'{c.name} {c.email} {c.phone}'.casefold() for word in words)]
        if not found:
            ui.label('Ningún cliente con ese texto.').classes('oy-sub')
            return
        for customer in found[:SHOWN]:
            balance = state['balances'].get(customer.id, {})
            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm no-wrap'):
                with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                    ui.label(customer.name).classes('text-sm ellipsis w-full')
                    contact = ' · '.join(part for part in (customer.email, customer.phone, customer.note) if part)
                    ui.label(contact or 'Sin datos de contacto').classes('oy-sub text-xs ellipsis w-full')
                with ui.column().classes('gap-0 items-end'):
                    ui.label(money(balance.get('credit', 0))).classes('oy-mono').tooltip('Saldo de tienda')
                    if balance.get('consignment'):
                        ui.label(f'Consigna: {money(balance["consignment"])}').classes('oy-sub text-xs')
                    if balance.get('points'):
                        ui.label(f'{balance["points"]} pts').classes('oy-sub text-xs')
                if state['rules'] is not None and state['rules'].enabled:
                    with ui.button(on_click=lambda c=customer: redeem(c)).props(
                            'flat dense round color=primary').tooltip('Canjear puntos'):
                        icon('coin')
                with ui.button(on_click=lambda c=customer: adjust(c)).props('flat dense round color=primary').tooltip(
                        'Añadir o quitar saldo'):
                    icon('wallet')
                with ui.button(on_click=lambda c=customer: history(c)).props(
                        'flat dense round color=primary').tooltip('Movimientos'):
                    icon('history')
                with ui.button(on_click=lambda c=customer: edit(c)).props('flat dense round color=primary').tooltip(
                        'Editar'):
                    icon('edit')
                with ui.button(on_click=lambda c=customer: remove(c)).props('flat dense round color=primary').tooltip(
                        'Borrar'):
                    icon('trash')
        if len(found) > SHOWN:
            ui.label(f'Se muestran {SHOWN} clientes. Escribe más para afinar.').classes('oy-sub text-xs')

    listing()
    query.on_value_change(listing.refresh)
    ui.timer(0.1, load, once=True)
