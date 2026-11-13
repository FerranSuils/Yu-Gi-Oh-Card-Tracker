"""CSV Suite page: export, import, merge and bulk-edit collections. The work itself is in services."""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Optional

from nicegui import events, run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.catalog_models import GameCollection
from src.core.collection_sync import bump, path_lock
from src.core.game_collections import game_collection_store
from src.core.models import Collection
from src.core.persistence import persistence
from src.services.catalog import PROVIDERS
from src.services.catalog.yugioh import catalog_card_from_api
from src.services.csv_suite import (FIELD_LABELS, MAX_BYTES, CatalogIndex, EntryRow, MatchedRow, apply_import,
                                    bulk_edit, entry_key, export_rows, guess_mapping, list_entries, match_rows,
                                    merge_collections, parse_rows, problem_rows_csv, read_table, to_csv)
from src.services.ygo_api import ygo_service
from src.ui.catalog import CONDITIONS, collection_exists, collection_label, new_collection_filename
from src.ui.icons import icon
from src.ui.theme import page_header

logger = logging.getLogger(__name__)

NEW_COLLECTION = '__new__'
PREVIEW_ROWS = 1000
STATUSES = ('ok', 'sin casar', 'ambigua', 'error')
_FORBIDDEN = '/\\:*?"<>|'

PREVIEW_COLUMNS = [
    {'name': 'line', 'label': 'Línea', 'field': 'line', 'align': 'right', 'sortable': True},
    {'name': 'status', 'label': 'Resultado', 'field': 'status', 'align': 'left', 'sortable': True},
    {'name': 'quantity', 'label': 'Cant.', 'field': 'quantity', 'align': 'right'},
    {'name': 'name', 'label': 'Carta', 'field': 'name', 'align': 'left', 'sortable': True},
    {'name': 'set', 'label': 'Set', 'field': 'set', 'align': 'left'},
    {'name': 'condition', 'label': 'Estado', 'field': 'condition', 'align': 'left'},
    {'name': 'language', 'label': 'Idioma', 'field': 'language', 'align': 'left'},
    {'name': 'price', 'label': 'Precio', 'field': 'price', 'align': 'right'},
    {'name': 'reason', 'label': 'Motivo', 'field': 'reason', 'align': 'left'},
]
EDIT_COLUMNS = [
    {'name': 'name', 'label': 'Carta', 'field': 'name', 'align': 'left', 'sortable': True},
    {'name': 'set', 'label': 'Set', 'field': 'set', 'align': 'left', 'sortable': True},
    {'name': 'rarity', 'label': 'Rareza', 'field': 'rarity', 'align': 'left', 'sortable': True},
    {'name': 'finish', 'label': 'Acabado', 'field': 'finish', 'align': 'left'},
    {'name': 'language', 'label': 'Idioma', 'field': 'language', 'align': 'left', 'sortable': True},
    {'name': 'first', 'label': '1.ª ed.', 'field': 'first', 'align': 'left'},
    {'name': 'storage', 'label': 'Ubicación', 'field': 'storage', 'align': 'left', 'sortable': True},
    {'name': 'quantity', 'label': 'Cant.', 'field': 'quantity', 'align': 'right', 'sortable': True},
    {'name': 'condition', 'label': 'Estado', 'field': 'condition', 'align': 'left', 'sortable': True},
    {'name': 'price', 'label': 'Precio de venta', 'field': 'price', 'align': 'right', 'sortable': True,
     ':format': 'value => value === null || value === undefined || value === "" ? "" : Number(value).toFixed(2)'},
]


# --- Pure helpers ------------------------------------------------------------

def failure_text(action: str, exc: Exception) -> str:
    """What the person reads when ``action`` fails. Only our own messages are shown:
    an OSError carries the path of the file on the server."""
    if isinstance(exc, ValueError):
        return str(exc)
    logger.exception('No se ha podido %s', action, exc_info=exc)
    return f'No se ha podido {action}. Inténtalo de nuevo.'


def export_filename(label: str) -> str:
    name = ''.join('_' if char in _FORBIDDEN else char for char in (label or '')).strip()
    return f"{name or 'coleccion'}-cardmarket.csv"


def match_summary(matched: list[MatchedRow]) -> dict[str, int]:
    summary = {status: 0 for status in STATUSES}
    summary['cards'] = 0
    for item in matched:
        summary[item.status] += 1
        if item.status == 'ok':
            summary['cards'] += item.row.quantity
    return summary


