"""Settings sections of the shop desk: what the shop pays for cards, and its public kiosk."""

from __future__ import annotations

import logging

from nicegui import run, ui

from src.core.account_profile import load_profile, save_profile
from src.core.account_scope import account_root
from src.core.sales_models import to_cents
from src.services.shop import api_keys, kiosk, shop_map
from src.ui.icons import icon

logger = logging.getLogger(__name__)

ICONS = ('hand-coin', 'shopping-list', 'copy', 'refresh-cw', 'ban', 'coin', 'key-round', 'map-pin')


def plain(cents: int) -> str:
    return f'{cents / 100:.2f}'.replace('.', ',')


def kiosk_url(base: str, token: str) -> str:
    return f'{base.rstrip("/")}/kiosko/{token}'


def render_buylist_section() -> None:
    profile = load_profile()
    if not profile.shop_mode:
        return
    rules = profile.buylist
    with ui.card().classes('w-full q-pa-lg q-mt-md'):
        with ui.row().classes('items-center gap-2'):
            icon('hand-coin', 20)
            ui.label('Compras a clientes').classes('text-h6')
        ui.label('Qué parte del precio de mercado pagas cuando compras cartas. Se aplica en Compras y en lo '
                 'que el kiosko enseña a tus clientes.').classes('text-caption text-grey-5 q-mb-md')
        with ui.grid(columns=1).classes('w-full gap-3 sm:grid-cols-3'):
            cash = ui.number('En efectivo', value=rules.cash_percent, min=0, max=100, step=1, format='%g').props(
                'outlined suffix=%')
            credit = ui.number('En saldo de tienda', value=rules.credit_percent, min=0, max=100, step=1,
                               format='%g').props('outlined suffix=%')
            floor = ui.input('Oferta mínima', value=plain(rules.min_offer_cents)).props(
                f'outlined suffix={profile.shop.currency}')
        ui.label('Las cartas cuya oferta queda por debajo de la mínima no se compran.').classes(
            'text-caption text-grey-5')
        error = ui.label('').classes('oy-form-error text-negative text-sm')

        async def save() -> None:
            if cash.value is None or credit.value is None or not (0 <= cash.value <= 100 and 0 <= credit.value <= 100):
                error.set_text('Los porcentajes van de 0 a 100.')
                return
            try:
                cents = to_cents((floor.value or '').strip() or '0')
            except ValueError:
                cents = -1
            if cents < 0:
                error.set_text('La oferta mínima es un importe, como 0,25.')
                return
            error.set_text('')
            current = load_profile()
            current.buylist = current.buylist.model_copy(update={
                'cash_percent': float(cash.value), 'credit_percent': float(credit.value), 'min_offer_cents': cents})
            await run.io_bound(save_profile, current, account_root())
            ui.notify('Compras guardadas.', type='positive')

        ui.button('Guardar compras', on_click=save).props('color=secondary').classes('w-full q-mt-md')


