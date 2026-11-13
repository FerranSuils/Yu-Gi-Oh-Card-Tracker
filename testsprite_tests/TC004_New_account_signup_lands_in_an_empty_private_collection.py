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
        
        # -> Open the registration form using “Crear cuenta” and inspect the fields it displays.
        # Crear cuenta button
        elem = page.get_by_role("button", name="Crear cuenta")
        await elem.click(timeout=10000)
        
        # -> Enter a fresh eligible username and matching passwords, then submit the registration form.
        # Usuario text field
        elem = page.get_by_role("textbox", name="Usuario")
        await elem.wait_for(state="visible", timeout=10000)
        await elem.fill("qauser20261113")
        
        # -> Enter a fresh eligible username and matching passwords, then submit the registration form.
        # Contraseña password field
        elem = page.get_by_role("textbox", name="Contraseña", exact=True)
        await elem.wait_for(state="visible", timeout=10000)
        await elem.fill("TestSprite-2026!")
        
        # -> Enter a fresh eligible username and matching passwords, then submit the registration form.
        # Repite la contraseña password field
        elem = page.get_by_role("textbox", name="Repite la contraseña")
        await elem.wait_for(state="visible", timeout=10000)
        await elem.fill("TestSprite-2026!")
        
        # -> Enter a fresh eligible username and matching passwords, then submit the registration form.
        # Crear mi cuenta button
        elem = page.get_by_role("button", name="Crear mi cuenta")
        await elem.click(timeout=10000)
        
        # -> Enter a different eligible username in the “Usuario” field and check whether username suggestions appear.
        # Usuario text field
        elem = page.get_by_role("textbox", name="Usuario")
        await elem.wait_for(state="visible", timeout=10000)
        await elem.fill("qauser20261113a")
        
        # -> Submit the registration form with the new username and verify the result.
        # Crear mi cuenta button
        elem = page.get_by_role("button", name="Crear mi cuenta")
        await elem.click(timeout=10000)
        
        # --> Assertions to verify final state
        
        # --> The new account is signed in on the collection page.
        # Assert-outcome: not verified — the export-time check could not be evaluated
        # Assert: The new account should land on the collection page.
        await expect(page).to_have_url(re.compile("/collection"), timeout=15000), "The new account should land on the collection page."
        # Assert-outcome: not verified — the export-time check could not be evaluated
        # Assert: The collection page should show the signed-in account name.
        await expect(page.locator("#app").nth(0)).to_contain_text("qauser20261113a", timeout=15000), "The collection page should show the signed-in account name."
        
        # --> The collection has no owned cards.
        # Assert-outcome: not verified — the export-time check could not be evaluated
        # Assert: The collection should show zero owned cards.
        await expect(page.locator("#app").nth(0)).to_contain_text("Total QTY 0", timeout=15000), "The collection should show zero owned cards."
        await asyncio.sleep(5)

    finally:
        if context:
            await context.close()
        if browser:
            await browser.close()
        if pw:
            await pw.stop()

asyncio.run(run_test())
    