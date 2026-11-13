"""Collections of every game except Yu-Gi-Oh."""

from __future__ import annotations

from nicegui import run, ui

from src.core.account_profile import enabled_games, load_profile
from src.core.account_scope import account_root
from src.core.catalog_models import GameCollection
from src.core.collection_sync import RevisionWatcher
from src.core.game_collections import GameCollectionEditor, game_collection_store
from src.services.catalog import PROVIDERS
from src.ui.catalog import CARD_STYLE, collection_exists, collection_label, empty_state, game_tabs, new_collection_filename, resolve_game
from src.services.repricing import base_price, quote_for
from src.core.pricing_models import PricingRule
from src.ui.components.pricing_bar import format_money, load_price_context, render_pricing_bar
from src.ui.icons import icon
from src.ui.theme import page_header


def game_collection_page(game: str) -> None:
    enabled = enabled_games(load_profile())
    if resolve_game(game, enabled) != game:
        ui.navigate.to('/catalog')
        return
    provider = PROVIDERS[game]
    store = game_collection_store.bound()
    state: dict = {'file': None, 'collection': None, 'prices': {}, 'market': 'cardmarket'}
    root = account_root()

    with ui.row().classes('w-full items-end justify-between'):
        page_header('Mis colecciones', provider.display_name)
        with ui.button(on_click=lambda: ui.navigate.to(f'/catalog/{game}')).props('flat no-caps color=primary'):
            icon('search')
            ui.label('Buscar en el catálogo').classes('q-ml-xs')
    game_tabs(game, enabled, '/games/{game}/collection')

    with ui.row().classes('w-full items-center gap-3 q-mb-md'):
        picker = ui.select({}, label='Colección').props('outlined dense').classes('w-64')
        with ui.button(on_click=lambda: new_dialog.open()).props('flat no-caps color=primary'):
            icon('plus')
            ui.label('Nueva colección').classes('q-ml-xs')
        delete_button = ui.button(on_click=lambda: confirm_dialog.open()).props('flat no-caps color=negative')
        with delete_button:
            icon('trash')
            ui.label('Borrar colección').classes('q-ml-xs')
    summary = ui.label('').classes('oy-sub q-mb-sm')
    pricing = ui.element('div').classes('w-full')
    grid = ui.element('div').classes('w-full grid gap-3').style(
        'grid-template-columns: repeat(auto-fill, minmax(170px, 1fr))')

    def image_for(card_id: str, printing_id: str) -> str | None:
        card = provider.get(card_id)
        if card is None or not card.printings:
            return None
        printing = next((p for p in card.printings if p.printing_id == printing_id), card.printings[0])
        return printing.image_url_small

    def render() -> None:
        grid.clear()
        collection: GameCollection | None = state['collection']
        delete_button.set_visibility(collection is not None)
        if collection is None:
            summary.set_text('')
            with grid:
                ui.label('Aún no tienes colecciones de este juego. Crea una o añade cartas desde el catálogo.'
                         ).classes('oy-sub')
            return
        summary.set_text(f'{collection.total_cards} cartas · {len(collection.cards)} distintas')
        with grid:
            if not collection.cards:
                ui.label('Colección vacía. Busca cartas en el catálogo para añadirlas.').classes('oy-sub')
            for card in collection.cards:
                for variant in card.variants:
                    for entry in variant.entries:
                        with ui.column().classes('gap-1 q-pa-sm').style(CARD_STYLE.replace('cursor: pointer', '')):
                            source = image_for(card.card_id, variant.printing_id)
                            if source:
                                ui.image(source).classes('w-full').props('fit=contain loading=lazy')
                            ui.label(card.name).classes('text-sm font-medium')
                            details = ' · '.join(x for x in (variant.set_code.upper(),
                                                             variant.number and f'#{variant.number}',
                                                             variant.finish, entry.condition, entry.language) if x)
                            ui.label(details).classes('text-xs').style('color: var(--oy-muted)')
                            market_value = base_price(PricingRule(), quote_for(
                                state['prices'].get(variant.printing_id), variant.finish))
                            if market_value is not None or entry.list_price is not None:
                                with ui.row().classes('items-center gap-1 text-xs oy-mono'):
                                    icon('trending-up', 12)
                                    ui.label(format_money(market_value, state['market']))
                                    if entry.list_price is not None:
                                        icon('tag', 12)
                                        ui.label(format_money(entry.list_price, state['market'])).classes(
                                            'text-weight-bold')
                                    if entry.price_locked:
                                        icon('lock', 12)
                            with ui.row().classes('w-full items-center justify-between'):
                                ui.label(f'× {entry.quantity}').classes('oy-mono text-sm')
                                with ui.button(on_click=lambda c=card, v=variant, e=entry: remove_one(c, v, e)).props(
                                        'flat dense round color=primary').tooltip('Quitar una'):
                                    icon('minus', 16)

    async def remove_one(card, variant, entry) -> None:
        catalog_card = provider.get(card.card_id)
        printing = next((p for p in (catalog_card.printings if catalog_card else []) if p.printing_id ==
                         variant.printing_id), None)
        if catalog_card is None or printing is None:
            from src.core.catalog_models import CatalogCard, CatalogPrinting
            catalog_card = CatalogCard(game=game, card_id=card.card_id, name=card.name)
            printing = CatalogPrinting(printing_id=variant.printing_id, set_code=variant.set_code, set_name='')
        GameCollectionEditor.apply_change(state['collection'], catalog_card, printing, variant.finish, -1,
                                          condition=entry.condition, language=entry.language,
                                          first_edition=entry.first_edition, storage_location=entry.storage_location)
        await run.io_bound(store.save, game, state['collection'], state['file'])
        render()

    async def save_current() -> None:
        await run.io_bound(store.save, game, state['collection'], state['file'])
        render()

    async def select(filename: str | None) -> None:
        state['file'] = filename
        state['collection'] = await run.io_bound(store.load, game, filename) if filename else None
        context = await run.io_bound(load_price_context, root, game)
        state['prices'], state['market'] = context['prices'], context['market']
        render()
        render_pricing_bar(pricing, state['collection'], game, save_current)
        watcher.changed()  # what we just loaded is the baseline

    # The nightly reprice may rewrite this file; reload rather than later saving an older copy.
    watcher = RevisionWatcher(lambda: store.path(game, state['file']) if state['file'] else None)

    async def reload_if_changed_elsewhere() -> None:
        if watcher.changed():
            ui.notify('Los precios de esta colección se han actualizado.', type='info')
            await select(state['file'])

    ui.timer(30, reload_if_changed_elsewhere)

    async def reload(selected: str | None = None) -> None:
        # Load the catalog off the UI thread; provider.get() below then reads memory only.
        await run.io_bound(provider.store.load)
        files = await run.io_bound(store.list, game)
        picker.set_options({f: collection_label(f) for f in files},
                           value=selected if selected in files else (files[0] if files else None))
        if not files:
            await select(None)

    picker.on_value_change(lambda e: select(e.value))

    with ui.dialog() as new_dialog, ui.card().classes('w-96'):
        ui.label('Nueva colección').classes('text-h6')
        name = ui.input('Nombre').props('outlined dense maxlength=80').classes('w-full')
        new_error = ui.label('').classes('oy-form-error text-negative text-sm')

        async def create() -> None:
            try:
                filename = new_collection_filename(name.value)
                if collection_exists(filename, await run.io_bound(store.list, game)):
                    raise ValueError('Ya tienes una colección con ese nombre.')
                await run.io_bound(store.save, game,
                                   GameCollection(game=game, name=collection_label(filename)), filename)
            except ValueError as exc:
                new_error.set_text(str(exc))
                return
            new_dialog.close()
            name.set_value('')
            await reload(filename)

        with ui.row().classes('w-full justify-end'):
            ui.button('Cancelar', on_click=new_dialog.close).props('flat no-caps')
            ui.button('Crear', on_click=create).props('color=secondary no-caps')

    with ui.dialog() as confirm_dialog, ui.card().classes('w-96'):
        ui.label('¿Borrar esta colección?').classes('text-h6')
        ui.label('Se borran todas sus cartas. No se puede deshacer.').classes('oy-sub')

        async def delete() -> None:
            await run.io_bound(store.delete, game, state['file'])
            confirm_dialog.close()
            await reload()

        with ui.row().classes('w-full justify-end'):
            ui.button('Cancelar', on_click=confirm_dialog.close).props('flat no-caps')
            ui.button('Borrar', on_click=delete).props('color=negative no-caps')

    if not provider.is_available():
        empty_state('Catálogo sin descargar', 'Sin catálogo no se pueden mostrar imágenes ni añadir cartas.',
                    'Ir a Ajustes', '/settings')

    ui.timer(0.01, reload, once=True)
