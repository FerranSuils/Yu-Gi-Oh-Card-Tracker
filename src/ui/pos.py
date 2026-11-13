"""/tpv: the counter. Search the stock, build a ticket and charge it."""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlsplit

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.account_scope import account_root
from src.core.game_collections import game_collection_store
from src.core.persistence import persistence
from src.core.sales_models import OutOfStock, Sale, SaleLine, format_money, to_cents
from src.services.sales.checkout import Checkout
from src.services.sales.inventory import Inventory, line_key, search
from src.services.sales.receipt import qr_svg
from src.services.sales.store import SalesStore
from src.services.sales.stripe_gateway import StripeGateway
from src.services.sales.stripe_settings import load_key
from src.services.sales.ticket import Ticket
from src.services.shop.desk import desk_for
from src.services.shop.kiosk import fit_to_stock
from src.ui.icons import icon
from src.ui.sales import RECEIPT_CSS, failure_text, show_receipt
from src.ui.shop_common import SHOP_ERRORS, customer_options, when
from src.ui.theme import page_header

logger = logging.getLogger(__name__)

__all__ = ['failure_text', 'pile_text', 'pos_page', 'success_url']

RESULTS = 40
POLL_SECONDS = 3.0
_HOST = re.compile(r'[A-Za-z0-9.-]+(:\d{1,5})?')
POS_CSS = '''
.oy-pos { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 440px); gap: 24px; width: 100%;
  align-items: start; }
@media (max-width: 900px) { .oy-pos { grid-template-columns: minmax(0, 1fr); } }
.oy-pos-row { border-bottom: 1px solid var(--oy-border-soft); }
.oy-pos-ticket { border: 1px solid var(--oy-border); border-radius: 6px; background: var(--oy-surface); }
.oy-pos-total { font-family: var(--oy-font-display); font-size: 30px; line-height: 1.1; }
.oy-pos-qr { background: #fff; padding: 8px; border-radius: 6px; line-height: 0; }
'''


def success_url(headers, base_url: str) -> str:
    """Where Stripe sends the customer after paying: this site's public thank-you page."""
    configured = os.environ.get('OPENYUGI_PUBLIC_URL', '').strip().rstrip('/')
    if configured:
        return configured + '/tpv/pagado'
    host = (headers.get('x-forwarded-host') or '').strip()
    if host and _HOST.fullmatch(host):
        scheme = (headers.get('x-forwarded-proto') or 'https').split(',')[0].strip().lower()
        return f'{scheme if scheme in ("http", "https") else "https"}://{host}/tpv/pagado'
    parts = urlsplit(str(base_url))
    return f'{parts.scheme}://{parts.netloc}/tpv/pagado'


def pile_text(line: SaleLine) -> str:
    """Which physical pile a line is: printing, condition, language, edition and where it is kept."""
    if line.kind != 'stock':
        return 'Artículo sin inventario'
    return ' · '.join(part for part in (
        line.set_code, line.rarity, line.finish, line.condition, line.language,
        '1.ª ed.' if line.first_edition else '', line.storage_location or '') if part)


def plain_price(cents: int) -> str:
    return f'{cents / 100:.2f}'.replace('.', ',') if cents else ''