def render_loyalty_section() -> None:
    from src.core.shop_models import LoyaltyRules
    from src.services.shop.customers import CustomerError
    from src.services.shop.loyalty import Loyalty

    profile = load_profile()
    if not profile.shop_mode:
        return
    currency = profile.shop.currency
    loyalty = Loyalty(account_root(), None, currency)
    with ui.card().classes('w-full q-pa-lg q-mt-md'):
        with ui.row().classes('items-center gap-2'):
            icon('coin', 20)
            ui.label('Puntos').classes('text-h6')
        ui.label('Tus clientes ganan puntos al comprar y los canjean por saldo de tienda desde su ficha. '
                 'Lo que se paga con saldo de tienda no da puntos, y una devolución quita los que dio.').classes(
            'text-caption text-grey-5 q-mb-md')
        try:
            rules = loyalty.rules()
        except CustomerError as failure:
            ui.label(str(failure)).classes('text-negative text-sm')
            return
        enabled = ui.switch('Dar puntos', value=rules.enabled)
        with ui.grid(columns=1).classes('w-full gap-3 sm:grid-cols-3'):
            rate = ui.number(f'Puntos por cada {currency}', value=rules.points_per_unit, min=0, max=1000, step=1,
                             format='%g').props('outlined')
            block = ui.number('Puntos para canjear', value=rules.redeem_points, min=1, step=1, format='%d').props(
                'outlined')
            worth = ui.input('Valen de saldo', value=plain(rules.redeem_cents)).props(f'outlined suffix={currency}')
        error = ui.label('').classes('oy-form-error text-negative text-sm')

        async def save() -> None:
            try:
                cents = to_cents((worth.value or '').strip() or '0')
            except ValueError:
                cents = 0
            try:
                fresh = LoyaltyRules(enabled=bool(enabled.value), points_per_unit=float(rate.value),
                                     redeem_points=int(block.value), redeem_cents=cents)
            except (TypeError, ValueError):
                error.set_text('Revisa los números: puntos de 0 a 1000 por unidad, y un canje de al menos '
                               '1 punto por 0,01.')
                return
            error.set_text('')
            try:
                await run.io_bound(loyalty.save_rules, fresh)
            except Exception as failure:
                logger.error('Puntos: no se pudieron guardar: %s', type(failure).__name__)
                ui.notify('No se pudieron guardar los puntos. Inténtalo de nuevo.', type='negative')
                return
            ui.notify('Puntos guardados.', type='positive')

        ui.button('Guardar puntos', on_click=save).props('color=secondary').classes('w-full q-mt-md')


def render_kiosk_section() -> None:
    from src.ui.pos import success_url

    if not load_profile().shop_mode:
        return
    root = account_root()
    request = ui.context.client.request
    base = success_url(request.headers, request.base_url).removesuffix('/tpv/pagado')
    state = {'token': None, 'loaded': False, 'busy': False}
    with ui.card().classes('w-full q-pa-lg q-mt-md'):
        with ui.row().classes('items-center gap-2'):
            icon('shopping-list', 20)
            ui.label('Kiosko').classes('text-h6')
        ui.label('Una pantalla pública para una tablet en la tienda: tus clientes ven el stock con precio, '
                 'envían una lista al mostrador y consultan lo que pagas por sus cartas. Quien tenga el '
                 'enlace puede verla; no enseña clientes, saldos ni ventas.').classes(
            'text-caption text-grey-5 q-mb-md')

        async def change(action, done: str) -> None:
            if state['busy']:
                return
            state['busy'] = True
            try:
                state['token'] = await run.io_bound(action, root)
            except Exception as failure:
                logger.error('Kiosko: no se pudo cambiar: %s', type(failure).__name__)
                ui.notify('No se pudo cambiar el kiosko. Inténtalo de nuevo.', type='negative')
                return
            finally:
                state['busy'] = False
            body.refresh()
            ui.notify(done, type='positive')

        def copy() -> None:
            ui.clipboard.write(kiosk_url(base, state['token']))
            ui.notify('Enlace copiado.', type='positive')

        @ui.refreshable
        def body() -> None:
            if not state['loaded']:
                ui.label('Cargando…').classes('text-caption text-grey-5')
                return
            if not state['token']:
                ui.label('El kiosko está apagado.').classes('oy-sub')
                ui.button('Encender el kiosko', on_click=lambda: change(kiosk.enable, 'Kiosko encendido.')).props(
                    'color=secondary').classes('w-full q-mt-md')
                return
            ui.input('Enlace del kiosko', value=kiosk_url(base, state['token'])).props(
                'outlined readonly').classes('w-full')
            with ui.row().classes('w-full gap-2 q-mt-md'):
                with ui.button(on_click=copy).props('no-caps color=secondary'):
                    icon('copy')
                    ui.label('Copiar enlace').classes('q-ml-xs')
                with ui.button(on_click=lambda: change(kiosk.enable, 'Enlace nuevo. El anterior ya no abre.')
                               ).props('no-caps outline color=primary'):
                    icon('refresh-cw')
                    ui.label('Cambiar enlace').classes('q-ml-xs')
                with ui.button(on_click=lambda: change(kiosk.disable, 'Kiosko apagado.')).props(
                        'no-caps outline color=primary'):
                    icon('ban')
                    ui.label('Apagar').classes('q-ml-xs')

        body()

        async def load() -> None:
            try:
                state['token'] = await run.io_bound(kiosk.token_of, root)
            except Exception as failure:
                logger.error('Kiosko: no se pudo leer: %s', type(failure).__name__)
            state['loaded'] = True
            body.refresh()

        ui.timer(0.1, load, once=True)


