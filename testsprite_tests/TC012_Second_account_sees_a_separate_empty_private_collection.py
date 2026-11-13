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
        
        # -> Open the registration form by selecting “Crear cuenta.”
        # Crear cuenta button
        elem = page.get_by_role("button", name="Crear cuenta")
        await elem.click(timeout=10000)
        
        # -> Enter a fresh lowercase username and matching passwords in the registration form, then create the account.
        # Usuario text field
        elem = page.get_by_role("textbox", name="Usuario")
        await elem.wait_for(state="visible", timeout=10000)
        await elem.fill("qaopenyu26")
        
        # -> Enter a fresh lowercase username and matching passwords in the registration form, then create the account.
        # Contraseña password field
        elem = page.get_by_role("textbox", name="Contraseña", exact=True)
        await elem.wait_for(state="visible", timeout=10000)
        await elem.fill("TestSprite-2026!")
        
        # -> Enter a fresh lowercase username and matching passwords in the registration form, then create the account.
        # Repite la contraseña password field
        elem = page.get_by_role("textbox", name="Repite la contraseña")
        await elem.wait_for(state="visible", timeout=10000)
        await elem.fill("TestSprite-2026!")
        
        # -> Enter a fresh lowercase username and matching passwords in the registration form, then create the account.
        # Crear mi cuenta button
        elem = page.get_by_role("button", name="Crear mi cuenta")
        await elem.click(timeout=10000)
        
        # -> Turn on the “Owned” filter and verify the new account’s collection contains no owned-card entries.
        # Owned toggle
        elem = page.get_by_role("switch", name="Owned")
        await elem.click(timeout=10000)
        
        # --> Assertions to verify final state
        
        # --> The new account’s collection is empty.
        # Assert-outcome: not verified — the export-time check could not be evaluated
        # Assert: The collection shows zero unique cards.
        await expect(page.locator("xpath=/html/body/div[1]/div/div/main/div/div[1]/div[3]/div[4]/div[1]/div[3]/div[2]").nth(0)).to_have_text("0", timeout=15000), "The collection shows zero unique cards."
        
        # --> The new account lands on its collection page.
        # Assert-outcome: not verified — the export-time check could not be evaluated
        # Assert: The account is on the collection page.
        await expect(page).to_have_url(re.compile("/collection"), timeout=15000), "The account is on the collection page."
        await asyncio.sleep(5)

    finally:
        if context:
            await context.close()
        if browser:
            await browser.close()
        if pw:
            await pw.stop()

asyncio.run(run_test())
    