def matched_to_table(item: MatchedRow) -> dict:
    row = item.row
    if item.card is not None and item.printing is not None:
        name = item.card.name
        code = (item.printing.set_code or '').upper()
        card_set = f'{code} · {item.printing.number}' if item.printing.number else code
    else:
        name, card_set = row.name, row.set_code
    return {'line': row.line, 'quantity': row.quantity, 'name': name, 'set': card_set,
            'condition': row.condition, 'language': row.language,
            'price': '' if row.price is None else f'{row.price:.2f}', 'status': item.status, 'reason': item.reason}


def entry_to_table(row_id: int, item: EntryRow) -> dict:
    entry = item.entry
    return {'id': row_id, 'name': item.name, 'set': (item.set_code or '').upper(), 'rarity': item.rarity or '',
            'finish': item.finish, 'language': entry.language, 'first': 'Sí' if entry.first_edition else '',
            'storage': entry.storage_location or '', 'quantity': entry.quantity, 'condition': entry.condition,
            'price': entry.list_price}


def parse_price(value: Any) -> Optional[float]:
    """A price typed by hand ('1,50', ' 3.25 € '). Empty means no price."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        text = str(value).replace('€', '').replace('$', '').replace(' ', '').replace(',', '.')
        price = float(text)
    except ValueError:
        raise ValueError('Precio no válido') from None
    if not math.isfinite(price) or price < 0:
        raise ValueError('Precio no válido')
    return price


def game_name(game: str) -> str:
    return PROVIDERS[game].display_name if game in PROVIDERS else 'Yu-Gi-Oh!'


# --- Storage and catalog -----------------------------------------------------

class Shelf:
    """The collections of one game for the signed-in account. Build it on the UI thread."""

    def __init__(self, game: str):
        self.game = game
        self.store = game_collection_store.bound()

    def files(self) -> list[str]:
        if self.game == 'yugioh':
            return sorted(f for f in persistence.list_collections() if f.endswith('.json'))
        return self.store.list(self.game)

    def load(self, filename: str):
        if self.game == 'yugioh':
            return persistence.load_collection(filename)
        return self.store.load(self.game, filename)

    def save(self, collection, filename: str) -> None:
        if self.game == 'yugioh':
            persistence.save_collection(collection, filename)
        else:
            self.store.save(self.game, collection, filename)

    def path(self, filename: str) -> str:
        if self.game == 'yugioh':
            return persistence.collection_path(filename)
        return self.store.path(self.game, filename)

    def new(self, name: str):
        return Collection(name=name) if self.game == 'yugioh' else GameCollection(game=self.game, name=name)

    def change(self, filename: str, action, create: bool = False):
        """Load, change and save one collection without another writer in between."""
        path = self.path(filename)
        with path_lock(path):
            collection = self.new(collection_label(filename)) if create else self.load(filename)
            result = action(collection)
            if result:
                self.save(collection, filename)
        if result:
            bump(path)  # open pages reload instead of saving an older copy
        return result


_INDEX: dict[str, tuple[Any, CatalogIndex]] = {}


async def catalog_index(game: str) -> CatalogIndex:
    """The catalog of a game, indexed for matching. Rebuilt only when the catalog changes."""
    if game == 'yugioh':
        cards = await ygo_service.load_card_database()
        token: Any = (id(cards), len(cards))

        def build() -> CatalogIndex:
            return CatalogIndex([catalog_card_from_api(card) for card in cards], game)
    else:
        store = PROVIDERS[game].store
        token = os.path.getmtime(store.path) if os.path.exists(store.path) else None

        def build() -> CatalogIndex:
            return CatalogIndex(store.load() if token is not None else [], game)
    cached = _INDEX.get(game)
    if cached and cached[0] == token:
        return cached[1]
    index = await run.io_bound(build)
    _INDEX[game] = (token, index)
    return index


# --- Page --------------------------------------------------------------------

def csv_suite_page() -> None:
    enabled = enabled_games(load_profile())
    page_header('CSV', 'Exporta, importa, fusiona y edita tus colecciones en bloque.')
    state = {'game': enabled[0]}

    if len(enabled) > 1:
        def switch(event) -> None:
            state['game'] = event.value
            body.refresh()

        ui.toggle({game: game_name(game) for game in enabled}, value=state['game'], on_change=switch).props(
            'no-caps unelevated toggle-color=primary').classes('q-mb-sm')

    @ui.refreshable
    def body() -> None:
        _render_game(state['game'])

    body()


def _render_game(game: str) -> None:
    shelf = Shelf(game)
    files = shelf.files()
    pickers: list = []  # (select, with_new_option, multiple)

    def options(with_new: bool = False) -> dict:
        result = {f: collection_label(f) for f in files}
        if with_new:
            result[NEW_COLLECTION] = 'Nueva colección…'
        return result

    def refresh_files() -> None:
        files[:] = shelf.files()
        pickers[:] = [item for item in pickers if not item[0].is_deleted]  # the import preview comes and goes
        for select, with_new, multiple in pickers:
            current = select.value
            select.set_options(options(with_new))
            if multiple:
                select.set_value([f for f in (current or []) if f in files])
            elif current in files or (with_new and current == NEW_COLLECTION):
                select.set_value(current)
            else:
                select.set_value(files[0] if files else (NEW_COLLECTION if with_new else None))

    def picker(label: str, with_new: bool = False, multiple: bool = False):
        value: Any = [] if multiple else (files[0] if files else (NEW_COLLECTION if with_new else None))
        select = ui.select(options(with_new), label=label, value=value, multiple=multiple).props(
            'outlined dense' + (' use-chips' if multiple else '')).classes('w-72')
        pickers.append((select, with_new, multiple))
        return select

    with ui.tabs().props('dense no-caps align=left').classes('w-full') as tabs:
        ui.tab('export', label='Exportar')
        ui.tab('import', label='Importar')
        ui.tab('merge', label='Fusionar')
        ui.tab('edit', label='Editar en bloque')
    with ui.tab_panels(tabs, value='export').classes('w-full').style('background: transparent'):
        with ui.tab_panel('export').classes('q-px-none'):
            _export_tab(shelf, picker)
        with ui.tab_panel('import').classes('q-px-none'):
            _import_tab(shelf, picker, files, refresh_files)
        with ui.tab_panel('merge').classes('q-px-none'):
            _merge_tab(shelf, picker, files, refresh_files)
        with ui.tab_panel('edit').classes('q-px-none'):
            _edit_tab(shelf, picker)


def _export_tab(shelf: Shelf, picker) -> None:
    ui.label('Un solo CSV con las columnas de stock de Cardmarket (idProduct, groupCount, price, idLanguage, '
             'condition, isFoil…) y, a continuación, nombre, set, número y rareza para las tiendas que casan '
             'por texto. Ese mismo archivo se puede volver a importar aquí.').classes('oy-sub q-mb-md').style(
        'max-width: 760px')
    with ui.row().classes('items-center gap-3'):
        source = picker('Colección')

        async def export() -> None:
            if not source.value:
                ui.notify('Elige una colección.', type='warning')
                return
            try:
                collection = await run.io_bound(shelf.load, source.value)
                index = await catalog_index(shelf.game)
                data = await run.io_bound(lambda: to_csv(export_rows(collection, shelf.game, index.card)))
            except Exception as exc:  # a broken file must not take the page down
                ui.notify(failure_text('exportar', exc), type='negative')
                return
            ui.download.content(data, export_filename(collection_label(source.value)), 'text/csv')

        with ui.button(on_click=export).props('color=secondary no-caps'):
            icon('download')
            ui.label('Descargar CSV').classes('q-ml-xs')


def _import_tab(shelf: Shelf, picker, files: list[str], refresh_files) -> None:
    state: dict = {'headers': [], 'rows': [], 'matched': [], 'selects': {}}
    ui.label('Sube un CSV de Cardmarket, TCGplayer, Moxfield, Deckbox u otra tienda (máx. 5 MB). '
             'Se reconocen las columnas, las revisas y solo entonces se añaden las cartas.').classes(
        'oy-sub q-mb-md').style('max-width: 760px')

    async def uploaded(event: events.UploadEventArguments) -> None:
        file_obj = getattr(event, 'content', getattr(event, 'file', None))
        try:
            data = await file_obj.read()
            headers, rows = await run.io_bound(read_table, data)
        except ValueError as problem:
            ui.notify(str(problem), type='negative')
            return
        finally:
            upload.reset()
        state.update(headers=[h for h in headers if h], rows=rows, matched=[])
        render_mapping()
        preview_box.clear()

    upload = ui.upload(label='CSV de la tienda', auto_upload=True, max_file_size=MAX_BYTES, on_upload=uploaded,
                       on_rejected=lambda: ui.notify('El archivo supera los 5 MB.', type='negative')).props(
        'accept=".csv,.txt,.tsv,text/csv" flat bordered').classes('w-full').style('max-width: 480px')
    mapping_box = ui.column().classes('w-full gap-2 q-mt-md')
    preview_box = ui.column().classes('w-full gap-2 q-mt-md')

    def render_mapping() -> None:
        mapping_box.clear()
        guess = guess_mapping(state['headers'])
        state['selects'] = {}
        with mapping_box:
            ui.label(f"{len(state['rows'])} filas. ¿Qué columna es cada dato?").classes('text-subtitle1')
            with ui.element('div').classes('w-full grid gap-2').style(
                    'grid-template-columns: repeat(auto-fill, minmax(220px, 1fr))'):
                for field, label in FIELD_LABELS.items():
                    state['selects'][field] = ui.select(state['headers'], label=label, value=guess.get(field),
                                                        clearable=True).props('outlined dense')
            with ui.button(on_click=review).props('color=primary no-caps'):
                icon('search')
                ui.label('Revisar').classes('q-ml-xs')

    async def review() -> None:
        mapping = {field: select.value for field, select in state['selects'].items() if select.value}
        if not mapping:
            ui.notify('Asigna al menos una columna.', type='warning')
            return
        try:
            index = await catalog_index(shelf.game)
        except Exception as exc:
            ui.notify(failure_text('cargar el catálogo', exc), type='negative')
            return
        rows = state['rows']
        state['matched'] = await run.io_bound(lambda: match_rows(parse_rows(rows, mapping), index))
        render_preview(empty_catalog=not index.cards)

    def render_preview(empty_catalog: bool) -> None:
        matched = state['matched']
        summary = match_summary(matched)
        preview_box.clear()
        with preview_box:
            if empty_catalog:
                ui.label(f'El catálogo de {game_name(shelf.game)} no está descargado: descárgalo en Ajustes '
                         'para poder casar las cartas.').classes('text-negative')
            ui.label(f"{summary['ok']} filas casadas ({summary['cards']} cartas) · {summary['sin casar']} sin casar "
                     f"· {summary['ambigua']} ambiguas · {summary['error']} con error").classes('text-subtitle1')
            ordered = sorted(matched, key=lambda item: item.status == 'ok')  # problems first
            if len(ordered) > PREVIEW_ROWS:
                ui.label(f'Se muestran las primeras {PREVIEW_ROWS} filas, los problemas primero.').classes('oy-sub')
            ui.table(columns=PREVIEW_COLUMNS, rows=[matched_to_table(item) for item in ordered[:PREVIEW_ROWS]],
                     row_key='line', pagination={'rowsPerPage': 25}).classes('w-full').props('dense flat')
            problems = len(matched) - summary['ok']
            if problems:
                def download_problems() -> None:
                    data = problem_rows_csv(state['headers'], state['rows'], matched)
                    if data:
                        ui.download.content(data, 'sin-casar.csv', 'text/csv')

                with ui.button(on_click=download_problems).props('flat no-caps color=secondary'):
                    icon('download')
                    ui.label(f'Descargar las {problems} filas no importadas').classes('q-ml-sm')
            if not summary['ok']:
                return
            with ui.row().classes('items-center gap-3 q-mt-sm'):
                target = picker('Añadir a', with_new=True)
                new_name = ui.input('Nombre de la nueva colección').props(
                    'outlined dense stack-label maxlength=80').classes('w-64')
                new_name.bind_visibility_from(target, 'value', backward=lambda v: v == NEW_COLLECTION)

                async def run_import() -> bool:
                    try:
                        create = target.value == NEW_COLLECTION
                        filename = new_collection_filename(new_name.value) if create else target.value
                        if not filename:
                            raise ValueError('Elige una colección.')
                        if create and collection_exists(filename, shelf.files()):
                            raise ValueError('Ya tienes una colección con ese nombre.')
                        added = await run.io_bound(
                            shelf.change, filename,
                            lambda collection: apply_import(collection, matched, ygo_service.get_card), create)
                    except Exception as exc:
                        ui.notify(failure_text('importar', exc), type='negative')
                        return False
                    ui.notify(f'{added} cartas añadidas a {collection_label(filename)}.',
                              type='positive' if added else 'warning')
                    state.update(rows=[], matched=[])
                    mapping_box.clear()
                    preview_box.clear()
                    refresh_files()
                    return True

                with ui.button(on_click=one_shot(run_import)).props('color=secondary no-caps'):
                    icon('upload')
                    ui.label(f"Importar {summary['cards']} cartas").classes('q-ml-xs')


def one_shot(action):
    """Click handler that ignores clicks while ``action`` runs and after it has returned True."""
    state = {'busy': False, 'done': False}

    async def guarded() -> None:
        if state['busy'] or state['done']:
            return
        state['busy'] = True
        try:
            state['done'] = bool(await action())
        finally:
            state['busy'] = False
    return guarded


def _merge_tab(shelf: Shelf, picker, files: list[str], refresh_files) -> None:
    ui.label('Crea una colección nueva con todas las cartas de las que elijas. Las de origen no cambian.').classes(
        'oy-sub q-mb-md')
    with ui.row().classes('items-center gap-3'):
        sources = picker('Colecciones a fusionar', multiple=True)
        name = ui.input('Nombre de la colección fusionada').props('outlined dense stack-label maxlength=80').classes(
            'w-64')

        async def merge() -> None:
            chosen = list(sources.value or [])
            try:
                if len(chosen) < 2:
                    raise ValueError('Elige al menos dos colecciones.')
                filename = new_collection_filename(name.value)
                if collection_exists(filename, shelf.files()):
                    raise ValueError('Ya tienes una colección con ese nombre.')

                def work() -> int:
                    merged = merge_collections(collection_label(filename), [shelf.load(f) for f in chosen])
                    shelf.save(merged, filename)
                    return merged.total_cards

                total = await run.io_bound(work)
            except Exception as exc:
                ui.notify(failure_text('fusionar', exc), type='negative')
                return
            ui.notify(f'{collection_label(filename)} creada con {total} cartas.', type='positive')
            name.set_value('')
            refresh_files()

        with ui.button(on_click=merge).props('color=secondary no-caps'):
            icon('arrow-merge')
            ui.label('Fusionar').classes('q-ml-xs')


def _edit_tab(shelf: Shelf, picker) -> None:
    state: dict = {'keys': {}}
    ui.label('Marca varias entradas y cámbiales a la vez cantidad, estado o precio de venta. '
             'Un campo vacío no se toca; cantidad 0 borra la entrada.').classes('oy-sub q-mb-md')
    with ui.row().classes('items-center gap-3 q-mb-sm'):
        source = picker('Colección')
        search = ui.input(placeholder='Filtrar').props('outlined dense clearable').classes('w-64')
        count = ui.label('').classes('oy-sub')
    table = ui.table(columns=EDIT_COLUMNS, rows=[], row_key='id', selection='multiple',
                     pagination={'rowsPerPage': 50}).classes('w-full').props('dense flat')
    search.bind_value_to(table, 'filter')

    with ui.row().classes('w-full items-center gap-2 q-mt-sm'):
        chosen = ui.label('Nada seleccionado').classes('text-sm')
        quantity = ui.number('Cantidad', min=0, max=9999, precision=0).props('outlined dense clearable').classes(
            'w-28')
        condition = ui.select(CONDITIONS, label='Estado', clearable=True).props('outlined dense').classes('w-40')
        price = ui.input('Precio de venta').props('outlined dense clearable').classes('w-36')
        clear_price = ui.checkbox('Quitar precio')
        apply_button = ui.button('Aplicar a la selección').props('no-caps color=secondary')
    table.on('selection', lambda: chosen.set_text(
        f'{len(table.selected)} seleccionadas' if table.selected else 'Nada seleccionado'))

    async def reload() -> None:
        table.selected = []
        chosen.set_text('Nada seleccionado')
        if not source.value:
            state['keys'] = {}
            table.rows = []
            count.set_text('')
            return
        try:
            collection = await run.io_bound(shelf.load, source.value)
        except Exception as exc:
            ui.notify(failure_text('abrir la colección', exc), type='negative')
            return
        items = list_entries(collection)
        state['keys'] = {i: entry_key(item) for i, item in enumerate(items)}
        table.rows = [entry_to_table(i, item) for i, item in enumerate(items)]
        count.set_text(f'{len(items)} entradas · {collection.total_cards} cartas')

    async def apply() -> None:
        keys = [state['keys'][row['id']] for row in table.selected if row['id'] in state['keys']]
        try:
            if not keys:
                raise ValueError('Marca al menos una entrada.')
            new_quantity = None if quantity.value is None else int(quantity.value)
            new_price = parse_price(price.value)
            if new_quantity is None and not condition.value and new_price is None and not clear_price.value:
                raise ValueError('Indica qué quieres cambiar.')
            result = await run.io_bound(
                shelf.change, source.value,
                lambda collection: bulk_edit(collection, keys, new_quantity, condition.value or None, new_price,
                                             bool(clear_price.value)))
        except Exception as exc:
            ui.notify(failure_text('guardar', exc), type='negative')
            return
        changed, missing = result
        note = f' {missing} ya no estaban en la colección.' if missing else ''
        ui.notify(f'{changed} entradas cambiadas.{note}', type='positive' if changed else 'warning')
        await reload()

    apply_button.on_click(apply)
    source.on_value_change(lambda _: reload())
    ui.timer(0.01, reload, once=True)
