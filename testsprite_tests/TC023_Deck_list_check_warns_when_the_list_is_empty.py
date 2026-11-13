import asyncio
import re
from playwright import async_api
from playwright.async_api import expect

async def run_test():
    pw = None
    browser = None
    context = None

    try:
        # Start a Playwright session in asynchronous mode
        pw = await async_api.async_playwright().start()

        # Launch a Chromium browser in headless mode with custom arguments
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--window-size=1280,720",
                "--disable-dev-shm-usage",
                "--ipc=host",
                "--single-process"
            ],
        )

        # Create a new browser context (like an incognito window)
        context = await browser.new_context()
        # Wider default timeout to match the agent's DOM-stability budget;
        # auto-waiting Playwright APIs (expect, locator.wait_for) inherit this.
        context.set_default_timeout(15000)

        # Open a new page in the browser context
        page = await context.new_page()

        # Interact with the page elements to simulate user flow
        # -> navigate
        await page.goto("http://localhost:8206/login")
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        
        # -> Enter the provided test username and password, then sign in using “Entrar al mostrador”.
        # Usuario text field
        elem = page.get_by_role("textbox", name="Usuario")
        await elem.wait_for(state="visible", timeout=10000)
        await elem.fill("testsprite")
        
        # -> Enter the provided test username and password, then sign in using “Entrar al mostrador”.
        # Contraseña password field
        elem = page.get_by_role("textbox", name="Contraseña")
        await elem.wait_for(state="visible", timeout=10000)
        await elem.fill("TestSprite-2026!")
        
        # -> Enter the provided test username and password, then sign in using “Entrar al mostrador”.
        # Entrar al mostrador button
        elem = page.get_by_role("button", name="Entrar al mostrador")
        await elem.click(timeout=10000)
        
        # -> Open the “Más” navigation menu to find the Lista page.
        # expand_more Más button
        elem = page.get_by_role("button", name="Más")
        await elem.click(timeout=10000)
        
        # -> Open “Lista de mazo” from the “Más” menu and inspect its empty stock-check form.
        # Lista de mazo
        elem = page.get_by_text("Lista de mazo")
        await elem.click(timeout=10000)
        
        # -> Click “Comprobar stock” with the list left empty and verify the warning message.
        # Comprobar stock button
        elem = page.get_by_role("button", name="Comprobar stock")
        await elem.click(timeout=10000)
        
        # --> Assertions to verify final state
        
        # --> El panel de la tienda carga con la sesión de testsprite iniciada.
        # Assert-outcome: not verified — the export-time check could not be evaluated
        # Assert: El encabezado muestra la sesión de testsprite iniciada.
        await expect(page.locator("#app").nth(0)).to_contain_text("testsprite", timeout=15000), "El encabezado muestra la sesi\u00f3n de testsprite iniciada."
        
        # --> Al comprobar una lista vacía, aparece el aviso de pegar una lista con una carta por línea.
        # Assert-outcome: not verified — the export-time check could not be evaluated
        # Assert: Se muestra el aviso para pegar una lista con una carta por línea.
        await expect(page.locator("#app").nth(0)).to_contain_text("Pega una lista: una carta por l\u00ednea, con el n\u00famero de copias delante.", timeout=15000), "Se muestra el aviso para pegar una lista con una carta por l\u00ednea."
        await asyncio.sleep(5)

    finally:
        if context:
            await context.close()
        if browser:
            await browser.close()
        if pw:
            await pw.stop()

asyncio.run(run_test())
    