"""/informes: what came in, through where, and which cards moved, for a period."""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Tuple

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.account_scope import account_root
from src.core.sales_models import METHOD_LABELS, format_money
from src.services.reports.summary import PERIODS, Report, gather, period, report_csv, stock_value
from src.services.shop.desk import desk_for
from src.ui.icons import icon
from src.ui.theme import page_header

logger = logging.getLogger(__name__)

ICONS = ('download', 'trending-up', 'receipt', 'cards-deck', 'hand-coin', 'package-box')
CUSTOM = 'fechas'
REPORT_CSS = '''
.oy-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; width: 100%; }
.oy-tile { border: 1px solid var(--oy-border); border-radius: 6px; background: var(--oy-surface); padding: 14px 16px; }
.oy-tile-value { font-family: var(--oy-font-display); font-size: 26px; line-height: 1.15; }
.oy-report-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; width: 100%;
  align-items: start; }
.oy-report-row { border-bottom: 1px solid var(--oy-border-soft); }
'''


def typed_range(start_text: str, end_text: str, today: date) -> Tuple[date, date]:
    """Two typed dates. A missing or unreadable one falls back to this month's."""
    first, last = period('mes', today)

    def read(text: str, fallback: date) -> date:
        try:
            return date.fromisoformat((text or '').strip())
        except ValueError:
            return fallback

    return read(start_text, first), read(end_text, last)


def chart_options(report: Report) -> dict:
    days = [f'{day[8:10]}/{day[5:7]}' for day, _ in report.by_day]
    return {
        'grid': {'left': 48, 'right': 12, 'top': 16, 'bottom': 28},
        'tooltip': {'trigger': 'axis'},
        'xAxis': {'type': 'category', 'data': days},
        'yAxis': {'type': 'value'},
        'series': [{'type': 'bar', 'data': [cents / 100 for _, cents in report.by_day],
                    'itemStyle': {'color': '#b08d57'}}],
    }


def method_rows(by_method: Dict[str, int], currency: str) -> List[Tuple[str, str]]:
    return [(METHOD_LABELS[method], format_money(by_method[method], currency))
            for method in METHOD_LABELS if by_method.get(method)]


def reports_page() -> None:
    ui.add_css(REPORT_CSS)
    profile = load_profile()
    page_header('Informes', 'Lo que ha entrado, por dónde y qué cartas se han movido.')
    if not profile.shop_mode:
        ui.label('Los informes son parte del modo tienda. Actívalo en Ajustes → Modo tienda.').classes('oy-sub')
        return
    currency = profile.shop.currency
    desk = desk_for(account_root(), currency)
    games = enabled_games(profile)
    state = {'report': None, 'stock': (0, 0), 'failed': False}

    def money(cents: int) -> str:
        return format_money(cents, currency)

    with ui.row().classes('w-full items-center gap-3 q-mt-md'):
        chooser = ui.select({**PERIODS, CUSTOM: 'Entre dos fechas'}, value='mes', label='Periodo').props(
            'outlined dense').classes('w-56')
        start_box = ui.input('Desde').props('outlined dense type=date stack-label').classes('w-44')
        end_box = ui.input('Hasta').props('outlined dense type=date stack-label').classes('w-44')
        ui.space()
        with ui.button().props('flat no-caps color=primary') as export_button:
            icon('download')
            ui.label('Exportar CSV').classes('q-ml-xs')
    start_box.bind_visibility_from(chooser, 'value', lambda value: value == CUSTOM)
    end_box.bind_visibility_from(chooser, 'value', lambda value: value == CUSTOM)

    def tile(name: str, title: str, value: str, note: str = '') -> None:
        with ui.column().classes('oy-tile gap-1'):
            with ui.row().classes('items-center gap-2 oy-sub'):
                icon(name, 16)
                ui.label(title)
            ui.label(value).classes('oy-tile-value')
            if note:
                ui.label(note).classes('oy-sub text-xs')

    def table(title: str, rows: List[Tuple[str, str]], empty: str) -> None:
        with ui.column().classes('gap-0 w-full'):
            ui.label(title).classes('text-subtitle1 q-mb-sm')
            if not rows:
                ui.label(empty).classes('oy-sub')
            for left, right in rows:
                with ui.row().classes('oy-report-row w-full items-center gap-3 q-py-xs no-wrap'):
                    ui.label(left).classes('text-sm ellipsis').style('min-width: 0; flex: 1')
                    ui.label(right).classes('oy-mono')

    @ui.refreshable
    def body() -> None:
        report = state['report']
        if state['failed']:
            ui.label('No se pudieron leer los libros de la tienda. Recarga la página.').classes('oy-sub q-mt-md')
            return
        if report is None:
            ui.spinner(size='lg').classes('q-mt-lg')
            return
        ui.label(f'Del {report.start.strftime("%d/%m/%Y")} al {report.end.strftime("%d/%m/%Y")}').classes(
            'oy-sub q-mt-md')
        with ui.element('div').classes('oy-tiles q-mt-sm'):
            tile('trending-up', 'Ingresos', money(report.revenue_cents))
            tile('receipt', 'Operaciones', str(report.count), f'Ticket medio {money(report.average_cents)}')
            tile('cards-deck', 'Unidades vendidas', str(report.units))
            tile('hand-coin', 'Compras', money(report.purchases_cents))
            units, cents = state['stock']
            tile('package-box', 'Stock a la venta', money(cents), f'{units} unidades con precio, ahora')
        if report.foreign:
            ui.label('Aparte, sin sumar a los ingresos, hay pedidos cobrados en otra moneda: '
                     + ', '.join(format_money(cents, code) for code, cents in sorted(report.foreign.items()))
                     + '.').classes('oy-sub q-mt-md')
        if not report.count:
            ui.label('No hay ventas ni pedidos cobrados en este periodo.').classes('oy-sub q-mt-lg')
            return
        ui.label('Ingresos por día').classes('text-subtitle1 q-mt-lg')
        ui.echart(chart_options(report)).classes('w-full').style('height: 260px')
        with ui.element('div').classes('oy-report-grid q-mt-lg'):
            table('Por canal', [(name, money(cents)) for name, cents in
                                sorted(report.by_channel.items(), key=lambda pair: -pair[1])], 'Sin ingresos.')
            table('Por forma de pago (mostrador)', method_rows(report.by_method, currency),
                  'Sin ventas en el mostrador.')
        with ui.column().classes('w-full q-mt-lg'):
            table('Cartas más vendidas',
                  [(f'{card.units} × {card.name}' + (f' · {card.set_code}' if card.set_code else ''),
                    money(card.cents)) for card in report.top], 'Sin cartas vendidas.')

    def chosen() -> Tuple[date, date]:
        today = date.today()
        if chooser.value == CUSTOM:
            return typed_range(start_box.value, end_box.value, today)
        return period(chooser.value, today)

    async def reload() -> None:
        start, end = chosen()
        state['failed'] = False
        try:
            state['report'] = await run.io_bound(gather, desk, start, end, currency)
            items = await run.io_bound(desk.inventory.items, games)
            state['stock'] = stock_value(items)
        except Exception as error:
            logger.error('Informes: %s', type(error).__name__)
            state['failed'] = True
        body.refresh()

    def export() -> None:
        report = state['report']
        if report is None:
            return
        ui.download.content(report_csv(report), f'informe-{report.start.isoformat()}-{report.end.isoformat()}.csv',
                            'text/csv')

    body()
    chooser.on_value_change(reload)
    start_box.on_value_change(reload)
    end_box.on_value_change(reload)
    export_button.on_click(export)
    ui.timer(0.1, reload, once=True)
