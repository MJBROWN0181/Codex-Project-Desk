"""Real folder discovery and browser choice; agent execution is intercepted."""
import json
from pathlib import Path
import tempfile
import threading
from playwright.sync_api import sync_playwright,expect
import server

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);server.DB=root/'scope.sqlite3';server.initialize()
    projectroot=root/'source';projectroot.mkdir()
    backend=projectroot/'backend';backend.mkdir();(backend/'package.json').write_text('{}')
    p=server.update(dict(name='Folder selection fixture',path=str(projectroot)))
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport=dict(width=390,height=844));errors=[];calls=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def intercept(route):
                calls.append(route.request.post_data_json);route.fulfill(json=p)
            page.route('**/api/project/control',intercept)
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle')
            for name,choice,expected in [('Finish agent team','all','all'),('Panel of advisors','1',[str(backend)])]:
                page.get_by_role('button',name=name,exact=True).click()
                dialog=page.locator('.audit-folder-picker');expect(dialog).to_be_visible()
                expect(dialog).to_contain_text(str(backend))
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                dialog.locator(f'input[value="{choice}"]').check()
                dialog.get_by_role('button',name='Start project review').click()
                expect(dialog).to_have_count(0);page.wait_for_load_state('networkidle')
                assert calls[-1]['auditFolders']==expected,calls
            before=len(calls);page.get_by_role('button',name='Panel of advisors',exact=True).click()
            page.locator('.audit-folder-picker').get_by_role('button',name='Cancel').click()
            assert len(calls)==before
            assert not errors,errors
            browser.close()
    finally:http.shutdown();http.server_close()
print('PASS: both audit folder pickers, all/single selection, mobile, cancellation; no real agents run.')
