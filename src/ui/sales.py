"""/ventas: the takings by day, each ticket, returns and the month's CSV."""

from __future__ import annotations

import logging
from datetime import datetime

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.account_scope import account_root
from src.core.game_collections import game_collection_store
from src.core.persistence import persistence
from src.core.sales_models import METHOD_LABELS, STATUS_LABELS, OutOfStock, Sale, format_money
from src.services.sales.checkout import Checkout, SaleError
from src.services.sales.inventory import Inventory
from src.services.sales.receipt import days, receipt_html, when_text
from src.services.sales.store import SalesStore, sales_csv
from src.services.sales.stripe_gateway import StripeError, StripeGateway
from src.services.sales.stripe_settings import load_key
from src.ui.icons import icon
from src.ui.theme import apply_theme, page_header

logger = logging.getLogger(__name__)

RECEIPT_CSS = '''
.oy-receipt { font-family: var(--oy-font-mono); font-size: 13px; color: var(--oy-text); max-width: 340px;
  margin: 0 auto; }
.oy-receipt-shop { font-family: var(--oy-font-display); font-size: 20px; text-align: center; }
.oy-receipt-small { font-size: 11px; color: var(--oy-muted); }
.oy-receipt > .oy-receipt-small { text-align: center; }
.oy-receipt-meta { text-align: center; margin: 10px 0; padding: 6px 0; border-top: 1px dashed var(--oy-border);
  border-bottom: 1px dashed var(--oy-border); }
.oy-receipt-state { text-align: center; font-weight: 600; color: var(--oy-accent); margin-bottom: 8px; }
.oy-receipt table { width: 100%; border-collapse: collapse; }
.oy-receipt td { padding: 3px 0; vertical-align: top; }
.oy-receipt-num { text-align: right; white-space: nowrap; padding-left: 10px !important; }
.oy-receipt-totals { margin-top: 8px; border-top: 1px dashed var(--oy-border); }
.oy-receipt-thanks { margin-top: 12px; }
.oy-sale-row { border-bottom: 1px solid var(--oy-border-soft); }
.oy-day { border: 1px solid var(--oy-border); border-radius: 6px; background: var(--oy-surface); }
@media print {
  body * { visibility: hidden !important; }
  .oy-receipt, .oy-receipt * { visibility: visible !important; color: #000 !important; }
  .oy-receipt { position: fixed; left: 0; top: 0; margin: 0; }
}
'''
MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
          'noviembre', 'diciembre']


def failure_text(error: Exception) -> str:
    """Only messages written for the person at the counter reach the screen."""
    if isinstance(error, (SaleError, StripeError, OutOfStock)):
        return str(error)
    logger.error('Ventas: %s', type(error).__name__)
    return 'No se pudo completar el cobro. Inténtalo de nuevo.'


def month_label(month: str) -> str:
    try:
        return f'{MONTHS[int(month[5:7]) - 1]} de {month[:4]}'
    except (ValueError, IndexError):
        return month


