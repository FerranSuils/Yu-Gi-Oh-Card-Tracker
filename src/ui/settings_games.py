"""Settings sections for the multi-game catalogs and the shop profile."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from nicegui import run, ui

from src.core.account_scope import account_root, current_account_name, uses_private_storage
from src.core.account_profile import enabled_games, load_profile, save_profile
from src.services.catalog import PROVIDERS
from src.ui.icons import icon

CURRENCIES = ['EUR', 'USD', 'GBP']
logger = logging.getLogger(__name__)
_EMAIL = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')


def catalog_status_text(info: dict) -> str:
    count = int(info.get('count') or 0)
    if not count:
        return 'Sin descargar'
    text = f"{count:,}".replace(',', '.') + ' cartas'
    if info.get('updated_at'):
        try:
            text += ' · actualizado ' + datetime.fromisoformat(info['updated_at']).strftime('%d/%m/%Y')
        except ValueError:
            pass
    return text


def valid_email(value: str) -> bool:
    value = (value or '').strip()
    return not value or bool(_EMAIL.fullmatch(value))


def can_manage_catalogs() -> bool:
    """Catalogs are shared by every account, so only the primary account may re-download them."""
    return not uses_private_storage(current_account_name())


def render_games_section() -> None:
    with ui.card().classes('w-full q-pa-lg q-mt-md'):
        ui.label('Juegos').classes('text-h6')
        ui.label('Activa los juegos de cartas que quieres llevar. Cada catálogo se descarga una vez.').classes(
            'text-caption text-grey-5 q-mb-md')
        profile = load_profile()
        active = set(enabled_games(profile))
        manager = can_manage_catalogs()

        async def toggle(game: str, value: bool) -> None:
            current = load_profile()
            games = [g for g in enabled_games(current) if g != game]
            if value:
                games.append(game)
            current.enabled_games = games
            await run.io_bound(save_profile, current, account_root())
            ui.notify(('Activado: ' if value else 'Desactivado: ') + PROVIDERS[game].display_name)

        for game, provider in PROVIDERS.items():
            with ui.row().classes('w-full items-center gap-4 q-py-sm oy-game-row'):
                switch = ui.switch(provider.display_name, value=game in active)
                if game == 'yugioh':
                    # Its card database is managed in "Data management" below.
                    switch.props('disable')
                    ui.label('Siempre activo · su base se gestiona en Data management').classes(
                        'text-caption text-grey-6')
                    continue
                else:
                    switch.on_value_change(lambda e, game=game: toggle(game, e.value))
                status = ui.label(catalog_status_text(provider.store.info())).classes('text-caption text-grey-6')
                ui.space()

                if not manager:
                    if not provider.is_available():
                        status.set_text('Aún no disponible: lo descarga el administrador.')
                    continue
                label = 'Actualizar catálogo' if provider.is_available() else 'Descargar catálogo'
                with ui.button().props('flat no-caps color=primary') as button:
                    icon('download')
                    ui.label(label).classes('q-ml-xs')

                async def refresh(provider=provider, status=status, target=button) -> None:
                    target.disable()
                    note = ui.notification(f'Descargando {provider.display_name}…', type='info', spinner=True,
                                           timeout=None)
                    try:
                        count = await run.io_bound(provider.refresh)
                        ui.notify(f"{provider.display_name}: {count:,} cartas".replace(',', '.'), type='positive')
                    except Exception as error:  # network and format errors are shown, the old catalog stays
                        ui.notify(f'No se pudo descargar {provider.display_name}: {error}', type='negative')
                    finally:
                        note.dismiss()
                        target.enable()
                        status.set_text(catalog_status_text(provider.store.info()))

                button.on_click(refresh)


def render_shop_section() -> None:
    profile = load_profile()
    with ui.card().classes('w-full q-pa-lg q-mt-md'):
        with ui.row().classes('items-center gap-2'):
            icon('store', 20)
            ui.label('Modo tienda').classes('text-h6')
        ui.label('Para tiendas de cartas: activa el punto de venta, la buylist y la consigna a medida que '
                 'estén disponibles. Todo es gratis.').classes('text-caption text-grey-5 q-mb-md')
        shop_mode = ui.switch('Esta cuenta es una tienda', value=profile.shop_mode)
        with ui.grid(columns=1).classes('w-full gap-3 sm:grid-cols-2 q-mt-sm'):
            name = ui.input('Nombre de la tienda', value=profile.shop.name).props('outlined maxlength=120')
            email = ui.input('Email de contacto', value=profile.shop.email).props('outlined type=email maxlength=200')
            address = ui.input('Dirección', value=profile.shop.address).props('outlined maxlength=200')
            city = ui.input('Ciudad', value=profile.shop.city).props('outlined maxlength=120')
            country = ui.input('País', value=profile.shop.country).props('outlined maxlength=120')
            currency = ui.select(CURRENCIES, label='Moneda', value=profile.shop.currency
                                 if profile.shop.currency in CURRENCIES else 'EUR').props('outlined')
        error = ui.label('').classes('oy-form-error text-negative text-sm')

        async def save() -> None:
            if not valid_email(email.value):
                error.set_text('Escribe un email válido, como tienda@ejemplo.com.')
                return
            error.set_text('')
            current = load_profile()
            current.shop_mode = bool(shop_mode.value)
            current.shop.name = (name.value or '').strip()
            current.shop.email = (email.value or '').strip()
            current.shop.address = (address.value or '').strip()
            current.shop.city = (city.value or '').strip()
            current.shop.country = (country.value or '').strip()
            current.shop.currency = currency.value
            await run.io_bound(save_profile, current, account_root())
            ui.notify('Tienda guardada.', type='positive')

        ui.button('Guardar tienda', on_click=save).props('color=secondary').classes('w-full q-mt-md')


def render_prices_section() -> None:
    from src.services.prices import sources
    from src.ui.components.pricing_bar import MARKET_LABELS, price_status_text

    profile = load_profile()
    with ui.card().classes('w-full q-pa-lg q-mt-md'):
        with ui.row().classes('items-center gap-2'):
            icon('trending-up', 20)
            ui.label('Precios').classes('text-h6')
        ui.label('Mercado con el que se calculan el valor de tus colecciones y tus precios de venta. '
                 'El otro mercado se muestra como referencia.').classes('text-caption text-grey-5 q-mb-md')
        market = ui.select(MARKET_LABELS, value=profile.price_market, label='Mercado de referencia'
                           ).props('outlined').classes('w-72')

        async def change_market(event) -> None:
            current = load_profile()
            current.price_market = event.value
            await run.io_bound(save_profile, current, account_root())
            ui.notify(f'Mercado de referencia: {MARKET_LABELS[event.value]}', type='positive')

        market.on_value_change(change_market)
        if not can_manage_catalogs():
            return

        ui.label('Los precios se descargan solos cada madrugada (a partir de las 05:00).').classes(
            'text-caption text-grey-6 q-mt-md')
        rows = []
        for source in sources():
            name = f"{PROVIDERS[source.game].display_name} · {MARKET_LABELS[source.market]}" \
                if source.game in PROVIDERS else f'{source.game} · {source.market}'
            with ui.row().classes('w-full items-center gap-4 q-py-xs'):
                ui.label(name).classes('text-sm')
                ui.space()
                status = ui.label(price_status_text(source.store.info())).classes('text-caption text-grey-6')
            rows.append((source, name, status))

        with ui.button().props('flat no-caps color=primary').classes('q-mt-sm') as button:
            icon('refresh-cw')
            ui.label('Actualizar precios ahora').classes('q-ml-xs')

        async def refresh_all() -> None:
            button.disable()
            note = ui.notification('Descargando precios…', type='info', spinner=True, timeout=None)
            failures = []
            try:
                for source, name, status in rows:
                    note.message = f'Descargando {name}…'
                    try:
                        await run.io_bound(source.refresh)
                    except Exception as error:  # the old prices stay; tell which source failed
                        failures.append(f'{name}: {error}')
                    status.set_text(price_status_text(source.store.info()))
            finally:
                note.dismiss()
                button.enable()
            if failures:
                ui.notify('No se pudieron descargar: ' + ' · '.join(failures), type='negative', multi_line=True,
                          timeout=0, close_button='Cerrar')
            else:
                ui.notify('Precios actualizados.', type='positive')

        button.on_click(refresh_all)


def stripe_status_text(summary) -> str:
    """What the settings page says about the stored Stripe key. Never the key itself."""
    if not summary:
        return 'Sin conectar'
    mode = 'real' if summary.get('mode') == 'live' else 'de pruebas'
    text = f"Conectado · clave {summary.get('kind') or 'secreta'} {mode} ····{summary.get('last4', '')}"
    if summary.get('connected_at'):
        try:
            text += ' · desde ' + datetime.fromisoformat(summary['connected_at']).astimezone().strftime('%d/%m/%Y')
        except ValueError:
            pass
    return text


def render_stripe_section() -> None:
    """Each shop connects its own Stripe account: the money goes straight to the shop."""
    from src.services.sales.stripe_gateway import StripeError, StripeGateway, check_key_format
    from src.services.sales.stripe_settings import forget_key, key_summary, load_key, save_key
    from src.ui.sales import build_checkout

    if not load_profile().shop_mode:
        return
    root = account_root()
    checkout = build_checkout()
    state = {'busy': False}
    with ui.card().classes('w-full q-pa-lg q-mt-md'):
        with ui.row().classes('items-center gap-2'):
            icon('credit-card', 20)
            ui.label('Cobros con Stripe').classes('text-h6')
        ui.label('Conecta la cuenta de Stripe de tu tienda para cobrar con QR o enlace desde el mostrador. '
                 'El dinero va directo a tu Stripe; esta aplicación no lo toca ni cobra comisión.').classes(
            'text-caption text-grey-5 q-mb-md')
        holder = ui.element('div')

        @ui.refreshable
        def body() -> None:
            summary = key_summary(root)
            if summary:
                ui.label(stripe_status_text(summary)).classes('oy-mono')
                if summary.get('mode') != 'live':
                    ui.label('Con una clave de pruebas no se mueve dinero real.').classes('text-caption text-grey-5')

                async def force_disconnect(dialog) -> None:
                    if state['busy']:
                        return
                    state['busy'] = True
                    try:
                        await run.io_bound(checkout.release_pending)
                        await run.io_bound(forget_key, root)
                    except Exception as error:
                        logger.error('Stripe: no se pudo desconectar: %s', type(error).__name__)
                        with holder:
                            ui.notify('No se pudo desconectar. Inténtalo de nuevo.', type='negative')
                        return
                    finally:
                        state['busy'] = False
                    dialog.close()
                    with holder:
                        ui.notify('Stripe desconectado. Los cobros abiertos se han cerrado sin confirmar.',
                                  type='warning', multi_line=True)
                    body.refresh()

                def confirm_forced_disconnect(reason: str) -> None:
                    """Stripe no longer answers with this key: let the shop out without leaving stock held."""
                    with ui.dialog() as dialog, ui.card().classes('q-pa-lg').style('max-width: 460px'):
                        ui.label('Stripe no ha podido cerrar los cobros abiertos').classes('text-h6')
                        ui.label(reason).classes('text-negative')
                        ui.label('Si la clave se ha revocado o cambiado, puedes desconectar igualmente: los cobros '
                                 'abiertos se cierran aquí sin preguntar a Stripe y su stock vuelve a la colección. '
                                 'Comprueba después en tu panel de Stripe si alguno llegó a pagarse.').classes(
                            'text-caption text-grey-5')
                        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                            ui.button('Cancelar', on_click=dialog.close).props('flat no-caps color=primary')
                            ui.button('Desconectar igualmente', on_click=lambda: force_disconnect(dialog)).props(
                                'no-caps color=negative')
                    dialog.on('hide', dialog.delete)
                    dialog.open()

                async def disconnect() -> None:
                    if state['busy']:
                        return
                    state['busy'] = True
                    try:
                        key = await run.io_bound(load_key, root)
                        if key:
                            await run.io_bound(checkout.close_pending, StripeGateway(key))
                        await run.io_bound(forget_key, root)
                    except StripeError as error:
                        with holder:
                            confirm_forced_disconnect(str(error))
                        return
                    except Exception as error:
                        logger.error('Stripe: no se pudo desconectar: %s', type(error).__name__)
                        with holder:
                            ui.notify('No se pudo desconectar. Inténtalo de nuevo.', type='negative')
                        return
                    finally:
                        state['busy'] = False
                    with holder:
                        ui.notify('Stripe desconectado.', type='positive')
                    body.refresh()

                ui.button('Desconectar Stripe', on_click=disconnect).props('flat no-caps color=primary').classes(
                    'q-mt-sm')
                return

            ui.label('Sin conectar').classes('oy-mono')
            key_input = ui.input('Clave secreta o restringida', password=True).props(
                'outlined autocomplete=off maxlength=300').classes('w-full q-mt-sm')
            ui.label('En Stripe → Desarrolladores → Claves de API. Mejor una clave restringida (rk_…) con permiso de '
                     'escritura solo en Checkout Sessions y en Refunds. La clave se guarda cifrada en este servidor '
                     'y no se vuelve a mostrar. El permiso de escritura se comprueba de verdad en el primer cobro.'
                     ).classes('text-caption text-grey-5')
            error_label = ui.label('').classes('oy-form-error text-negative text-sm')

            async def connect() -> None:
                if state['busy']:
                    return
                state['busy'] = True
                try:
                    key = check_key_format(key_input.value or '')
                    await run.io_bound(StripeGateway(key).check)
                    await run.io_bound(save_key, root, key)
                except StripeError as error:
                    error_label.set_text(str(error))
                    return
                except Exception as error:
                    logger.error('Stripe: no se pudo guardar la clave: %s', type(error).__name__)
                    error_label.set_text('No se pudo guardar la clave. Inténtalo de nuevo.')
                    return
                finally:
                    state['busy'] = False
                    key_input.set_value('')
                with holder:
                    ui.notify('Stripe conectado.', type='positive')
                body.refresh()

            ui.button('Conectar Stripe', on_click=connect).props('color=secondary').classes('w-full q-mt-md')

        body()
