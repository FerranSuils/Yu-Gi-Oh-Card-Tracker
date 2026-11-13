"""Settings section for the shop's own online shops: connect Shopify or WooCommerce, and get the product
files that put the stock there in the first place. Keys go in and never come back out."""

from __future__ import annotations

import logging
from typing import List, Optional

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.account_scope import account_root
from src.core.order_models import CHANNEL_LABELS
from src.services.orders.channels import CHANNELS, ChannelSettings, sellable, shopify_csv, woocommerce_csv
from src.services.orders.sync import connect
from src.services.shop.desk import desk_for
from src.ui.icons import icon
from src.ui.shop_common import shop_failure, when

logger = logging.getLogger(__name__)

ICONS = ('store', 'link', 'download', 'ban')
BETA = ('Función en pruebas: la conexión está comprobada con respuestas simuladas, todavía no contra una tienda '
        'real. Empieza con pocos productos y revisa el stock en tu tienda tras la primera sincronización.')
LIMITS = ('Cardmarket y TCGplayer no dan acceso nuevo a su API: con ellos se trabaja por fichero (exportar en CSV '
          'Suite, importar pedidos en Pedidos).')
FIELDS = {
    'shopify': (('Dominio', 'tu-tienda.myshopify.com', False),
                ('Token de acceso de la API Admin', 'shpat_…', True)),
    'woocommerce': (('Dirección de la tienda', 'https://tu-tienda.com', False),
                    ('Clave de cliente', 'ck_…', True), ('Clave secreta', 'cs_…', True)),
}
HELP = {
    'shopify': 'En Shopify: Configuración → Apps → Desarrollar apps. Permisos: leer pedidos, leer productos, '
               'leer y escribir inventario.',
    'woocommerce': 'En WooCommerce: Ajustes → Avanzado → API REST → Añadir clave, con permiso de lectura y '
                   'escritura. Solo productos simples con SKU.',
}


def channel_status_text(entry: Optional[dict]) -> str:
    """What the settings page says about one connection. Never a key: only its last four characters."""
    if not entry:
        return 'Sin conectar'
    text = f"Conectada · {entry.get('where', '')} · clave ····{entry.get('last4', '')}"
    synced = entry.get('synced_at')
    return text + (f' · última sincronización {when(synced)}' if synced else ' · sin sincronizar todavía')


def sync_label(channel: str) -> str:
    return f'Sincronizar {CHANNEL_LABELS.get(channel, channel)}'


def sync_lines(report) -> List[str]:
    """What one round did to the stock in the online shop, for the person at the screen."""
    more = ['La tienda tiene más pedidos pendientes de los que se leen de una vez: envía estos y vuelve a '
            'sincronizar para traer el resto.'] if getattr(report, 'truncated', False) else []
    if report.push_error:
        return more + [
            f'No se pudo enviar el stock: {report.push_error} Se reintentará en la próxima sincronización.']
    lines = []
    if report.updated:
        products = 'producto' if report.updated == 1 else 'productos'
        lines.append(f'Stock actualizado en {report.updated} {products} de la tienda.')
    if report.missing:
        lines.append(f'{report.missing} pilas con stock no tienen producto con su SKU en la tienda: súbelas con '
                     'el fichero de productos de Ajustes → Tiendas online.')
    return more + (lines or ['El stock de la tienda ya estaba al día.'])


