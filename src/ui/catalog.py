"""Catalog browser for every game except Yu-Gi-Oh, which keeps its own pages."""

from __future__ import annotations

import re
import typing

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.catalog_models import CatalogCard, GameCollection
from src.core.game_collections import GameCollectionEditor, game_collection_store
from src.core.models import CollectionEntry
from src.services.catalog import PROVIDERS
from src.ui.icons import icon
from src.ui.theme import page_header

CONDITIONS = list(typing.get_args(CollectionEntry.model_fields['condition'].annotation))
NEW_COLLECTION = '__new__'
CARD_STYLE = ('background: var(--oy-surface); border: 1px solid var(--oy-border-soft); border-radius: 6px; '
              'cursor: pointer')


def resolve_game(game: str | None, enabled: list[str]) -> str | None:
    others = [g for g in enabled if g != 'yugioh']
    if game is None:
        return others[0] if others else None
    return game if game in others else None


def game_tabs(current: str, enabled: list[str], base: str) -> None:
    with ui.row().classes('items-center gap-6 q-mb-md'):
        for game in enabled:
            if game == 'yugioh':
                continue
            ui.label(PROVIDERS[game].display_name).classes(
                'oy-mode' + (' active' if game == current else '')
            ).on('click', lambda game=game: ui.navigate.to(base.format(game=game)))


def empty_state(title: str, text: str, button: str, target: str) -> None:
    with ui.card().classes('w-full q-pa-xl items-center text-center'):
        ui.label(title).classes('text-h6')
        ui.label(text).classes('oy-sub')
        ui.button(button, on_click=lambda: ui.navigate.to(target)).props('color=secondary').classes('q-mt-md')


def collection_label(filename: str) -> str:
    return filename[:-5] if filename.endswith('.json') else filename


def collection_exists(filename: str, filenames: list[str]) -> bool:
    # NTFS ignores case: 'main.json' would overwrite 'Main.json'.
    wanted = filename.casefold()
    return any(existing.casefold() == wanted for existing in filenames)


_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_FILENAMES = ({'con', 'prn', 'aux', 'nul'} | {f'com{n}' for n in range(1, 10)}
                       | {f'lpt{n}' for n in range(1, 10)})


def new_collection_filename(name: str) -> str:
    """A file name Windows accepts for any name a person types ('Venta: abril?')."""
    name = _BAD_FILENAME_CHARS.sub('_', name or '').strip().rstrip('. ')
    if not name:
        raise ValueError('Escribe un nombre para la colección.')
    if name.split('.')[0].strip().casefold() in _RESERVED_FILENAMES:
        name = f'_{name}'
    return f'{name}.json'


def catalog_page(game: str | None = None) -> None:
    enabled = enabled_games(load_profile())
    current = resolve_game(game, enabled)
    if current is None:
        if game is not None and resolve_game(None, enabled):
            ui.navigate.to('/catalog')
            return
        page_header('Catálogo', 'Busca cartas de otros juegos y añádelas a tus colecciones.')
        empty_state('Activa un juego en Ajustes', 'Magic y Pokémon están disponibles gratis.', 'Ir a Ajustes',
                    '/settings')
        return

    provider = PROVIDERS[current]
    with ui.row().classes('w-full items-end justify-between'):
        page_header('Catálogo', f'{provider.display_name}: busca una carta y añádela a una colección.')
        with ui.button(on_click=lambda: ui.navigate.to(f'/games/{current}/collection')).props(
                'flat no-caps color=primary'):
            icon('cards-deck')
            ui.label('Mis colecciones').classes('q-ml-xs')
    game_tabs(current, enabled, '/catalog/{game}')

    if not provider.is_available():
        empty_state('Catálogo sin descargar', f'El catálogo de {provider.display_name} aún no está descargado.',
                    'Ir a Ajustes', '/settings')
        return

    state = {'query': '', 'set': None, 'rarity': None}
    with ui.row().classes('w-full items-center gap-3 q-mb-md'):
        search = ui.input(placeholder='Nombre de la carta').props('outlined dense clearable').classes(
            'flex-grow max-w-md')
        set_select = ui.select({}, label='Set', with_input=True, clearable=True).props(
            'outlined dense').classes('w-64')
        rarity_select = ui.select([], label='Rareza', clearable=True).props('outlined dense').classes('w-48')
    count_label = ui.label('').classes('oy-sub q-mb-sm')
    results = ui.element('div').classes('w-full grid gap-3').style(
        'grid-template-columns: repeat(auto-fill, minmax(150px, 1fr))')

    def render(cards: list[CatalogCard]) -> None:
        results.clear()
        count_label.set_text('Sin resultados.' if not cards else f'{len(cards)} cartas')
        with results:
            for card in cards:
                printing = card.printings[0] if card.printings else None
                with ui.column().classes('gap-1 q-pa-sm').style(CARD_STYLE).on(
                        'click', lambda card=card: open_card(card)):
                    if printing and printing.image_url_small:
                        ui.image(printing.image_url_small).classes('w-full').props('fit=contain loading=lazy')
                    ui.label(card.name).classes('text-sm font-medium')
                    if printing:
                        ui.label(f'{printing.set_name} · {len(card.printings)} impresiones').classes(
                            'text-xs').style('color: var(--oy-muted)')

    async def run_search() -> None:
        state['query'] = search.value or ''
        state['set'] = set_select.value
        state['rarity'] = rarity_select.value
        cards = await run.io_bound(provider.search, state['query'], state['set'], state['rarity'], 60)
        render(cards)

    async def load() -> None:
        sets = await run.io_bound(provider.sets)
        set_select.set_options({code: f'{name} ({code})' for code, name in sets})
        cards = await run.io_bound(provider.store.load)
        rarity_select.set_options(sorted({p.rarity for c in cards for p in c.printings if p.rarity}))
        await run_search()

    search.on('keydown.enter', run_search)
    search.on('clear', run_search)
    set_select.on_value_change(run_search)
    rarity_select.on_value_change(run_search)

    def open_card(card: CatalogCard) -> None:
        add_to_collection_dialog(current, card)

    ui.timer(0.01, load, once=True)


