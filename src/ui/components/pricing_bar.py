"""Collection value bar and the «Precios…» dialog, shared by Yu-Gi-Oh and the other games."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional

from nicegui import run, ui

from src.core.account_profile import load_profile
from src.core.account_scope import account_root
from src.core.pricing_models import DEFAULT_CONDITION_FACTORS, PricingRule
from src.core.catalog_models import GameCollection
from src.core.game_collections import GameCollectionEditor
from src.services.collection_editor import CollectionEditor
from src.services.repricing import (RepriceRow, apply, base_price, collection_values, preview, quote_for,
                                    validate_rule)
from src.ui.icons import icon

logger = logging.getLogger(__name__)

METRIC_LABELS = {'trend': 'Tendencia', 'avg': 'Media', 'low': 'Mínimo', 'avg1': 'Media 1 día',
                 'avg7': 'Media 7 días', 'avg30': 'Media 30 días'}
ROUNDING_LABELS = {'none': 'Sin redondeo', 'x49_x99': 'A ,49 / ,99', 'step_005': 'A 0,05'}
MARKET_LABELS = {'cardmarket': 'Cardmarket (EUR)', 'tcgplayer': 'TCGplayer (USD)'}
STATUS_LABELS = {'cambia': 'Cambia', 'igual': 'Igual', 'bloqueada': 'Bloqueada', 'sin precio': 'Sin precio',
                 'por carta': 'Por carta'}


def other_market(market: str) -> str:
    return 'tcgplayer' if market == 'cardmarket' else 'cardmarket'


def format_money(value: Optional[float], market: str) -> str:
    if value is None:
        return '—'
    if market == 'tcgplayer':
        return f'${value:,.2f}'
    return f'{value:,.2f}'.replace(',', ' ').replace('.', ',').replace(' ', '.') + ' €'


def _signed(value: Optional[float], market: str) -> str:
    if value is None:
        return '—'
    text = format_money(abs(value), market)
    return ('+' if value > 0 else '-' if value < 0 else '') + text


def price_status_text(info: dict) -> str:
    count = int(info.get('count') or 0)
    if not count:
        return 'Sin descargar'
    text = f'{count:,}'.replace(',', '.') + ' precios'
    if info.get('updated_at'):
        try:
            text += ' · actualizado ' + datetime.fromisoformat(info['updated_at']).strftime('%d/%m/%Y')
        except ValueError:
            pass
    return text


def row_to_table_dict(index: int, row: RepriceRow, market: str, reference: Optional[float],
                      scope: Optional[str]) -> dict:
    ref = row.ref
    return {
        'id': index, 'name': ref.name, 'set': ref.set_code, 'finish': ref.finish,
        'condition': ref.entry.condition, 'quantity': ref.entry.quantity,
        'market': format_money(row.market, market), 'current': format_money(row.current, market),
        'new': format_money(row.new, market), 'delta': _signed(row.delta, market), 'status': row.status,
        'reference': format_money(reference, other_market(market)) if reference is not None else '—',
        'locked': ref.entry.price_locked,
        'note': 'precio por carta' if scope == 'card' else '',
    }


def _load_prices(game: str, market: str) -> dict:
    """{printing_id: PrintingPrice} for one game and market; empty when not downloaded."""
    from src.services.prices import get_source

    try:
        return get_source(game, market).store.load()
    except KeyError:
        return {}


def load_price_context(root: str, game: str) -> dict:
    market = load_profile(root).price_market
    return {'market': market, 'prices': _load_prices(game, market),
            'reference': _load_prices(game, other_market(market))}


COLUMNS = [
    {'name': 'name', 'label': 'Carta', 'field': 'name', 'align': 'left', 'sortable': True},
    {'name': 'set', 'label': 'Set', 'field': 'set', 'align': 'left'},
    {'name': 'condition', 'label': 'Estado', 'field': 'condition', 'align': 'left'},
    {'name': 'quantity', 'label': 'Cant.', 'field': 'quantity'},
    {'name': 'market', 'label': 'Mercado', 'field': 'market'},
    {'name': 'current', 'label': 'Actual', 'field': 'current'},
    {'name': 'new', 'label': 'Nuevo', 'field': 'new'},
    {'name': 'delta', 'label': 'Dif.', 'field': 'delta'},
    {'name': 'status', 'label': 'Estado precio', 'field': 'status', 'align': 'left', 'sortable': True},
    {'name': 'reference', 'label': 'Otro mercado', 'field': 'reference', 'classes': 'text-grey-6'},
    {'name': 'note', 'label': '', 'field': 'note', 'classes': 'text-grey-6 text-caption'},
]


def render_pricing_bar(container: ui.element, collection, game: str,
                       save: Callable[[], Awaitable[None]]) -> None:
    """Fill ``container`` with the value bar of ``collection``. ``save`` persists it."""
    container.clear()
    if collection is None:
        return
    root = account_root()  # resolve on the UI thread: worker threads cannot see the session
    state: dict = {}

    with container:
        with ui.row().classes('oy-pricing-bar w-full items-center gap-4 q-py-sm flex-wrap'):
            with ui.row().classes('items-center gap-1'):
                icon('trending-up', 16)
                market_label = ui.label('Valor de mercado: …').classes('text-sm')
            with ui.row().classes('items-center gap-1'):
                icon('tag', 16)
                sale_label = ui.label('Precio de venta: …').classes('text-sm')
            for_sale = ui.switch('A la venta', value=bool(collection.for_sale)).props('dense')
            ui.space()
            prices_button = ui.button().props('flat no-caps dense color=primary')
            with prices_button:
                icon('tag', 16)
                ui.label('Precios…').classes('q-ml-xs')
            prices_button.disable()

    def refresh_values() -> None:
        market_value, sale_value = collection_values(collection, state['prices'].get)
        market_label.set_text('Valor de mercado: ' + format_money(market_value, state['market']))
        sale_label.set_text('Precio de venta: ' + format_money(sale_value, state['market']))

    async def load() -> None:
        try:
            state.update(await run.io_bound(load_price_context, root, game))
        except Exception as error:
            logger.error('Pricing bar could not load prices: %s', error)
            market_label.set_text('Valor de mercado: sin precios')
            return
        refresh_values()
        if not state['prices']:
            market_label.set_text('Valor de mercado: precios aún no descargados')
        prices_button.enable()

    async def toggle_sale(event) -> None:
        collection.for_sale = bool(event.value)
        await save()
        ui.notify('Colección a la venta.' if event.value else 'Colección retirada de la venta.')

    for_sale.on_value_change(toggle_sale)
    prices_button.on_click(lambda: _open_dialog(collection, game, state, save, refresh_values))
    ui.timer(0, load, once=True)


def _open_dialog(collection, game: str, state: dict, save, on_saved: Callable[[], None]) -> None:
    market = state['market']
    rule = (collection.pricing_rule or PricingRule()).model_copy(deep=True)
    rows: list[RepriceRow] = []

    with ui.dialog().props('maximized') as dialog, ui.card().classes('w-full h-full q-pa-md'):
        with ui.row().classes('w-full items-center'):
            ui.label(f'Precios · {collection.name}').classes('text-h6')
            ui.label(MARKET_LABELS.get(market, market)).classes('text-caption text-grey-6')
            ui.space()
            ui.button('Cerrar', on_click=dialog.close).props('flat no-caps')

        with ui.expansion('Regla de precio', value=True).classes('w-full'):
            with ui.element('div').classes('w-full grid gap-3').style(
                    'grid-template-columns: repeat(auto-fill, minmax(200px, 1fr))'):
                metric = ui.select(METRIC_LABELS, value=rule.metric, label='Precio base').props('outlined dense')
                percent = ui.number('Porcentaje (%)', value=rule.percent, min=0, step=1).props('outlined dense')
                fixed = ui.number('Cantidad fija', value=rule.fixed, step=0.1).props('outlined dense')
                minimum = ui.number('Precio mínimo', value=rule.min_price, min=0, step=0.05).props('outlined dense')
                rounding = ui.select(ROUNDING_LABELS, value=rule.rounding, label='Redondeo').props('outlined dense')
                auto = ui.checkbox('Aplicar cada día', value=rule.auto_apply)
                card_prices = ui.checkbox('Usar también precios por carta', value=rule.use_card_prices).tooltip(
                    'Yu-Gi-Oh en Cardmarket solo tiene un precio por carta (la impresión más barata). '
                    'Sin marcar, esas entradas no se reprecian.')
            ui.label('Factor por estado (%)').classes('text-caption text-grey-6 q-mt-sm')
            factors = {}
            with ui.element('div').classes('w-full grid gap-2').style(
                    'grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))'):
                for condition in DEFAULT_CONDITION_FACTORS:
                    factors[condition] = ui.number(condition, value=rule.condition_factors.get(condition, 100),
                                                   min=0, step=5).props('outlined dense')
            error = ui.label('').classes('text-negative text-sm')

        with ui.row().classes('w-full items-center gap-2 q-my-sm'):
            preview_button = ui.button('Vista previa').props('no-caps color=primary')
            apply_button = ui.button('Aplicar cambios').props('no-caps color=positive')
            apply_button.disable()
            summary = ui.label('').classes('text-sm text-grey-7')

        table = ui.table(columns=COLUMNS, rows=[], row_key='id', selection='single',
                         pagination={'rowsPerPage': 50}).classes('w-full').props('dense flat')

        with ui.row().classes('w-full items-center gap-2') as editor:
            ui.label('Entrada seleccionada:').classes('text-sm')
            manual = ui.number('Precio a mano', min=0, step=0.05).props('outlined dense')
            locked = ui.checkbox('Bloquear (no repreciar)')
            save_entry = ui.button('Guardar entrada').props('no-caps flat color=primary')
        editor.set_visibility(False)

    def read_rule() -> Optional[PricingRule]:
        candidate = PricingRule(
            metric=metric.value, percent=float(percent.value or 0), fixed=float(fixed.value or 0),
            min_price=float(minimum.value or 0), rounding=rounding.value, auto_apply=bool(auto.value),
            use_card_prices=bool(card_prices.value),
            condition_factors={c: float(f.value if f.value is not None else 100) for c, f in factors.items()})
        problems = validate_rule(candidate)
        error.set_text(' '.join(problems))
        return None if problems else candidate

    def show_preview() -> None:
        current = read_rule()
        if current is None:
            return
        rows[:] = preview(collection, state['prices'].get, current)
        table_rows = []
        for index, row in enumerate(rows):
            price = state['prices'].get(row.ref.printing_id)
            other = state['reference'].get(row.ref.printing_id)
            reference = base_price(PricingRule(), quote_for(other, row.ref.finish))
            table_rows.append(row_to_table_dict(index, row, market, reference, price.scope if price else None))
        table.rows = table_rows
        table.update()
        changes = sum(1 for r in rows if r.status == 'cambia')
        counts = {s: sum(1 for r in rows if r.status == s) for s in STATUS_LABELS}
        summary.set_text(f"{changes} cambios · {counts['igual']} iguales · {counts['bloqueada']} bloqueadas · "
                         f"{counts['sin precio']} sin precio" +
                         (f" · {counts['por carta']} solo con precio por carta" if counts['por carta'] else ''))
        apply_button.enable() if changes else apply_button.disable()

    async def confirm_apply() -> None:
        current = read_rule()
        if current is None:
            return
        show_preview()  # rebuild from the rule on screen: the last preview may be from an older rule
        changes = sum(1 for r in rows if r.status == 'cambia')
        if not changes:
            return
        with ui.dialog() as ask, ui.card():
            ui.label(f'¿Aplicar {changes} cambios de precio?')
            with ui.row():
                ui.button('Cancelar', on_click=lambda: ask.submit(False)).props('flat no-caps')
                ui.button('Aplicar', on_click=lambda: ask.submit(True)).props('no-caps color=positive')
        if not await ask:
            return
        collection.pricing_rule = current
        written = apply(collection, rows)
        await save()
        on_saved()
        ui.notify(f'{written} precios actualizados.', type='positive')
        show_preview()

    def on_select(event) -> None:
        selected = event.selection
        if not selected:
            editor.set_visibility(False)
            return
        entry = rows[selected[0]['id']].ref.entry
        manual.value = entry.list_price
        locked.value = entry.price_locked
        editor.set_visibility(True)

    async def save_selected() -> None:
        if not table.selected:
            return
        ref = rows[table.selected[0]['id']].ref
        editor_cls = GameCollectionEditor if isinstance(collection, GameCollection) else CollectionEditor
        value = manual.value
        editor_cls.set_list_price(ref.entry, None if value in (None, '') else float(value), bool(locked.value))
        await save()
        on_saved()
        ui.notify('Entrada guardada.', type='positive')
        show_preview()

    async def save_rule_only() -> None:
        current = read_rule()
        if current is not None and collection.pricing_rule != current:
            collection.pricing_rule = current
            await save()

    preview_button.on_click(show_preview)
    apply_button.on_click(confirm_apply)
    table.on_select(on_select)
    save_entry.on_click(save_selected)
    auto.on_value_change(lambda _: save_rule_only())
    dialog.open()
    show_preview()