def day_label(date: str) -> str:
    try:
        return datetime.strptime(date, '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        return date


def method_summary(by_method: dict, currency: str) -> str:
    return ' · '.join(f'{METHOD_LABELS[method]} {format_money(by_method[method], currency)}'
                      for method in METHOD_LABELS if by_method.get(method))


def build_checkout() -> Checkout:
    """Bound to the signed-in account. Call it on the UI thread."""
    from src.services.shop.desk import desk_for

    return desk_for(account_root()).checkout


def show_receipt(sale: Sale, shop) -> None:
    with ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 320px; max-width: 420px'):
        ui.html(receipt_html(sale, shop), sanitize=False).classes('w-full')
        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Cerrar', on_click=dialog.close).props('flat no-caps color=primary')
            with ui.button(on_click=lambda: ui.run_javascript('window.print()')).props('no-caps color=secondary'):
                icon('printer-device')
                ui.label('Imprimir').classes('q-ml-xs')
    dialog.on('hide', dialog.delete)
    dialog.open()


def sales_page() -> None:
    ui.add_css(RECEIPT_CSS)
    profile = load_profile()
    page_header('Ventas', 'Lo cobrado en el mostrador, día a día.')
    if not profile.shop_mode:
        ui.label('Las ventas son parte del modo tienda. Actívalo en Ajustes → Modo tienda.').classes('oy-sub')
        return
    root = account_root()
    shop = profile.shop
    store = SalesStore(root)
    checkout = build_checkout()
    state = {'month': datetime.now().strftime('%Y-%m'), 'sales': [], 'busy': False}
    holder = ui.element('div')  # outlives the rows, so messages after a refresh still have a home

    async def gateway():
        key = await run.io_bound(load_key, root)
        return StripeGateway(key) if key else None

    with ui.row().classes('w-full items-center gap-3 q-mt-md'):
        picker = ui.select({state['month']: month_label(state['month'])}, value=state['month'],
                           label='Mes').props('outlined dense').classes('w-56')
        ui.space()
        with ui.button().props('flat no-caps color=primary') as export_button:
            icon('download')
            ui.label('Exportar CSV del mes').classes('q-ml-xs')

    @ui.refreshable
    def listing() -> None:
        sales = state['sales']
        if not sales:
            ui.label('No hay ventas este mes.').classes('oy-sub q-mt-md')
            return
        paid = [sale for sale in sales if sale.status == 'paid']
        currencies = sorted({sale.currency for sale in paid}) or [shop.currency]
        for currency in currencies:
            mine = [sale for sale in paid if sale.currency == currency]
            by_method: dict = {}
            for sale in mine:
                by_method[sale.method] = by_method.get(sale.method, 0) + sale.total_cents
            with ui.row().classes('w-full items-baseline gap-4 q-mt-md'):
                ui.label(format_money(sum(sale.total_cents for sale in mine), currency)).classes('oy-h1')
                ui.label(f'{len(mine)} venta{"s" if len(mine) != 1 else ""} · '
                         + (method_summary(by_method, currency) or 'sin cobros')).classes('oy-sub')
        for day in days(sales):
            with ui.column().classes('oy-day w-full gap-0 q-mt-md q-pa-md'):
                with ui.row().classes('w-full items-baseline gap-3'):
                    ui.label(day_label(day.date)).classes('text-subtitle1')
                    ui.space()
                    currency = day.sales[0].currency
                    ui.label(method_summary(day.by_method, currency)).classes('oy-sub')
                    ui.label(format_money(day.total_cents, currency)).classes('oy-mono text-subtitle1')
                for sale in day.sales:
                    _row(sale)

    def _row(sale: Sale) -> None:
        with ui.row().classes('oy-sale-row w-full items-center gap-3 q-py-sm no-wrap'):
            ui.label(sale.label).classes('oy-mono').style('min-width: 84px')
            ui.label(when_text(sale.paid_at or sale.created_at)[-5:]).classes('oy-sub')
            names = ', '.join(line.name for line in sale.lines[:2]) + ('…' if len(sale.lines) > 2 else '')
            ui.label(f'{sale.units} art. · {names}').classes('text-sm ellipsis').style('min-width: 0; flex: 1')
            ui.label(METHOD_LABELS.get(sale.method, sale.method)).classes('oy-sub oy-desktop-only')
            if sale.status != 'paid':
                ui.label(STATUS_LABELS.get(sale.status, sale.status)).classes('text-xs').style(
                    'color: var(--oy-accent)')
            ui.label(format_money(sale.total_cents, sale.currency)).classes('oy-mono').style(
                'text-decoration: line-through' if sale.status in ('refunded', 'cancelled') else '')
            with ui.button(on_click=lambda sale=sale: show_receipt(sale, shop)).props(
                    'flat dense round color=primary').tooltip('Ver ticket'):
                icon('receipt')
            if sale.status == 'paid':
                with ui.button(on_click=lambda sale=sale: ask_refund(sale)).props(
                        'flat dense round color=primary').tooltip('Devolver'):
                    icon('undo')
            elif sale.status == 'pending':
                with ui.button(on_click=lambda sale=sale: settle(sale)).props(
                        'flat dense round color=primary').tooltip('Comprobar el pago'):
                    icon('refresh-cw')
                with ui.button(on_click=lambda sale=sale: cancel(sale)).props(
                        'flat dense round color=primary').tooltip('Cancelar el cobro'):
                    icon('x')
        if sale.note:
            ui.label(sale.note).classes('text-xs').style('color: var(--oy-accent)')

    async def reload(reconcile: bool = False) -> None:
        if reconcile:
            try:
                stripe = await gateway()
                if stripe:
                    await run.io_bound(checkout.reconcile, stripe)
            except Exception as error:  # the list still loads; pending sales stay pending
                logger.warning('Ventas: no se pudo conciliar con Stripe: %s', type(error).__name__)
        months = await run.io_bound(store.months)
        current = datetime.now().strftime('%Y-%m')
        options = {month: month_label(month) for month in sorted(set(months) | {current, state['month']},
                                                                 reverse=True)}
        picker.set_options(options, value=state['month'])
        state['sales'] = await run.io_bound(store.month, state['month'])
        listing.refresh()

    async def act(work, done: str) -> None:
        if state['busy']:
            return
        state['busy'] = True
        with holder:
            try:
                message = await work()
                ui.notify(message or done, type='positive')
            except Exception as error:
                ui.notify(failure_text(error), type='negative', multi_line=True)
            finally:
                state['busy'] = False
            await reload()

    def ask_refund(sale: Sale) -> None:
        with ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('max-width: 440px'):
            ui.label(f'Devolver el ticket {sale.label}').classes('text-h6')
            text = f'Las cartas vuelven a su colección y la venta de {format_money(sale.total_cents, sale.currency)} ' \
                   'queda como devuelta.'
            if sale.method == 'stripe':
                text += ' El importe se reembolsa en Stripe a la tarjeta del cliente.'
            elif sale.method == 'card':
                text += ' Haz la devolución en el datáfono: la aplicación no lo toca.'
            else:
                text += ' Devuelve el efectivo al cliente.'
            ui.label(text).classes('oy-sub')

            async def confirm() -> None:
                dialog.close()

                async def work():
                    stripe = await gateway() if sale.method == 'stripe' else None
                    await run.io_bound(checkout.refund, sale.id, stripe)

                await act(work, f'Ticket {sale.label} devuelto.')

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('No devolver', on_click=dialog.close).props('flat no-caps color=primary')
                ui.button('Devolver', on_click=confirm).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    async def with_stripe(action, sale: Sale) -> str:
        stripe = await gateway()
        if stripe is None:
            raise SaleError('Conecta Stripe en Ajustes para consultar este cobro.')
        result = await run.io_bound(action, sale.id, stripe)
        return {'paid': f'Cobrado: ticket {result.label}.', 'cancelled': 'Cobro cancelado; el stock ha vuelto.',
                'pending': 'El cliente todavía no ha pagado.'}.get(result.status, '')

    async def settle(sale: Sale) -> None:
        await act(lambda: with_stripe(checkout.settle_stripe, sale), '')

    async def cancel(sale: Sale) -> None:
        await act(lambda: with_stripe(checkout.cancel_stripe, sale), '')

    async def change_month(event) -> None:
        if event.value and event.value != state['month']:
            state['month'] = event.value
            await reload()

    async def export() -> None:
        if not state['sales']:
            ui.notify('No hay ventas que exportar este mes.', type='warning')
            return
        data = await run.io_bound(sales_csv, state['sales'])
        ui.download.content(data, f'ventas-{state["month"]}.csv', 'text/csv')

    picker.on_value_change(change_month)
    export_button.on_click(export)
    listing()
    ui.timer(0.1, lambda: reload(reconcile=True), once=True)


def paid_page() -> None:
    """Where Stripe sends the customer's phone after paying. Public and without any data."""
    apply_theme()
    with ui.column().classes('w-full items-center q-pa-xl gap-3').style('margin-top: 12vh'):
        icon('check', 56)
        ui.label('Pago recibido').classes('oy-h1')
        ui.label('Gracias por tu compra. Ya puedes cerrar esta página.').classes('oy-sub')
