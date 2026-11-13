"""/pedidos: what was sold away from the counter, from the moment it arrives until it is delivered."""

from __future__ import annotations

from typing import Dict, List

from nicegui import events, run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.account_scope import account_root
from src.core.order_models import CHANNEL_LABELS, ORDER_LABELS, Address, Order, OrderLine, ShippingMethod
from src.core.sales_models import SaleLine, format_money, to_cents
from src.services.csv_suite import MAX_BYTES
from src.services.orders.book import pick_list, tracking_url
from src.services.orders.channels import CHANNELS, ChannelSettings
from src.services.orders.importer import bring_in, parse_orders, shelves_or_refuse
from src.services.orders.paper import VIEWS, in_view, matching, next_steps, picks_html, slip_html
from src.services.orders.sku import sku_of
from src.services.orders.sync import due_channels, sync_channel
from src.services.sales.inventory import line_key, search
from src.services.shop.desk import desk_for
from src.ui.icons import icon
from src.ui.pos import pile_text
from src.ui.settings_channels import sync_label, sync_lines
from src.ui.shop_common import SHOP_CSS, customer_options, shop_failure, when
from src.ui.theme import page_header

ICONS = ('plus', 'minus', 'trash', 'upload', 'eye', 'printer-device', 'clipboard', 'truck-delivery', 'package-box',
         'package-check', 'package-return', 'delivery-note', 'cash-payment', 'ban', 'link', 'x', 'refresh-cw')
SHOWN = 100
RESULTS = 20
IMPORT_CHANNELS = ('cardmarket', 'tcgplayer', 'ebay', 'shopify', 'woocommerce', 'otro')
STEP_LABELS = {'paid': 'Marcar cobrado', 'packed': 'Marcar preparado', 'ship': 'Enviar', 'delivered': 'Entregado',
               'cancel': 'Anular', 'return': 'Devolución'}
STEP_ICONS = {'paid': 'cash-payment', 'packed': 'package-box', 'ship': 'truck-delivery',
              'delivered': 'package-check', 'cancel': 'ban', 'return': 'package-return'}
ORDERS_CSS = '''
.oy-slip { font-family: var(--oy-font-mono); font-size: 13px; color: var(--oy-text); max-width: 640px;
  margin: 0 auto; }
.oy-slip-shop { font-family: var(--oy-font-display); font-size: 20px; }
.oy-slip-small { font-size: 11px; color: var(--oy-muted); }
.oy-slip-meta { margin: 10px 0; padding: 6px 0; border-top: 1px dashed var(--oy-border);
  border-bottom: 1px dashed var(--oy-border); }
.oy-slip-to { margin-bottom: 12px; }
.oy-slip table { width: 100%; border-collapse: collapse; }
.oy-slip th { text-align: left; font-weight: 600; font-size: 11px; padding: 3px 8px 3px 0;
  border-bottom: 1px solid var(--oy-border); }
.oy-slip td { padding: 4px 8px 4px 0; vertical-align: top; }
.oy-slip-num { text-align: right; white-space: nowrap; }
.oy-slip-totals { margin-top: 8px; border-top: 1px dashed var(--oy-border); }
.oy-order-state { font-size: 11px; border: 1px solid var(--oy-border); border-radius: 4px; padding: 1px 6px;
  white-space: nowrap; }
@media print {
  body * { visibility: hidden !important; }
  .q-dialog, .q-dialog__inner, .q-dialog__inner > .q-card, .q-scrollarea, .q-scrollarea__container {
    position: static !important; max-height: none !important; height: auto !important;
    overflow: visible !important; }
  .oy-slip, .oy-slip * { visibility: visible !important; color: #000 !important; }
  .oy-slip { position: absolute; left: 0; top: 0; margin: 0; width: 100%; max-width: none; }
}
'''


def postage_cents(text) -> int:
    """Cents of a shipping price typed by a person; empty is free. Raises ValueError when it is not a price."""
    return to_cents((text or '').strip())


def order_title(order: Order) -> str:
    reference = CHANNEL_LABELS.get(order.channel, order.channel)
    return f'{reference} {order.external_id}'.strip()


