"""The actions of the collection's multi-select bar: delete, move to another collection, give a storage, edit counts."""

from __future__ import annotations

from nicegui import run, ui

from src.core.models import StorageDefinition
from src.core.persistence import persistence
from src.services.collection_editor import CollectionEditor
from src.ui.icons import icon

NO_STORAGE = '(Sin almacén)'


def _summary(collection, targets) -> tuple[int, int]:
    picked = CollectionEditor.select_entries(collection, targets)
    return len(picked), sum(entry.quantity for _, _, entry in picked)


def _dialog(title: str, subtitle: str = ''):
    dialog = ui.dialog()
    with dialog:
        card = ui.card().classes('w-full max-w-lg gap-3')
        with card:
            ui.label(title).classes('text-lg font-bold')
            if subtitle:
                ui.label(subtitle).classes('text-sm oy-text-body')
    return dialog, card


def _buttons(dialog, label: str, on_click, color: str = 'secondary', icon_name: str = 'check') -> None:
    with ui.row().classes('w-full justify-end gap-2'):
        ui.button('Cancelar', on_click=dialog.close).props('flat no-caps')
        with ui.button(on_click=on_click).props(f'no-caps color={color} id=bulk-confirm'):
            icon(icon_name)
            ui.label(label).classes('q-ml-xs')


def open_delete(page) -> None:
    col = page.state['current_collection']
    stacks, cards = _summary(col, page.bulk.targets())
    dialog, card = _dialog('Eliminar cartas', f'Se quitarán {cards} cartas ({stacks} entradas) de '
                                              f'«{page.collection_label()}». Esta acción no se puede deshacer.')

    async def confirm():
        dialog.close()
        targets = page.bulk.targets()
        await page.bulk_commit(lambda c: CollectionEditor.bulk_remove(c, targets), 'Eliminadas {n} cartas.')

    with card:
        _buttons(dialog, 'Eliminar', confirm, color='negative', icon_name='trash')
    dialog.open()


def open_storage(page) -> None:
    col = page.state['current_collection']
    names = sorted(s.name for s in col.storage_definitions)
    dialog, card = _dialog('Asignar almacén', 'Las cartas marcadas pasan al almacén que elijas.')
    with card:
        choice = ui.select([NO_STORAGE] + names, value=names[0] if names else NO_STORAGE, label='Almacén') \
            .classes('w-full').props('id=bulk-storage')
        fresh = ui.input('…o crea uno nuevo').classes('w-full').props('id=bulk-new-storage')

        async def confirm():
            name = (fresh.value or '').strip()
            storage = name or (None if choice.value == NO_STORAGE else choice.value)
            targets = page.bulk.targets()
            dialog.close()

            def apply(c):
                if storage and not any(s.name == storage for s in c.storage_definitions):
                    c.storage_definitions.append(StorageDefinition(name=storage))
                return CollectionEditor.bulk_assign_storage(c, targets, storage)

            await page.bulk_commit(apply, 'Movidas {n} cartas a ' + (f'«{storage}».' if storage else 'sin almacén.'))

        _buttons(dialog, 'Asignar', confirm, icon_name='package-box')
    dialog.open()


def open_transfer(page) -> None:
    others = [f for f in persistence.list_collections() if f != page.state['selected_file']]
    if not others:
        ui.notify('No hay otra colección a la que mover. Crea una primero.', type='warning')
        return
    dialog, card = _dialog('Mover a otra colección', 'Las cartas marcadas salen de esta colección y se suman a la elegida.')
    with card:
        target = ui.select({f: page.collection_label(f) for f in others}, value=others[0], label='Colección destino') \
            .classes('w-full').props('id=bulk-target')

        async def confirm():
            filename, targets = target.value, page.bulk.targets()
            dialog.close()
            await page.bulk_transfer(filename, targets)

        _buttons(dialog, 'Mover', confirm, icon_name='arrow-right')
    dialog.open()


def open_quantities(page) -> None:
    col = page.state['current_collection']
    picked = CollectionEditor.select_entries(col, page.bulk.targets())
    dialog, card = _dialog('Editar cantidades', 'Cambia cuántas copias tienes de cada una. Con 0 se quita.')
    boxes = []
    with card:
        with ui.scroll_area().classes('w-full').style('max-height: 55vh'):
            for owner, variant, entry in picked:
                with ui.row().classes('w-full items-center no-wrap gap-2 py-1'):
                    with ui.column().classes('gap-0 grow min-w-0'):
                        ui.label(owner.name).classes('text-sm font-medium truncate')
                        ui.label(f'{variant.set_code} · {variant.rarity} · {entry.condition} · {entry.language}'
                                 f'{" · 1st" if entry.first_edition else ""} · {entry.storage_location or "Sin sitio"}'
                                 ).classes('text-xs oy-text-faint truncate')
                    box = ui.number(value=entry.quantity, min=0, step=1, precision=0).props('dense outlined') \
                        .classes('w-24 bulk-qty')
                    boxes.append((owner, variant, entry, box))

        async def confirm():
            changes = [(o.card_id, v.variant_id, e.language, e.condition, e.first_edition, e.storage_location,
                        int(b.value or 0)) for o, v, e, b in boxes if int(b.value or 0) != e.quantity]
            dialog.close()
            if not changes:
                ui.notify('No has cambiado ninguna cantidad.', type='info')
                return

            def apply(c):
                return sum(1 for change in changes if CollectionEditor.set_entry_quantity(c, *change))

            await page.bulk_commit(apply, 'Actualizadas {n} entradas.')

        _buttons(dialog, 'Guardar cantidades', confirm, icon_name='edit')
    dialog.open()
