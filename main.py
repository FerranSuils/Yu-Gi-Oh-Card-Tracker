import sys
import os
import multiprocessing
from nicegui import ui, app
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

# Ensure src is in the python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.core.logging_setup import setup_logging
setup_logging()
from src.core.io_context import install_context_aware_io_bound
install_context_aware_io_bound()
from src.ui.stale_save import install_stale_save_notice
install_stale_save_notice()

from src.ui.layout import create_layout
from src.ui.dashboard import dashboard_page
from src.ui.collection import collection_page
from src.ui.deck_builder import deck_builder_page
from src.ui.import_tools import import_tools_page
from src.ui.csv_suite import csv_suite_page
from src.ui.pos import pos_page
from src.ui.sales import paid_page, sales_page
from src.ui.customers import customers_page
from src.ui.buylist import buylist_page
from src.ui.consignment import consignment_page
from src.ui.orders import orders_page
from src.ui.events import events_page
from src.ui.reports import reports_page
from src.ui.decklist import decklist_page
from src.ui.kiosk import kiosk_page
from src.ui.shop_map import map_page
from src.ui.browse_sets import browse_sets_page
from src.ui.bulk_add import bulk_add_page
from src.ui.scan import scan_page
from src.ui.db_editor import db_editor_page
from src.ui.storage import storage_page
from src.ui.auth import complete_login_callback, login_page, register_page
from src.ui.settings import settings_page
from src.ui.catalog import catalog_page
from src.ui.game_collection import game_collection_page
from src.ui import pwa
from src.ui.novedades import novedades_page
from src.ui.theme import install_global_styles
from src.api.routes import router as api_router
from src.services.shop.public_api import build_router as build_shop_api
from src.services.auth_middleware import AuthenticationMiddleware
from src.services.auth_service import get_storage_secret

app.include_router(api_router)
app.include_router(build_shop_api())
app.add_middleware(AuthenticationMiddleware)
install_global_styles()

# Nightly market prices and automatic repricing (set OPENYUGI_DISABLE_PRICE_SCHEDULER=1 to turn off).
if os.environ.get('OPENYUGI_DISABLE_PRICE_SCHEDULER', '').lower() not in {'1', 'true', 'yes'}:
    from src.services.prices.scheduler import start_scheduler
    app.on_startup(start_scheduler)

from src.services.billing.scheduler import start_scheduler as start_billing_scheduler
app.on_startup(start_billing_scheduler)


async def start_loop_watchdog():
    # Logs the stacks of all threads whenever the loop stops answering for 5 s or more.
    from src.services.loop_watchdog import LoopWatchdog
    import asyncio
    LoopWatchdog(asyncio.get_running_loop()).start()


app.on_startup(start_loop_watchdog)

@ui.page('/facturacion')
def facturacion(request: Request):
    from src.ui.billing import billing_page
    create_layout(lambda: billing_page(str(request.base_url)))

@ui.page('/login')
def login(request: Request):
    login_page(request.query_params.get('next'))


@ui.page('/registro')
def registro(request: Request):
    register_page(request.query_params.get('next'))


@ui.page('/login/callback')
async def login_callback(request: Request):
    destination = await complete_login_callback(
        request.query_params.get('token'), request.query_params.get('next')
    )
    return RedirectResponse(destination or '/login', status_code=303)

@ui.page('/')
def home():
    create_layout(dashboard_page)

@ui.page('/collection')
def collection():
    create_layout(collection_page)

@ui.page('/storage')
def storage():
    create_layout(storage_page)

@ui.page('/sets')
def sets():
    create_layout(browse_sets_page)

@ui.page('/decks')
def decks():
    create_layout(deck_builder_page)

@ui.page('/bulk_add')
def bulk_add():
    create_layout(bulk_add_page)

@ui.page('/import')
def import_tools():
    create_layout(import_tools_page)

@ui.page('/csv')
def csv_suite():
    create_layout(csv_suite_page)

@ui.page('/tpv')
def tpv():
    create_layout(pos_page)

@ui.page('/ventas')
def ventas():
    create_layout(sales_page)