def render_channels_section() -> None:
    profile = load_profile()
    if not profile.shop_mode:
        return
    root = account_root()
    settings = ChannelSettings(root)
    state = {'summary': {}, 'loaded': False, 'busy': False}
    with ui.card().classes('w-full q-pa-lg q-mt-md'):
        with ui.row().classes('items-center gap-2'):
            icon('store', 20)
            ui.label('Tiendas online').classes('text-h6')
        ui.label('Conecta tu propia tienda: sus pedidos pagados entran en Pedidos y el stock que te queda se '
                 'envía de vuelta, como mucho cada 10 minutos mientras tengas Pedidos abierto. Marcar un pedido '
                 'como enviado aquí no lo marca en la tienda.').classes('text-caption text-grey-5')
        ui.label(BETA).classes('text-caption text-warning')
        ui.label(LIMITS).classes('text-caption text-grey-5 q-mb-md')
        holder = ui.element('div')

        async def work(action, *args, fallback: str):
            """One change off the UI thread; the result when it went through, None otherwise."""
            if state['busy']:
                return None
            state['busy'] = True
            try:
                result = await run.io_bound(action, *args)
                state['summary'] = await run.io_bound(settings.summary)
            except Exception as error:
                with holder:
                    ui.notify(shop_failure(error, fallback), type='negative', multi_line=True)
                return None
            finally:
                state['busy'] = False
            body.refresh()
            return result if result is not None else True

        async def join(channel: str, inputs: list) -> None:
            values = [(field.value or '').strip() for field in inputs]
            if not all(values):
                ui.notify('Rellena todos los campos.', type='warning')
                return
            name = await work(connect, settings, channel, *values,
                              fallback='No se pudo conectar la tienda. Inténtalo de nuevo.')
            if name:
                with holder:
                    ui.notify(f'{CHANNEL_LABELS[channel]} conectada.', type='positive')

        def leave(channel: str) -> None:
            with holder, ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('min-width: 320px'):
                ui.label(f'Desconectar {CHANNEL_LABELS[channel]}').classes('text-h6')
                ui.label('Se borran las claves guardadas. Los pedidos que ya entraron se quedan; el stock de la '
                         'tienda deja de actualizarse.').classes('oy-sub text-sm')

                async def confirm() -> None:
                    if await work(settings.forget, channel, fallback='No se pudo desconectar. Inténtalo de nuevo.'):
                        dialog.close()
                        with holder:
                            ui.notify(f'{CHANNEL_LABELS[channel]} desconectada.', type='positive')

                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Volver', on_click=dialog.close).props('flat no-caps color=primary')
                    ui.button('Desconectar', on_click=confirm).props('no-caps color=negative')
            dialog.on('hide', dialog.delete)
            dialog.open()

        async def products(channel: str) -> None:
            def build() -> tuple:
                items, left_out = sellable(
                    desk_for(root, profile.shop.currency).inventory.items(enabled_games(profile)))
                data = shopify_csv(items, vendor=profile.shop.name) if channel == 'shopify' else woocommerce_csv(items)
                return data, left_out

            try:
                data, left_out = await run.io_bound(build)
            except Exception as error:
                ui.notify(shop_failure(error, 'No se pudo preparar el fichero.'), type='negative')
                return
            ui.download.content(data, f'productos-{channel}.csv', 'text/csv')
            if left_out:
                piles = '1 pila sin precio no está' if left_out == 1 else f'{left_out} pilas sin precio no están'
                ui.notify(f'{piles} en el fichero: ponles precio y descárgalo de nuevo.', type='warning')

        @ui.refreshable
        def body() -> None:
            if not state['loaded']:
                ui.label('Cargando…').classes('text-caption text-grey-5')
                return
            for channel in CHANNELS:
                entry = state['summary'].get(channel)
                with ui.column().classes('w-full gap-2 q-mt-md'):
                    ui.label(CHANNEL_LABELS[channel]).classes('text-subtitle1')
                    ui.label(channel_status_text(entry)).classes('oy-mono text-sm')
                    if not entry:
                        ui.label(HELP[channel]).classes('text-caption text-grey-5')
                        inputs = [ui.input(label, placeholder=hint, password=secret).props(
                            'outlined dense maxlength=300 autocomplete=off').classes('w-full')
                            for label, hint, secret in FIELDS[channel]]
                    with ui.row().classes('w-full gap-2'):
                        if entry:
                            with ui.button(on_click=lambda c=channel: leave(c)).props(
                                    'no-caps outline color=primary'):
                                icon('ban')
                                ui.label('Desconectar').classes('q-ml-xs')
                        else:
                            with ui.button(on_click=lambda c=channel, i=inputs: join(c, i)).props(
                                    'no-caps color=secondary'):
                                icon('link')
                                ui.label('Conectar').classes('q-ml-xs')
                        with ui.button(on_click=lambda c=channel: products(c)).props(
                                'flat no-caps color=primary').tooltip(
                                'Tu stock como fichero de importación de productos, con el SKU que luego enlaza '
                                'pedidos y stock'):
                            icon('download')
                            ui.label('Fichero de productos').classes('q-ml-xs')

        body()

        async def load() -> None:
            try:
                state['summary'] = await run.io_bound(settings.summary)
            except Exception as failure:
                logger.error('Canales: no se pudieron leer: %s', type(failure).__name__)
            state['loaded'] = True
            body.refresh()

        ui.timer(0.1, load, once=True)