def pos_page() -> None:
    ui.add_css(RECEIPT_CSS + POS_CSS)
    profile = load_profile()
    page_header('Mostrador', 'Busca en tu stock, monta el ticket y cobra.')
    if not profile.shop_mode:
        ui.label('El mostrador es parte del modo tienda. Actívalo en Ajustes → Modo tienda.').classes('oy-sub')
        return

    root = account_root()
    shop = profile.shop
    currency = shop.currency
    games = enabled_games(profile)
    desk = desk_for(root, currency)
    inventory = desk.inventory
    checkout = desk.checkout
    ticket = Ticket()
    request = ui.context.client.request
    back_url = success_url(request.headers, request.base_url)
    state = {'items': [], 'busy': False, 'loaded': False}
    holder = ui.element('div')  # dialogs and messages live here, outside anything that refreshes

    def money(cents: int) -> str:
        return format_money(cents, currency)

    # --- shelf -------------------------------------------------------------------------------

    with ui.element('div').classes('oy-pos q-mt-md'):
        with ui.column().classes('w-full gap-2'):
            query = ui.input(placeholder='Nombre, set o número de la carta').props(
                'outlined dense clearable debounce=250 autofocus').classes('w-full')

            @ui.refreshable
            def results() -> None:
                if not state['loaded']:
                    ui.label('Cargando el stock…').classes('oy-sub')
                    return
                if not state['items']:
                    ui.label('No hay cartas en tus colecciones. Añade stock y aparecerá aquí.').classes('oy-sub')
                    return
                found = search(state['items'], query.value or '', RESULTS)
                if not found:
                    ui.label('Nada en stock con ese texto.').classes('oy-sub')
                    return
                for item in found:
                    with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm no-wrap'):
                        with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                            ui.label(item.name).classes('text-sm ellipsis w-full')
                            ui.label(pile_text(item)).classes('oy-sub text-xs ellipsis w-full')
                        ui.label(f'×{item.quantity}').classes('oy-mono oy-sub')
                        ui.label(money(item.unit_cents) if item.unit_cents else 'sin precio').classes('oy-mono')
                        with ui.button(on_click=lambda item=item: add(item)).props(
                                'flat dense round color=primary').tooltip('Añadir al ticket'):
                            icon('plus')
                if len(found) == RESULTS:
                    ui.label(f'Se muestran {RESULTS} pilas. Escribe más para afinar.').classes('oy-sub text-xs')

            results()
            query.on_value_change(results.refresh)

        # --- ticket --------------------------------------------------------------------------

        with ui.column().classes('oy-pos-ticket w-full gap-2 q-pa-md'):
            with ui.row().classes('w-full items-center gap-2'):
                icon('receipt', 18)
                ui.label('Ticket').classes('text-subtitle1')

            @ui.refreshable
            def lines_view() -> None:
                if not ticket.lines:
                    ui.label('Añade cartas desde la búsqueda.').classes('oy-sub')
                    return
                for index, line in enumerate(ticket.lines):
                    with ui.column().classes('oy-pos-row w-full gap-1 q-py-sm'):
                        with ui.row().classes('w-full items-center gap-2 no-wrap'):
                            with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                                ui.label(line.name).classes('text-sm ellipsis w-full')
                                ui.label(pile_text(line)).classes('oy-sub text-xs ellipsis w-full')
                            with ui.button(on_click=lambda index=index: remove(index)).props(
                                    'flat dense round color=primary').tooltip('Quitar'):
                                icon('trash')
                        with ui.row().classes('w-full items-center gap-2 no-wrap'):
                            limit = ticket.stock(index)
                            amount = ui.number(value=line.quantity, min=1, max=limit, step=1, format='%d').props(
                                'outlined dense').classes('w-20').tooltip(
                                f'Hay {limit} en la pila' if limit is not None else 'Unidades')
                            ui.label('×').classes('oy-sub')
                            price = ui.input(value=plain_price(line.unit_cents), placeholder='0,00').props(
                                f'outlined dense suffix={currency}').classes('w-28')
                            ui.space()
                            total = ui.label(money(line.total_cents)).classes('oy-mono')
                            amount.on_value_change(
                                lambda event, index=index, total=total: set_quantity(index, event.value, total))
                            price.on('change', lambda _, index=index, price=price, total=total:
                                     set_price(index, price, total))

            lines_view()

            with ui.expansion('Artículo sin inventario').props('dense').classes('w-full'):
                with ui.row().classes('w-full items-center gap-2'):
                    custom_name = ui.input(placeholder='Fundas, sobre, torneo…').props(
                        'outlined dense maxlength=120').style('min-width: 0; flex: 1')
                    custom_price = ui.input(placeholder='0,00').props(f'outlined dense suffix={currency}').classes(
                        'w-28')
                    custom_units = ui.number(value=1, min=1, max=999, step=1, format='%d').props(
                        'outlined dense').classes('w-20')
                    with ui.button(on_click=lambda: add_custom()).props('flat dense round color=primary').tooltip(
                            'Añadir al ticket'):
                        icon('plus')

            with ui.row().classes('w-full items-center gap-2 q-mt-sm'):
                discount_kind = ui.select({'none': 'Sin descuento', 'percent': 'Descuento %',
                                           'amount': f'Descuento {currency}'}, value='none').props(
                    'outlined dense').style('min-width: 0; flex: 1')
                discount_value = ui.input(placeholder='0').props('outlined dense').classes('w-28')
            discount_error = ui.label('').classes('oy-form-error text-negative text-xs')

            @ui.refreshable
            def totals() -> None:
                if ticket.discount_cents:
                    with ui.row().classes('w-full items-baseline'):
                        ui.label('Subtotal').classes('oy-sub')
                        ui.space()
                        ui.label(money(ticket.subtotal)).classes('oy-mono')
                    with ui.row().classes('w-full items-baseline'):
                        ui.label('Descuento').classes('oy-sub')
                        ui.space()
                        ui.label('−' + money(ticket.discount_cents)).classes('oy-mono')
                with ui.row().classes('w-full items-baseline'):
                    ui.label('Total').classes('text-subtitle1')
                    ui.space()
                    ui.label(money(ticket.total)).classes('oy-pos-total')
                blocker = ticket.blocker()
                if blocker and ticket.lines:
                    ui.label(blocker).classes('oy-form-error text-negative text-sm')

            totals()

            with ui.row().classes('w-full gap-2 q-mt-sm'):
                with ui.button(on_click=lambda: ask_cash()).props('no-caps color=secondary').classes('col'):
                    icon('cash-payment')
                    ui.label('Efectivo').classes('q-ml-xs')
                with ui.button(on_click=lambda: ask_card()).props('no-caps outline color=primary').classes('col'):
                    icon('credit-card')
                    ui.label('Datáfono').classes('q-ml-xs')
            with ui.button(on_click=lambda: pay_stripe()).props('no-caps outline color=primary').classes('w-full'):
                icon('qr-payment')
                ui.label('Cobrar con Stripe (QR o enlace)').classes('q-ml-xs')
            with ui.row().classes('w-full gap-2'):
                with ui.button(on_click=lambda: ask_credit()).props('no-caps outline color=primary').classes(
                        'col'):
                    icon('wallet')
                    ui.label('Saldo de cliente').classes('q-ml-xs')
                with ui.button(on_click=lambda: ask_lists()).props('no-caps outline color=primary').classes(
                        'col'):
                    icon('shopping-list')
                    ui.label('Listas del kiosko').classes('q-ml-xs')

    # --- ticket edits ------------------------------------------------------------------------

    def add(item: SaleLine) -> None:
        message = ticket.add(item)
        if message:
            ui.notify(message, type='warning')
        lines_view.refresh()
        totals.refresh()

    def remove(index: int) -> None:
        if index < len(ticket.lines):
            ticket.remove(index)
        lines_view.refresh()
        totals.refresh()

    def set_quantity(index: int, value, total) -> None:
        if value is None or index >= len(ticket.lines):
            return
        ticket.set_quantity(index, value)
        total.set_text(money(ticket.lines[index].total_cents))
        totals.refresh()

    def set_price(index: int, price, total) -> None:
        if index >= len(ticket.lines):
            return
        try:
            ticket.set_price(index, price.value or '0')
            price.props(remove='error')
        except ValueError:
            price.props('error')
            ui.notify('Ese precio no es un número. Usa, por ejemplo, 2,50.', type='warning')
            return
        total.set_text(money(ticket.lines[index].total_cents))
        totals.refresh()

    def add_custom() -> None:
        try:
            ticket.add_custom(custom_name.value, custom_price.value or '0', custom_units.value or 1)
        except ValueError as error:
            ui.notify(str(error) if 'Escribe' in str(error) else 'Ese precio no es un número. Usa, por ejemplo, 2,50.',
                      type='warning')
            return
        custom_name.set_value('')
        custom_price.set_value('')
        custom_units.set_value(1)
        lines_view.refresh()
        totals.refresh()

    def set_discount() -> None:
        kind = discount_kind.value or 'none'
        try:
            ticket.set_discount(kind, discount_value.value or '0')
            discount_error.set_text('')
        except ValueError as error:
            ticket.set_discount('none', '')
            discount_error.set_text(f'{error}. No se aplica ningún descuento.')
        totals.refresh()

    discount_kind.on_value_change(set_discount)
    discount_value.on_value_change(set_discount)

    # --- stock -------------------------------------------------------------------------------

    async def load(reconcile: bool = False) -> bool:
        if reconcile:
            try:
                key = await run.io_bound(load_key, root)
                if key:
                    await run.io_bound(checkout.reconcile, StripeGateway(key))
            except Exception as error:
                logger.warning('Mostrador: no se pudo conciliar con Stripe: %s', type(error).__name__)
        try:
            state['items'] = await run.io_bound(inventory.items, games)
        except Exception as error:
            logger.error('Mostrador: no se pudo leer el stock: %s', type(error).__name__)
            with holder:
                ui.notify('No se pudo leer el stock. Recarga la página.', type='negative')
            return False
        state['loaded'] = True
        changed = ticket.sync(state['items']) if ticket.lines else []
        if changed:
            with holder:
                ui.notify('El stock ha cambiado. Revisa en el ticket: ' + ', '.join(changed[:4]) + '.',
                          type='warning', multi_line=True)
        results.refresh()
        lines_view.refresh()
        totals.refresh()
        return True

    def ready() -> bool:
        if state['busy']:
            return False
        blocker = ticket.blocker()
        if blocker:
            ui.notify(blocker, type='warning')
            return False
        return True

    def snapshot() -> list:
        return [line.model_copy() for line in ticket.lines]

    def reset_ticket() -> None:
        ticket.clear()
        discount_kind.set_value('none')
        discount_value.set_value('')
        discount_error.set_text('')

    async def finish(sale: Sale) -> None:
        reset_ticket()
        await load()
        with holder:
            ui.notify(f'Cobrado: ticket {sale.label}, {money(sale.total_cents)}.', type='positive')
            show_receipt(sale, shop)

    async def fail(error: Exception) -> None:
        with holder:
            ui.notify(str(error) if isinstance(error, SHOP_ERRORS) and str(error) else failure_text(error),
                      type='negative', multi_line=True)
        if isinstance(error, OutOfStock):
            await load()

    # --- cash and card -----------------------------------------------------------------------

    async def charge(method: str, received_cents=None, customer_id=None) -> None:
        if not ready():
            return
        state['busy'] = True
        try:
            sale = await run.io_bound(checkout.charge, snapshot(), ticket.discount, method, currency,
                                      received_cents, customer_id)
        except Exception as error:
            await fail(error)
            return
        finally:
            state['busy'] = False
        await finish(sale)

    def ask_cash() -> None:
        if not ready():
            return
        due = ticket.total
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 320px'):
            ui.label('Cobro en efectivo').classes('text-h6')
            ui.label(f'Total: {money(due)}').classes('oy-mono')
            received = ui.input('Entregado', placeholder=plain_price(due)).props(
                f'outlined autofocus suffix={currency}').classes('w-full q-mt-sm')
            change = ui.label('Deja el campo vacío si te dan el importe justo.').classes('oy-sub')

            def amount():
                return to_cents(received.value) if (received.value or '').strip() else due

            def show_change() -> None:
                try:
                    given = amount()
                except ValueError:
                    change.set_text('Ese importe no es un número.')
                    return
                change.set_text(f'Cambio: {money(given - due)}' if given >= due
                                else f'Faltan {money(due - given)}')

            async def confirm() -> None:
                try:
                    given = amount()
                except ValueError:
                    ui.notify('Ese importe no es un número. Usa, por ejemplo, 20 o 20,50.', type='warning')
                    return
                if given < due:
                    ui.notify(f'Faltan {money(due - given)} para cubrir el total.', type='warning')
                    return
                dialog.close()
                await charge('cash', given)

            received.on_value_change(show_change)
            received.on('keydown.enter', confirm)
            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Cobrar', on_click=confirm).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    def ask_card() -> None:
        if not ready():
            return
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('max-width: 420px'):
            ui.label('Cobro con datáfono').classes('text-h6')
            ui.label(f'Cobra {money(ticket.total)} en tu datáfono y confirma aquí cuando el pago esté aceptado. '
                     'La aplicación solo lo anota.').classes('oy-sub')

            async def confirm() -> None:
                dialog.close()
                await charge('card')

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Pago aceptado', on_click=confirm).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    # --- store credit ------------------------------------------------------------------------

    async def ask_credit() -> None:
        if not ready():
            return
        try:
            customers, balances = await run.io_bound(lambda: (desk.customers.all(), desk.customers.balances()))
        except Exception as error:
            logger.error('Mostrador: no se pudieron leer los clientes: %s', type(error).__name__)
            with holder:
                ui.notify('No se pudieron leer los clientes. Inténtalo de nuevo.', type='negative')
            return
        due = ticket.total
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 340px; max-width: 440px'):
            ui.label('Cobro con saldo de cliente').classes('text-h6')
            ui.label(f'Total: {money(due)}').classes('oy-mono')
            if not customers:
                ui.label('Todavía no hay clientes. Añádelos en Clientes y dales saldo.').classes('oy-sub')
            who = ui.select(customer_options(customers, balances, currency), label='Cliente', with_input=True).props(
                'outlined dense').classes('w-full q-mt-sm')
            note = ui.label('').classes('oy-sub')

            def have() -> int:
                return balances.get(who.value, {}).get('credit', 0) if who.value else 0

            def show() -> None:
                if not who.value:
                    note.set_text('')
                elif have() < due:
                    note.set_text(f'Le faltan {money(due - have())} de saldo.')
                else:
                    note.set_text(f'Le quedarán {money(have() - due)} de saldo.')

            async def confirm() -> None:
                if not who.value:
                    ui.notify('Elige el cliente que paga con su saldo.', type='warning')
                    return
                if have() < due:
                    ui.notify(f'Le faltan {money(due - have())} de saldo.', type='warning')
                    return
                dialog.close()
                await charge('credit', None, who.value)

            who.on_value_change(show)
            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Cobrar', on_click=confirm).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    # --- lists from the kiosk ----------------------------------------------------------------

    async def ask_lists() -> None:
        if state['busy']:
            return
        try:
            orders = await run.io_bound(desk.orders.open)
        except Exception as error:
            logger.error('Mostrador: no se pudieron leer las listas: %s', type(error).__name__)
            with holder:
                ui.notify('No se pudieron leer las listas del kiosko. Inténtalo de nuevo.', type='negative')
            return
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 340px; max-width: 520px'):
            ui.label('Listas del kiosko').classes('text-h6')
            if not orders:
                ui.label('No hay listas esperando. Las que envían tus clientes desde el kiosko aparecen aquí '
                         'durante 24 horas.').classes('oy-sub')
            for order in orders:
                copies = sum(line.quantity for line in order.lines)
                with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm no-wrap'):
                    ui.label(order.code).classes('oy-mono text-subtitle1')
                    with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                        ui.label(order.name).classes('text-sm ellipsis w-full')
                        ui.label(f'{copies} {"carta" if copies == 1 else "cartas"} · {when(order.created_at)}'
                                 ).classes('oy-sub text-xs ellipsis w-full')

                    async def take(order=order) -> None:
                        dialog.close()
                        await load_list(order.id)

                    async def discard(order=order) -> None:
                        dialog.close()
                        try:
                            await run.io_bound(desk.orders.discard, order.id)
                        except Exception as error:
                            await fail(error)
                            return
                        with holder:
                            ui.notify(f'Lista {order.code} descartada.', type='info')

                    ui.button('Descartar', on_click=discard).props('flat no-caps color=primary')
                    ui.button('Cargar', on_click=take).props('no-caps color=secondary')
            with ui.row().classes('w-full justify-end q-mt-md'):
                ui.button('Cerrar', on_click=dialog.close).props('flat no-caps color=primary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    async def load_list(order_id: str) -> None:
        if state['busy']:
            return
        state['busy'] = True
        try:
            await run.io_bound(desk.orders.get, order_id)
            if not await load():  # without today's stock the list stays in the queue for another try
                return
            order = await run.io_bound(desk.orders.take, order_id)
        except Exception as error:
            await fail(error)
            return
        finally:
            state['busy'] = False
        lines, short = fit_to_stock(order.lines, state['items'])
        for line in lines:
            key = line_key(line)
            pile = next((item for item in state['items'] if line_key(item) == key), None)
            if pile is None:
                continue
            if ticket.add(pile):
                short.append(f'{line.name} (ya estaba entera en el ticket)')
                continue
            index = next(i for i, held in enumerate(ticket.lines) if held.kind == 'stock' and line_key(held) == key)
            ticket.set_quantity(index, ticket.lines[index].quantity - 1 + line.quantity)
        lines_view.refresh()
        totals.refresh()
        with holder:
            ui.notify(f'Lista {order.code} de {order.name} cargada en el ticket.', type='positive')
            if short:
                ui.notify('Revisa con el cliente: ' + ', '.join(short[:5]) + '.', type='warning', multi_line=True)

    # --- Stripe ------------------------------------------------------------------------------

    async def pay_stripe() -> None:
        if not ready():
            return
        state['busy'] = True
        try:
            key = await run.io_bound(load_key, root)
            if not key:
                with holder:
                    ui.notify('Conecta tu cuenta de Stripe en Ajustes → Cobros con Stripe.', type='warning')
                return
            gateway = StripeGateway(key)
            sale = await run.io_bound(checkout.start_stripe, snapshot(), ticket.discount, currency, back_url, gateway)
        except Exception as error:
            await fail(error)
            return
        finally:
            state['busy'] = False
        wait_for_payment(sale, gateway)

    def wait_for_payment(sale: Sale, gateway: StripeGateway) -> None:
        waiting = {'busy': False, 'done': False}
        with holder, ui.dialog().props('persistent') as dialog, ui.card().classes('q-pa-lg items-center').style(
                'min-width: 320px; max-width: 420px'):
            ui.label(f'Cobro de {money(sale.total_cents)}').classes('text-h6')
            ui.label('El cliente escanea el código con su móvil y paga con tarjeta.').classes('oy-sub text-center')
            ui.html(qr_svg(sale.stripe_url), sanitize=False).classes('oy-pos-qr q-my-md')
            with ui.button(on_click=lambda: (ui.clipboard.write(sale.stripe_url),
                                             ui.notify('Enlace copiado.', type='positive'))).props(
                    'flat no-caps color=primary'):
                icon('link')
                ui.label('Copiar el enlace de pago').classes('q-ml-xs')
            status = ui.label('Esperando el pago…').classes('oy-sub')
            ui.label('Las cartas quedan reservadas hasta que se pague o se cancele (máximo 30 minutos).').classes(
                'oy-sub text-xs text-center')

            async def close(result: Sale) -> None:
                if waiting['done']:
                    return
                waiting['done'] = True
                timer.deactivate()
                dialog.close()
                if result.status == 'paid':
                    await finish(result)
                    return
                with holder:
                    ui.notify('Cobro cancelado. Las cartas siguen en el ticket y en tu stock.', type='warning')
                await load()

            async def poll() -> None:
                if waiting['busy'] or waiting['done']:
                    return
                waiting['busy'] = True
                try:
                    result = await run.io_bound(checkout.settle_stripe, sale.id, gateway)
                except Exception as error:
                    logger.warning('Mostrador: Stripe no responde: %s', type(error).__name__)
                    status.set_text('Stripe no responde. Se vuelve a intentar…')
                    return
                finally:
                    waiting['busy'] = False
                if result.status == 'pending':
                    status.set_text('Esperando el pago…')
                else:
                    await close(result)

            async def cancel() -> None:
                if waiting['done']:
                    return
                try:
                    result = await run.io_bound(checkout.cancel_stripe, sale.id, gateway)
                except Exception as error:
                    ui.notify(failure_text(error), type='negative', multi_line=True)
                    return
                await close(result)

            ui.button('Cancelar el cobro', on_click=cancel).props('flat no-caps color=primary').classes('q-mt-sm')
        with holder:
            timer = ui.timer(POLL_SECONDS, poll)
        dialog.on('hide', dialog.delete)
        dialog.open()

    ui.timer(0.1, lambda: load(reconcile=True), once=True)