def add_to_collection_dialog(game: str, card: CatalogCard) -> None:
    store = game_collection_store.bound()
    filenames = store.list(game)
    printings = {p.printing_id: p for p in card.printings}
    with ui.dialog() as dialog, ui.card().classes('w-full').style('max-width: 640px'):
        with ui.row().classes('w-full no-wrap gap-4'):
            image = ui.image(card.printings[0].image_url if card.printings else '').classes('w-48').props(
                'fit=contain')
            with ui.column().classes('flex-grow gap-2'):
                ui.label(card.name).classes('text-h6')
                printing = ui.select({pid: ' · '.join(x for x in (p.set_name, p.number and f'#{p.number}', p.rarity)
                                                      if x) for pid, p in printings.items()},
                                     label='Impresión', value=card.printings[0].printing_id if card.printings else None
                                     ).props('outlined dense').classes('w-full')
                finish = ui.select([], label='Acabado').props('outlined dense').classes('w-full')
                with ui.row().classes('w-full gap-2 no-wrap'):
                    condition = ui.select(CONDITIONS, label='Condición', value='Near Mint').props(
                        'outlined dense').classes('flex-grow')
                    language = ui.input('Idioma', value='EN').props('outlined dense maxlength=5').classes('w-20')
                    quantity = ui.number('Cantidad', value=1, min=1, max=999, precision=0).props(
                        'outlined dense').classes('w-24')
                options = {f: collection_label(f) for f in filenames}
                options[NEW_COLLECTION] = 'Nueva colección…'
                target = ui.select(options, label='Colección',
                                   value=filenames[0] if filenames else NEW_COLLECTION).props(
                    'outlined dense').classes('w-full')
                new_name = ui.input('Nombre de la nueva colección').props('outlined dense stack-label maxlength=80').classes(
                    'w-full')
                new_name.bind_visibility_from(target, 'value', backward=lambda v: v == NEW_COLLECTION)
                error = ui.label('').classes('oy-form-error text-negative text-sm')

        def sync_printing() -> None:
            chosen = printings.get(printing.value)
            if chosen is None:
                return
            finishes = chosen.finishes or ['nonfoil']
            finish.set_options(finishes, value=finishes[0])
            image.set_source(chosen.image_url or '')

        printing.on_value_change(lambda _: sync_printing())
        sync_printing()

        async def add() -> None:
            try:
                amount = int(quantity.value or 0)
                if not 1 <= amount <= 999:
                    raise ValueError('La cantidad va de 1 a 999.')
                chosen = printings[printing.value]
                if target.value == NEW_COLLECTION:
                    filename = new_collection_filename(new_name.value)
                    if collection_exists(filename, filenames):
                        raise ValueError('Ya tienes una colección con ese nombre.')
                    collection = GameCollection(game=game, name=collection_label(filename))
                else:
                    filename = target.value
                    collection = await run.io_bound(store.load, game, filename)
                GameCollectionEditor.apply_change(collection, card, chosen, finish.value or 'nonfoil', amount,
                                                  condition=condition.value,
                                                  language=(language.value or 'EN').strip().upper())
                await run.io_bound(store.save, game, collection, filename)
            except (ValueError, KeyError) as exc:
                error.set_text(str(exc) if isinstance(exc, ValueError) else 'Elige una impresión.')
                return
            dialog.close()
            ui.notify(f'{amount} × {card.name} añadida a {collection_label(filename)}.', type='positive')

        with ui.row().classes('w-full justify-end gap-2 q-mt-sm'):
            ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
            with ui.button(on_click=add).props('color=secondary no-caps'):
                icon('plus')
                ui.label('Añadir a colección').classes('q-ml-xs')
    dialog.open()
