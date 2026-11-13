import asyncio
import types
from pathlib import Path

import pytest

from src.core.catalog_models import GameCollection
from src.core.collection_sync import StaleCollectionError
from src.core.game_collections import GameCollectionStore
from src.core.models import Collection
from src.core.persistence import PersistenceManager


@pytest.fixture
def manager(tmp_path):
    manager = PersistenceManager(str(tmp_path / 'collections'), str(tmp_path / 'decks'))
    manager.save_collection(Collection(name='Tienda'), 'tienda.json')
    return manager


def test_an_older_copy_cannot_overwrite_a_newer_save(manager):
    first, second = manager.load_collection('tienda.json'), manager.load_collection('tienda.json')
    first.description = 'import'
    manager.save_collection(first, 'tienda.json')
    second.description = 'otra pestaña'
    with pytest.raises(StaleCollectionError, match='otra ventana'):
        manager.save_collection(second, 'tienda.json')
    assert manager.load_collection('tienda.json').description == 'import'


def test_the_same_copy_can_save_again_and_again(manager):
    collection = manager.load_collection('tienda.json')
    for text in ('a', 'b', 'c'):
        collection.description = text
        manager.save_collection(collection, 'tienda.json')
    assert manager.load_collection('tienda.json').description == 'c'


def test_a_new_collection_and_another_file_are_not_checked(manager):
    stale = manager.load_collection('tienda.json')
    manager.save_collection(manager.load_collection('tienda.json'), 'tienda.json')
    manager.save_collection(stale, 'copia.json')                         # another file
    manager.save_collection(Collection(name='Nueva'), 'tienda.json')     # deliberate replacement
    assert manager.load_collection('tienda.json').name == 'Nueva'


def test_game_collections_are_guarded_too(tmp_path):
    store = GameCollectionStore(lambda: str(tmp_path))
    store.save('magic', GameCollection(game='magic', name='Caja'), 'caja.json')
    first, second = store.load('magic', 'caja.json'), store.load('magic', 'caja.json')
    first.description = 'venta'
    store.save('magic', first, 'caja.json')
    store.save('magic', first, 'caja.json')
    with pytest.raises(StaleCollectionError):
        store.save('magic', second, 'caja.json')
    assert store.load('magic', 'caja.json').description == 'venta'


def test_a_stale_save_tells_the_page_and_still_fails():
    from src.ui.stale_save import install_stale_save_notice

    async def io_bound(callback, *args):
        return callback(*args)

    def stale():
        raise StaleCollectionError('x')

    run, seen = types.SimpleNamespace(io_bound=io_bound), []
    install_stale_save_notice(run, on_stale=lambda: seen.append(1))
    wrapped = run.io_bound
    install_stale_save_notice(run, on_stale=lambda: seen.append(2))
    assert run.io_bound is wrapped

    async def scenario():
        assert await run.io_bound(len, 'abc') == 3
        with pytest.raises(StaleCollectionError):
            await run.io_bound(stale)

    asyncio.run(scenario())
    assert seen == [1]


def test_main_installs_the_notice():
    source = Path('main.py').read_text(encoding='utf-8')
    assert 'install_stale_save_notice()' in source
    assert source.index('install_context_aware_io_bound()') < source.index('install_stale_save_notice()')


def test_page_context_enters_the_page_when_there_is_one():
    from src.ui.stale_save import page_context

    class Page:
        events = []

        def __enter__(self):
            self.events.append('in')

        def __exit__(self, *exc):
            self.events.append('out')

    with page_context(Page()):
        Page.events.append('save')
    with page_context(None):
        Page.events.append('no page')
    assert Page.events == ['in', 'save', 'out', 'no page']


@pytest.mark.parametrize('page', ['bulk_add', 'collection', 'storage'])
def test_debounced_saves_run_inside_their_page(page):
    # asyncio.create_task drops NiceGUI's page context, so a refused save could not tell the user.
    source = Path('src/ui', f'{page}.py').read_text(encoding='utf-8')
    body = source[source.index('async def delayed_save():'):]
    assert 'page = current_page()' in source
    assert 'with page_context(page):\n                    await self._perform_save()' in body