def orders_page() -> None:
    ui.add_css(SHOP_CSS + ORDERS_CSS)
    profile = load_profile()
    page_header('Pedidos', 'Lo vendido fuera del mostrador: prepararlo, enviarlo y saber por dónde va.')
    if not profile.shop_mode:
        ui.label('Los pedidos son parte del modo tienda. Actívalo en Ajustes → Modo tienda.').classes('oy-sub')
        return

    currency = profile.shop.currency
    games = enabled_games(profile)
    desk = desk_for(account_root(), currency)
    book = desk.dispatch
    state = {'orders': [], 'methods': [], 'loaded': False, 'busy': False, 'view': 'open'}
    holder = ui.element('div')

    def read():
        return book.all(), book.methods()

    async def load() -> None:
        try:
            state['orders'], state['methods'] = await run.io_bound(read)
        except Exception as error:
            with holder:
                ui.notify(shop_failure(error, 'No se pudieron leer los pedidos. Recarga la página.'),
                          type='negative')
            return
        state['loaded'] = True
        listing.refresh()

    async def attempt(action, *args, done: str = '', fallback: str = 'No se pudo guardar. Inténtalo de nuevo.'):
        """Run one change off the UI thread. The result when it went through, None otherwise."""
        if state['busy']:
            return None
        state['busy'] = True
        try:
            result = await run.io_bound(action, *args)
        except Exception as error:
            with holder:
                ui.notify(shop_failure(error, fallback), type='negative', multi_line=True)
            return None
        finally:
            state['busy'] = False
        await load()
        if done:
            with holder:
                ui.notify(done, type='positive')
        return result if result is not None else True

    def buttons(dialog, label: str, action, color: str = 'secondary') -> None:
        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
            ui.button(label, on_click=action).props(f'no-caps color={color}')

    def paper(html: str, width: int = 520) -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style(
                f'min-width: 320px; width: {width}px; max-width: 96vw'):
            ui.html(html, sanitize=False).classes('w-full')
            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Cerrar', on_click=dialog.close).props('flat no-caps color=primary')
                with ui.button(on_click=lambda: ui.run_javascript('window.print()')).props(
                        'no-caps color=secondary'):
                    icon('printer-device')
                    ui.label('Imprimir').classes('q-ml-xs')
        dialog.on('hide', dialog.delete)
        dialog.open()

    # --- steps of one order ------------------------------------------------------------------

    def ship(order: Order, after=None) -> None:
        carriers = list(dict.fromkeys([m.carrier or m.name for m in state['methods']] + (
            [order.carrier] if order.carrier else [])))
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 340px'):
            ui.label(f'Enviar {order.label}').classes('text-h6')
            carrier = ui.select(carriers, value=order.carrier or (carriers[0] if carriers else None),
                                label='Transportista', with_input=True, new_value_mode='add-unique').props(
                'outlined dense').classes('w-full')
            tracking = ui.input('Número de seguimiento', value=order.tracking).props(
                'outlined dense maxlength=80').classes('w-full')
            ui.label('Sin número también vale: el pedido pasa a «Enviado».').classes('oy-sub text-xs')

            async def save() -> None:
                if await attempt(book.ship, order.id, carrier.value or '', tracking.value or '',
                                 done=f'{order.label} enviado.'):
                    dialog.close()
                    if after:
                        after()

            buttons(dialog, 'Enviar', save)
        dialog.on('hide', dialog.delete)
        dialog.open()

    def confirm(title: str, text: str, label: str, action, color: str = 'negative', choice: str = '') -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('max-width: 440px'):
            ui.label(title).classes('text-h6')
            ui.label(text).classes('oy-sub')
            box = ui.checkbox(choice, value=True) if choice else None

            async def go() -> None:
                dialog.close()
                await action(box.value if box else None)

            buttons(dialog, label, go, color)
        dialog.on('hide', dialog.delete)
        dialog.open()

    async def step(order: Order, name: str, after=None) -> None:
        async def finish(result) -> None:
            if result and after:
                after()

        if name in ('paid', 'packed', 'delivered'):
            await finish(await attempt(book.mark, order.id, name, done=f'{order.label}: {ORDER_LABELS[name].lower()}.'))
        elif name == 'ship':
            ship(order, after)
        elif name == 'cancel':
            async def cancel(_) -> None:
                await finish(await attempt(book.cancel, order.id, done=f'{order.label} anulado. Sus cartas vuelven '
                                                                      'al stock.'))
            confirm(f'¿Anular {order.label}?', 'Las cartas del pedido vuelven a sus montones. El cobro, si lo hubo, '
                    'se devuelve donde se cobró: aquí solo se anota.', 'Anular pedido', cancel)
        elif name == 'return':
            async def back(restock) -> None:
                await finish(await attempt(book.returned, order.id, bool(restock),
                                           done=f'{order.label}: devolución anotada.'))
            confirm(f'Devolución de {order.label}', 'Anota que el pedido ha vuelto. El dinero se devuelve donde se '
                    'cobró: aquí solo se anota.', 'Anotar devolución', back, 'secondary',
                    'Las cartas han vuelto en buen estado: devolverlas al stock')

    def detail(order: Order) -> None:
        def money(cents: int) -> str:
            return format_money(cents, order.currency)

        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style(
                'min-width: 340px; width: 620px; max-width: 96vw'):
            with ui.row().classes('w-full items-center gap-2 no-wrap'):
                ui.label(f'Pedido {order.label}').classes('text-h6')
                ui.label(ORDER_LABELS.get(order.status, order.status)).classes('oy-order-state')
                ui.space()
                with ui.button(on_click=dialog.close).props('flat dense round color=primary').tooltip('Cerrar'):
                    icon('x')
            ui.label(' · '.join(part for part in (order_title(order), when(order.created_at)) if part)).classes(
                'oy-sub text-xs')
            with ui.row().classes('w-full gap-6 q-mt-sm'):
                with ui.column().classes('gap-0'):
                    ui.label('Enviar a').classes('oy-sub text-xs')
                    for row in order.address.lines() or [order.customer_name or 'Sin dirección']:
                        ui.label(row).classes('text-sm')
                    if order.email:
                        ui.label(order.email).classes('oy-sub text-xs')
                with ui.column().classes('gap-0'):
                    ui.label('Envío').classes('oy-sub text-xs')
                    ui.label(' · '.join(dict.fromkeys(part for part in (order.shipping_name, order.carrier) if part))
                             or 'Sin método').classes('text-sm')
                    if order.tracking:
                        target = tracking_url(order)
                        if target:
                            ui.link(order.tracking, target, new_tab=True).classes('oy-mono text-sm')
                        else:
                            ui.label(order.tracking).classes('oy-mono text-sm')
                    for label, stamp in (('Cobrado', order.paid_at), ('Preparado', order.packed_at),
                                         ('Enviado', order.shipped_at), ('Entregado', order.delivered_at),
                                         ('Anulado', order.cancelled_at), ('Devuelto', order.returned_at)):
                        if stamp:
                            ui.label(f'{label}: {when(stamp)}').classes('oy-sub text-xs')
            with ui.column().classes('w-full gap-0 q-mt-sm'):
                for line in order.lines:
                    with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-xs no-wrap'):
                        ui.label(f'{line.quantity}×').classes('oy-mono')
                        with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                            ui.label(line.name).classes('text-sm ellipsis w-full')
                            ui.label('Sin enlazar con el stock: no se ha descontado ninguna carta'
                                     if line.unlinked else pile_text(line)).classes('oy-sub text-xs ellipsis w-full')
                        ui.label(money(line.total_cents)).classes('oy-mono')
            with ui.row().classes('w-full justify-end gap-4 q-mt-sm'):
                ui.label(f'Envío {money(order.shipping_cents)}').classes('oy-sub oy-mono')
                ui.label(f'Total {money(order.total_cents)}').classes('oy-mono text-weight-bold')
            if order.note:
                ui.label(order.note).classes('oy-sub text-sm')
            if order.status in ('cancelled', 'returned'):
                ui.label('Las cartas volvieron al stock.' if order.restocked
                         else 'Las cartas no volvieron al stock.').classes('oy-sub text-xs')

            async def again() -> None:
                dialog.close()
                fresh = next((item for item in state['orders'] if item.id == order.id), None)
                if fresh:
                    detail(fresh)

            def reopen() -> None:
                ui.timer(0.05, again, once=True)

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                with ui.button(on_click=lambda: paper(slip_html(order, profile.shop), 620)).props(
                        'flat no-caps color=primary'):
                    icon('delivery-note')
                    ui.label('Albarán').classes('q-ml-xs')
                steps = next_steps(order)
                for name in reversed(steps):
                    first = name == steps[0]
                    with ui.button(on_click=lambda name=name: step(order, name, reopen)).props(
                            'no-caps ' + ('color=secondary' if first else 'flat color=primary')):
                        icon(STEP_ICONS[name])
                        ui.label(STEP_LABELS[name]).classes('q-ml-xs')
        dialog.on('hide', dialog.delete)
        dialog.open()

    # --- a new order by hand -----------------------------------------------------------------

    async def new_order() -> None:
        try:
            items, customers = await run.io_bound(lambda: (desk.inventory.items(games), desk.customers.all()))
        except Exception as error:
            ui.notify(shop_failure(error, 'No se pudo leer el stock. Inténtalo de nuevo.'), type='negative')
            return
        cart: Dict[tuple, List] = {}          # pile key -> [pile, copies]
        methods = {method.id: method for method in state['methods']}

        def money(cents: int) -> str:
            return format_money(cents, currency)

        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style(
                'min-width: 340px; width: 880px; max-width: 96vw'):
            ui.label('Nuevo pedido').classes('text-h6')
            with ui.element('div').classes('oy-pos'):
                with ui.column().classes('w-full gap-2'):
                    query = ui.input(placeholder='Nombre, set o número de la carta').props(
                        'outlined dense clearable debounce=250 autofocus').classes('w-full')

                    @ui.refreshable
                    def results() -> None:
                        if not items:
                            ui.label('No hay cartas en tus colecciones.').classes('oy-sub')
                            return
                        found = search(items, query.value or '', RESULTS) if (query.value or '').strip() else []
                        if not found:
                            ui.label('Escribe para buscar en el stock.' if not (query.value or '').strip()
                                     else 'Nada en stock con ese texto.').classes('oy-sub')
                        for item in found:
                            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-xs no-wrap'):
                                with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                                    ui.label(item.name).classes('text-sm ellipsis w-full')
                                    ui.label(pile_text(item)).classes('oy-sub text-xs ellipsis w-full')
                                ui.label(f'×{item.quantity}').classes('oy-mono oy-sub')
                                ui.label(money(item.unit_cents) if item.unit_cents else 'sin precio').classes(
                                    'oy-mono')
                                with ui.button(on_click=lambda item=item: change(item, 1)).props(
                                        'flat dense round color=primary').tooltip('Añadir al pedido'):
                                    icon('plus')

                    results()
                    query.on_value_change(results.refresh)

                with ui.column().classes('w-full gap-2'):
                    @ui.refreshable
                    def basket() -> None:
                        if not cart:
                            ui.label('El pedido está vacío.').classes('oy-sub')
                        for pile, copies in cart.values():
                            with ui.row().classes('oy-pos-row w-full items-center gap-2 q-py-xs no-wrap'):
                                with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                                    ui.label(pile.name).classes('text-sm ellipsis w-full')
                                    ui.label(pile_text(pile)).classes('oy-sub text-xs ellipsis w-full')
                                with ui.button(on_click=lambda pile=pile: change(pile, -1)).props(
                                        'flat dense round color=primary').tooltip('Una menos'):
                                    icon('minus')
                                ui.label(str(copies)).classes('oy-mono')
                                with ui.button(on_click=lambda pile=pile: change(pile, 1)).props(
                                        'flat dense round color=primary').tooltip('Una más'):
                                    icon('plus')
                                ui.label(money(pile.unit_cents * copies)).classes('oy-mono')
                        goods = sum(pile.unit_cents * copies for pile, copies in cart.values())
                        try:
                            postage = postage_cents(shipping.value)
                        except ValueError:
                            postage = 0
                        ui.label(f'Total {money(goods + postage)}').classes('oy-mono text-weight-bold self-end')

                    def change(pile: SaleLine, by: int) -> None:
                        entry = cart.setdefault(line_key(pile), [pile, 0])
                        if by > 0 and entry[1] >= pile.quantity:
                            ui.notify(f'Solo hay {pile.quantity} en ese montón.', type='warning')
                        else:
                            entry[1] += by
                        if entry[1] <= 0:
                            cart.pop(line_key(pile), None)
                        basket.refresh()

                    who = ui.select(customer_options(customers, {}, currency, None), label='Cliente (opcional)',
                                    with_input=True, clearable=True).props('outlined dense').classes('w-full')
                    name = ui.input('Nombre del destinatario').props('outlined dense maxlength=80').classes('w-full')
                    email = ui.input('Email').props('outlined dense maxlength=120').classes('w-full')
                    line1 = ui.input('Dirección').props('outlined dense maxlength=120').classes('w-full')
                    line2 = ui.input('Piso, puerta…').props('outlined dense maxlength=120').classes('w-full')
                    with ui.row().classes('w-full gap-2 no-wrap'):
                        postcode = ui.input('C. P.').props('outlined dense maxlength=16').style('width: 110px')
                        city = ui.input('Ciudad').props('outlined dense maxlength=80').style('min-width: 0; flex: 1')
                    with ui.row().classes('w-full gap-2 no-wrap'):
                        region = ui.input('Provincia').props('outlined dense maxlength=80').style(
                            'min-width: 0; flex: 1')
                        country = ui.input('País', value=profile.shop.country).props(
                            'outlined dense maxlength=60').style('min-width: 0; flex: 1')
                    with ui.row().classes('w-full gap-2 no-wrap'):
                        method = ui.select({key: m.name for key, m in methods.items()}, label='Envío',
                                           clearable=True).props('outlined dense').style('min-width: 0; flex: 1')
                        shipping = ui.input('Precio del envío', placeholder='0,00').props(
                            f'outlined dense suffix={currency}').style('width: 150px')
                    note = ui.input('Nota').props('outlined dense maxlength=300').classes('w-full')
                    paid = ui.checkbox('Ya está cobrado', value=False)
                    basket()

            def pick_customer() -> None:
                person = next((c for c in customers if c.id == who.value), None)
                if person:
                    name.value, email.value = person.name, person.email

            def pick_method() -> None:
                chosen = methods.get(method.value)
                if chosen:
                    shipping.value = f'{chosen.cents / 100:.2f}'.replace('.', ',')
                basket.refresh()

            who.on_value_change(pick_customer)
            method.on_value_change(pick_method)
            shipping.on_value_change(basket.refresh)

            async def save() -> None:
                if not cart:
                    ui.notify('Añade al menos una carta al pedido.', type='warning')
                    return
                try:
                    postage = postage_cents(shipping.value)
                except ValueError:
                    ui.notify('El precio del envío no es un importe, como 3,90.', type='warning')
                    return
                lines = [OrderLine(**{**pile.model_dump(), 'quantity': copies, 'sku': sku_of(pile)})
                         for pile, copies in cart.values()]
                address = Address(name=name.value or '', line1=line1.value or '', line2=line2.value or '',
                                  postcode=postcode.value or '', city=city.value or '', region=region.value or '',
                                  country=country.value or '')
                created = await attempt(lambda: book.create(
                    lines, channel='manual', customer_name=name.value or '', email=email.value or '',
                    address=address, method=methods.get(method.value), shipping_cents=postage, currency=currency,
                    paid=bool(paid.value), note=note.value or '', customer_id=who.value or None),
                    fallback='No se pudo crear el pedido. Inténtalo de nuevo.')
                if created:
                    dialog.close()
                    with holder:
                        ui.notify(f'Pedido {created.label} creado. Sus cartas ya están apartadas.', type='positive')

            buttons(dialog, 'Crear pedido', save)
        dialog.on('hide', dialog.delete)
        dialog.open()

    # --- orders from a file ------------------------------------------------------------------

    def import_file() -> None:
        found: Dict[str, list] = {'orders': []}
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style(
                'min-width: 340px; width: 520px; max-width: 96vw'):
            ui.label('Importar pedidos de un fichero').classes('text-h6')
            ui.label('Sube el CSV de pedidos que descargas de la tienda (máx. 5 MB). Cada artículo se busca en tu '
                     'stock por SKU o por nombre, set, estado e idioma; lo que no se encuentra queda marcado «sin '
                     'enlazar» y no descuenta cartas.').classes('oy-sub text-sm')
            channel = ui.select({key: CHANNEL_LABELS[key] for key in IMPORT_CHANNELS}, value='cardmarket',
                                label='De dónde viene').props('outlined dense').classes('w-full')
            summary = ui.column().classes('w-full gap-1')

            async def uploaded(event: events.UploadEventArguments) -> None:
                file_obj = getattr(event, 'content', getattr(event, 'file', None))
                summary.clear()
                found['orders'] = []
                try:
                    data = await file_obj.read()
                    found['orders'] = await run.io_bound(parse_orders, data, channel.value)
                except Exception as error:
                    ui.notify(shop_failure(error, 'No se pudo leer el fichero.'), type='negative', multi_line=True)
                    return
                finally:
                    upload.reset()
                with summary:
                    articles = sum(len(order.articles) for order in found['orders'])
                    ui.label(f'{len(found["orders"])} pedidos con {articles} artículos en el fichero.').classes(
                        'text-sm')
                    for order in found['orders'][:5]:
                        ui.label(' · '.join(part for part in (
                            'sin referencia' if order.made_up else order.external_id, order.customer_name,
                            f'{len(order.articles)} artículos') if part)).classes('oy-sub text-xs ellipsis w-full')

            upload = ui.upload(label='CSV de pedidos', auto_upload=True, max_file_size=MAX_BYTES, on_upload=uploaded,
                               on_rejected=lambda: ui.notify('El archivo supera los 5 MB.', type='negative')).props(
                'accept=".csv,.txt,.tsv,text/csv" flat bordered').classes('w-full')

            def bring():
                return bring_in(book, found['orders'], shelves_or_refuse(desk.inventory, games), currency)

            async def save() -> None:
                if not found['orders']:
                    ui.notify('Sube primero un fichero con pedidos.', type='warning')
                    return
                report = await attempt(bring, fallback='No se pudieron importar los pedidos. Inténtalo de nuevo.')
                if not report:
                    return
                dialog.close()
                show_report(report)

            buttons(dialog, 'Importar', save)
        dialog.on('hide', dialog.delete)
        dialog.open()

    def show_report(report, title: str = 'Pedidos importados', notes=()) -> None:
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 320px; max-width: 520px'):
            ui.label(title).classes('text-h6')
            for note in notes:
                ui.label(note).classes('text-sm')
            ui.label(f'{len(report.created)} pedidos nuevos, ya cobrados y con sus cartas apartadas.').classes(
                'text-sm')
            if report.skipped:
                ui.label(f'{report.skipped} ya estaban en la lista y no se han tocado.').classes('oy-sub text-sm')
            if report.unlinked:
                ui.label(f'{report.unlinked} artículos sin enlazar con el stock: revísalos en cada pedido y '
                         'descuenta esas cartas a mano.').classes('oy-sub text-sm')
            for problem in report.failed[:10]:
                ui.label(problem).classes('text-sm text-negative')
            if len(report.failed) > 10:
                ui.label(f'… y {len(report.failed) - 10} más.').classes('oy-sub text-xs')
            with ui.row().classes('w-full justify-end q-mt-md'):
                ui.button('Entendido', on_click=dialog.close).props('no-caps color=secondary')
        dialog.on('hide', dialog.delete)
        dialog.open()

    # --- shipping methods --------------------------------------------------------------------

    def edit_methods() -> None:
        rows: List[dict] = [{'id': m.id, 'name': m.name, 'carrier': m.carrier,
                             'cents': f'{m.cents / 100:.2f}'.replace('.', ',') if m.cents else '',
                             'tracking_url': m.tracking_url} for m in state['methods']]
        with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style(
                'min-width: 340px; width: 760px; max-width: 96vw'):
            ui.label('Métodos de envío').classes('text-h6')
            ui.label('El enlace de seguimiento empieza por https:// y lleva {code} donde va el número. '
                     'Los que vienen de serie son orientativos: compruébalos con un envío real.').classes(
                'oy-sub text-sm')

            @ui.refreshable
            def table() -> None:
                for row in rows:
                    with ui.row().classes('w-full items-center gap-2 no-wrap'):
                        ui.input('Nombre').bind_value(row, 'name').props('outlined dense maxlength=60').style(
                            'width: 150px')
                        ui.input('Transportista').bind_value(row, 'carrier').props(
                            'outlined dense maxlength=60').style('width: 130px')
                        ui.input('Precio', placeholder='0,00').bind_value(row, 'cents').props(
                            'outlined dense').style('width: 90px')
                        ui.input('Enlace de seguimiento').bind_value(row, 'tracking_url').props(
                            'outlined dense maxlength=300').style('min-width: 0; flex: 1')
                        with ui.button(on_click=lambda row=row: (rows.remove(row), table.refresh())).props(
                                'flat dense round color=primary').tooltip('Quitar'):
                            icon('trash')

            with ui.scroll_area().style('height: min(50vh, 380px)'):
                table()
            with ui.button(on_click=lambda: (rows.append(
                    {'id': '', 'name': '', 'carrier': '', 'cents': '', 'tracking_url': ''}), table.refresh())).props(
                    'flat no-caps color=primary'):
                icon('plus')
                ui.label('Añadir método').classes('q-ml-xs')

            async def save() -> None:
                methods = []
                try:
                    for row in rows:
                        fields = {'name': row['name'] or '', 'carrier': row['carrier'] or '',
                                  'cents': postage_cents(row['cents']), 'tracking_url': row['tracking_url'] or ''}
                        methods.append(ShippingMethod(id=row['id'], **fields) if row['id']
                                       else ShippingMethod(**fields))
                except ValueError:
                    ui.notify('Algún precio no es un importe, como 3,90.', type='warning')
                    return
                if await attempt(book.save_methods, methods, done='Métodos de envío guardados.'):
                    dialog.close()

            buttons(dialog, 'Guardar', save)
        dialog.on('hide', dialog.delete)
        dialog.open()

    # --- the list ----------------------------------------------------------------------------

    def picks() -> None:
        waiting = [order for order in state['orders'] if order.status == 'paid']
        paper(picks_html(pick_list(waiting)), 720)

    with ui.row().classes('w-full items-center gap-2 q-mt-md'):
        with ui.button(on_click=new_order).props('no-caps color=secondary'):
            icon('plus')
            ui.label('Nuevo pedido').classes('q-ml-xs')
        with ui.button(on_click=import_file).props('flat no-caps color=primary'):
            icon('upload')
            ui.label('Importar CSV').classes('q-ml-xs')
        with ui.button(on_click=picks).props('flat no-caps color=primary').tooltip(
                'Las cartas de los pedidos por preparar, en el orden en que se recogen'):
            icon('clipboard')
            ui.label('Hoja de recogida').classes('q-ml-xs')
        with ui.button(on_click=edit_methods).props('flat no-caps color=primary'):
            icon('truck-delivery')
            ui.label('Métodos de envío').classes('q-ml-xs')
        extras = ui.row().classes('items-center gap-2')
    with ui.row().classes('w-full items-center gap-2 q-mt-sm no-wrap'):
        query = ui.input(placeholder='Número, referencia, cliente o carta').props(
            'outlined dense clearable debounce=250').style('min-width: 0; flex: 1')
        view = ui.toggle(VIEWS, value='open').props('no-caps unelevated toggle-color=secondary')

    @ui.refreshable
    def listing() -> None:
        if not state['loaded']:
            ui.label('Cargando pedidos…').classes('oy-sub')
            return
        if not state['orders']:
            ui.label('Todavía no hay pedidos. Crea uno a mano o importa el CSV de tu tienda.').classes('oy-sub')
            return
        found = matching(in_view(state['orders'], view.value), query.value or '')
        if not found:
            ui.label('Ningún pedido aquí con ese texto.').classes('oy-sub')
            return
        for order in found[:SHOWN]:
            steps = next_steps(order)
            with ui.row().classes('oy-pos-row w-full items-center gap-3 q-py-sm no-wrap'):
                with ui.column().classes('gap-0').style('min-width: 0; flex: 1'):
                    with ui.row().classes('items-center gap-2 no-wrap'):
                        ui.label(order.label).classes('oy-mono text-sm')
                        ui.label(ORDER_LABELS.get(order.status, order.status)).classes('oy-order-state')
                        if order.unlinked:
                            ui.label(f'{order.unlinked} sin enlazar').classes('oy-order-state text-negative')
                    ui.label(' · '.join(part for part in (
                        order_title(order), order.customer_name, f'{order.units} cartas', when(order.created_at))
                        if part)).classes('oy-sub text-xs ellipsis w-full')
                ui.label(format_money(order.total_cents, order.currency)).classes('oy-mono')
                if steps and steps[0] != 'return':
                    with ui.button(on_click=lambda o=order, s=steps[0]: step(o, s)).props(
                            'flat dense round color=primary').tooltip(STEP_LABELS[steps[0]]):
                        icon(STEP_ICONS[steps[0]])
                with ui.button(on_click=lambda o=order: paper(slip_html(o, profile.shop), 620)).props(
                        'flat dense round color=primary').tooltip('Albarán'):
                    icon('delivery-note')
                with ui.button(on_click=lambda o=order: detail(o)).props('flat dense round color=primary').tooltip(
                        'Ver el pedido'):
                    icon('eye')
        if len(found) > SHOWN:
            ui.label(f'Se muestran {SHOWN} pedidos. Escribe más para afinar.').classes('oy-sub text-xs')

    listing()
    query.on_value_change(listing.refresh)
    view.on_value_change(listing.refresh)

    # --- the shop's own online shops -----------------------------------------------------------

    channels = ChannelSettings(desk.root)

    def round_with(channel: str):
        return sync_channel(channels, channel, book, lambda: desk.inventory.items(games, strict=True), currency)

    async def sync_now(channel: str) -> None:
        report = await attempt(round_with, channel,
                               fallback='No se pudo sincronizar con la tienda. Inténtalo de nuevo.')
        if report:
            show_report(report.orders, sync_label(channel), notes=sync_lines(report) + [
                'Al enviar un pedido aquí, márcalo también como enviado en tu tienda.'])

    async def start() -> None:
        await load()
        try:
            connected = await run.io_bound(channels.summary)
            waiting = await run.io_bound(due_channels, channels)
        except Exception as error:
            shop_failure(error, '')
            return
        with extras:
            for channel in CHANNELS:
                if channel in connected:
                    with ui.button(on_click=lambda c=channel: sync_now(c)).props('flat no-caps color=primary'):
                        icon('refresh-cw')
                        ui.label(sync_label(channel)).classes('q-ml-xs')
        for channel in waiting:
            # On its own and without taking the page's turn: the desk stays usable while the shop answers.
            try:
                report = await run.io_bound(round_with, channel)
            except Exception as error:
                with holder:
                    ui.notify(shop_failure(error, f'No se pudo sincronizar con {CHANNEL_LABELS[channel]}.'),
                              type='warning', multi_line=True)
                continue
            if report.orders.created:
                await load()
            if report.orders.created or report.orders.failed or report.push_error:
                show_report(report.orders, sync_label(channel), notes=sync_lines(report))

    ui.timer(0.1, start, once=True)