def key_hint(tail) -> str:
    """How a key is shown once it has been put away: never more than its last four characters."""
    return f'oy_…{tail}' if tail else ''


def render_api_section() -> None:
    from src.ui.pos import success_url

    if not load_profile().shop_mode:
        return
    root = account_root()
    request = ui.context.client.request
    base = success_url(request.headers, request.base_url).removesuffix('/tpv/pagado')
    state = {'hint': None, 'fresh': None, 'loaded': False, 'busy': False}
    with ui.card().classes('w-full q-pa-lg q-mt-md'):
        with ui.row().classes('items-center gap-2'):
            icon('key-round', 20)
            ui.label('API de lectura').classes('text-h6')
        ui.label('Para que tu web o tus scripts lean el stock con precio, los pedidos y las ventas de la tienda. '
                 'Solo lee: no cambia nada, y no entrega nombres, correos ni direcciones de clientes. '
                 'Máximo 60 peticiones por minuto.').classes('text-caption text-grey-5 q-mb-md')

        async def change(action, done: str) -> None:
            if state['busy']:
                return
            state['busy'] = True
            try:
                state['fresh'] = await run.io_bound(action, root)
                state['hint'] = await run.io_bound(api_keys.hint, root)
            except Exception as failure:
                logger.error('API: no se pudo cambiar la clave: %s', type(failure).__name__)
                ui.notify('No se pudo cambiar la clave. Inténtalo de nuevo.', type='negative')
                return
            finally:
                state['busy'] = False
            body.refresh()
            ui.notify(done, type='positive')

        def copy() -> None:
            ui.clipboard.write(state['fresh'])
            ui.notify('Clave copiada.', type='positive')

        @ui.refreshable
        def body() -> None:
            if not state['loaded']:
                ui.label('Cargando…').classes('text-caption text-grey-5')
                return
            if state['hint'] is None:
                ui.label('No hay ninguna clave.').classes('oy-sub')
                ui.button('Crear clave', on_click=lambda: change(api_keys.create, 'Clave creada.')).props(
                    'color=secondary').classes('w-full q-mt-md')
                return
            if state['fresh']:
                ui.input('Tu clave', value=state['fresh']).props('outlined readonly').classes('w-full')
                ui.label('Cópiala ahora: no se vuelve a mostrar. Aquí solo se guarda su huella.').classes(
                    'text-caption text-warning')
            else:
                ui.label(f'Clave activa: {key_hint(state["hint"]) or "oy_…"}').classes('oy-sub')
            ui.label(f'GET {base.rstrip("/")}/api/v1/shop/stock · /orders · /sales?month=AAAA-MM  —  '
                     'cabecera «Authorization: Bearer TU_CLAVE»').classes('text-caption text-grey-5 q-mt-sm')
            with ui.row().classes('w-full gap-2 q-mt-md'):
                if state['fresh']:
                    with ui.button(on_click=copy).props('no-caps color=secondary'):
                        icon('copy')
                        ui.label('Copiar clave').classes('q-ml-xs')
                with ui.button(on_click=lambda: change(api_keys.create, 'Clave nueva. La anterior ya no sirve.')
                               ).props('no-caps outline color=primary'):
                    icon('refresh-cw')
                    ui.label('Cambiar clave').classes('q-ml-xs')
                with ui.button(on_click=lambda: change(api_keys.revoke, 'Clave anulada.')).props(
                        'no-caps outline color=primary'):
                    icon('ban')
                    ui.label('Anular').classes('q-ml-xs')

        body()

        async def load() -> None:
            try:
                state['hint'] = await run.io_bound(api_keys.hint, root)
            except Exception as failure:
                logger.error('API: no se pudo leer la clave: %s', type(failure).__name__)
            state['loaded'] = True
            body.refresh()

        ui.timer(0.1, load, once=True)


