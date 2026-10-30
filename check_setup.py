"""Isolated browser check: empty setup, persistence, add flow, mobile, reopen."""
from pathlib import Path
import tempfile
import threading
from playwright.sync_api import sync_playwright,expect
import server

with tempfile.TemporaryDirectory() as folder:
    server.DB=Path(folder)/'setup.sqlite3';server.initialize()
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True)
            page=browser.new_page(viewport=dict(width=390,height=844));errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{http.server_port}')
            wizard=page.locator('#setup-wizard');expect(wizard).to_be_visible()
            expect(page.locator('article.project')).to_have_count(0)
            for step in range(2):
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                page.locator('#setup-next').click()
            page.locator('#setup-back').click();expect(page.locator('#setup-progress')).to_have_text('Step 2 of 3')
            page.locator('#setup-next').click();page.locator('#setup-next').click()
            expect(wizard).not_to_be_visible();assert server.load_projects()==[]
            page.reload();expect(wizard).not_to_be_visible()
            page.locator('#setup-help').click();expect(wizard).to_be_visible()
            page.locator('#setup-next').click();page.locator('#setup-next').click()
            page.locator('input[value="add"]').check();page.locator('#setup-next').click()
            expect(page.locator('#editor')).to_be_visible()
            page.locator('#project-form input[name="name"]').fill('My first project')
            page.locator('#project-form button[type="submit"]').click()
            expect(page.locator('article.project')).to_have_count(1)
            page.reload();page.wait_for_load_state('networkidle');expect(wizard).not_to_be_visible()
            assert server.load_projects()[0]['name']=='My first project'
            assert not errors,errors
            browser.close()
    finally:http.shutdown();http.server_close()
print('Setup browser checks passed; no personal database or native services used.')