@ui.page('/clientes')
def clientes():
    create_layout(customers_page)


@ui.page('/compras')
def compras():
    create_layout(buylist_page)


@ui.page('/consigna')
def consigna():
    create_layout(consignment_page)


@ui.page('/pedidos')
def pedidos():
    create_layout(orders_page)


@ui.page('/eventos')
def eventos():
    create_layout(events_page)


@ui.page('/informes')
def informes():
    create_layout(reports_page)


@ui.page('/lista')
def lista():
    create_layout(decklist_page)


@ui.page('/kiosko/{token}')
def kiosko(token: str):
    kiosk_page(token)


@ui.page('/mapa')
def mapa():
    map_page()


@ui.page('/tpv/pagado')
def tpv_pagado():
    paid_page()

@ui.page('/scan')
def scan():
    create_layout(scan_page)

@ui.page('/db_editor')
def db_editor():
    create_layout(db_editor_page)

@ui.page('/catalog')
def catalog_index():
    create_layout(lambda: catalog_page(None))

@ui.page('/catalog/{game}')
def catalog_game(game: str):
    create_layout(lambda: catalog_page(game))

@ui.page('/games/{game}/collection')
def game_collection(game: str):
    create_layout(lambda: game_collection_page(game))

@ui.page('/settings')
def settings():
    create_layout(settings_page)

@ui.page('/novedades')
def novedades():
    create_layout(novedades_page)

# Daily refresh of reference data (set release dates). Set OPENYUGI_DISABLE_PRICE_SCHEDULER=1 to turn off.
if os.environ.get('OPENYUGI_DISABLE_PRICE_SCHEDULER', '').lower() not in {'1', 'true', 'yes'}:
    from src.services.reference.scheduler import start_scheduler
    app.on_startup(start_scheduler)

# Serve images
os.makedirs('data/images', exist_ok=True)
os.makedirs('data/img', exist_ok=True)
os.makedirs('data/collections/storage', exist_ok=True)
os.makedirs('data/flags', exist_ok=True)
app.add_static_files('/fonts', 'static/fonts')
app.add_static_files('/brand', 'static/brand')
app.add_static_files('/images', 'data/images')
app.add_static_files('/data/img', 'data/img') # Serve data/img for Art Match if used
app.add_static_files('/sets', 'data/sets')
app.add_static_files('/storage', 'data/collections/storage')
app.add_static_files('/flags', 'data/flags')
if os.environ.get('OPENYUGI_ENABLE_DEBUG_STATIC', '').lower() in {'1', 'true', 'yes'}:
    app.add_static_files('/debug', 'debug')

pwa.register_routes(app)

# Handle Chrome DevTools probe to prevent 404 warnings
@app.get('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools_probe():
    return JSONResponse(content={})

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # Disable reload to prevent restart loops when writing to data/ directory (images, db)
    ui.run(
        title='OpenYuGi — tu colección de Yu-Gi-Oh, gratis',
        favicon='static/brand/mark.svg',
        host=os.environ.get('OPENYUGI_HOST', '0.0.0.0'),
        port=int(os.environ.get('OPENYUGI_PORT', '8080')),
        reload=False,
        # The server can stall 20 s or more (IIS logs show it); the default 3 s made the socket ping
        # expire, deleting the client and reloading the page. 120 s covers those stalls.
        reconnect_timeout=120.0,
        # On Windows uvicorn uses the Proactor loop, whose accept loop closes the
        # listening socket after a transient WinError 64. The process then stays
        # alive but stops accepting connections, and IIS answers 502 everywhere.
        loop='asyncio:SelectorEventLoop' if sys.platform == 'win32' else 'auto',
        show=os.environ.get('OPENYUGI_OPEN_BROWSER', '1').lower() not in {'0', 'false', 'no'},
        storage_secret=get_storage_secret(),
        session_middleware_kwargs={
            'same_site': 'lax',
            'https_only': os.environ.get('OPENYUGI_SECURE_COOKIES', '').lower() in {'1', 'true', 'yes'},
        },
    )