def map_status(pin) -> str:
    """One line saying whether, and as what, the shop is on the public map."""
    if pin is None:
        return 'Tu tienda no aparece en el mapa.'
    place = ', '.join(part for part in (pin.address, pin.city) if part)
    return f'En el mapa como «{pin.name}»{", " + place if place else ""}.'


def render_map_section() -> None:
    if not load_profile().shop_mode:
        return
    root = account_root()
    state = {'pin': None, 'loaded': False, 'busy': False}
    with ui.card().classes('w-full q-pa-lg q-mt-md'):
        with ui.row().classes('items-center gap-2'):
            icon('map-pin', 20)
            ui.label('Aparecer en el mapa').classes('text-h6')
        ui.label('El mapa de tiendas es público: cualquiera ve el nombre y la dirección de tu tienda y, si tienes '
                 'el kiosko abierto, un enlace a él. No se publica el correo. Se usa la dirección de «Datos de la '
                 'tienda»; si la cambias, pulsa «Actualizar».').classes('text-caption text-grey-5 q-mb-md')

        async def publish() -> None:
            if state['busy']:
                return
            state['busy'] = True
            try:
                state['pin'] = await run.io_bound(lambda: shop_map.publish(root, load_profile(root)))
            except shop_map.MapError as failure:   # written for the person: say it as it is
                ui.notify(str(failure), type='warning')
                return
            except Exception as failure:
                logger.error('Mapa: no se pudo publicar: %s', type(failure).__name__)
                ui.notify('No se pudo publicar la tienda en el mapa. Inténtalo de nuevo.', type='negative')
                return
            finally:
                state['busy'] = False
            body.refresh()
            ui.notify('Tu tienda está en el mapa.', type='positive')

        async def remove() -> None:
            if state['busy']:
                return
            state['busy'] = True
            try:
                await run.io_bound(shop_map.unpublish, root)
                state['pin'] = None
            except Exception as failure:
                logger.error('Mapa: no se pudo quitar: %s', type(failure).__name__)
                ui.notify('No se pudo quitar la tienda del mapa. Inténtalo de nuevo.', type='negative')
                return
            finally:
                state['busy'] = False
            body.refresh()
            ui.notify('Tu tienda ya no aparece en el mapa.', type='positive')

        @ui.refreshable
        def body() -> None:
            if not state['loaded']:
                ui.label('Cargando…').classes('text-caption text-grey-5')
                return
            ui.label(map_status(state['pin'])).classes('oy-sub')
            with ui.row().classes('w-full items-center gap-2 q-mt-md'):
                if state['pin'] is None:
                    ui.button('Aparecer en el mapa', on_click=publish).props('no-caps color=secondary')
                else:
                    with ui.button(on_click=publish).props('no-caps outline color=primary'):
                        icon('refresh-cw')
                        ui.label('Actualizar').classes('q-ml-xs')
                    with ui.button(on_click=remove).props('no-caps outline color=primary'):
                        icon('ban')
                        ui.label('Quitar del mapa').classes('q-ml-xs')
                ui.link('Ver el mapa', '/mapa', new_tab=True)

        body()

        async def load() -> None:
            try:
                state['pin'] = await run.io_bound(shop_map.published, root)
            except Exception as failure:
                logger.error('Mapa: no se pudo leer: %s', type(failure).__name__)
            state['loaded'] = True
            body.refresh()

        ui.timer(0.1, load, once=True)
