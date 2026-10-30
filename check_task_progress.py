"""Real progress semantics and indeterminate fallback; isolated data, no messages."""
from pathlib import Path
import tempfile,threading
from playwright.sync_api import sync_playwright,expect
import server

with tempfile.TemporaryDirectory() as folder:
    server.DB=Path(folder)/'progress.sqlite3';server.initialize()
    p=server.new_project('Task progress fixture');p['workState']=dict(phase='working',threadId='chat',turnId='current',taskProgress=dict(turnId='current',steps=[dict(step='Inspect the project',status='completed'),dict(step='Implement <script> as text',status='in_progress'),dict(step='Verify the result',status='pending')],completed=1,total=3));server.save(p)
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1100,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle')
            progress=page.locator('.task-progress');expect(progress).to_contain_text('1 of 3 plan steps complete');expect(progress.locator('progress')).to_have_attribute('value','1');expect(progress.locator('progress')).to_have_attribute('max','3')
            progress.locator('summary').click();expect(progress.locator('.task-plan-steps')).to_contain_text('Completed');expect(progress.locator('.task-current-step')).to_have_text('Implement <script> as text');expect(progress.locator('script')).to_have_count(0)
            for theme in ['light','dark']:
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme);assert progress.is_visible()
            page.set_viewport_size({'width':390,'height':844});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            Path('output').mkdir(exist_ok=True);page.screenshot(path='output/task-progress-mobile.png',full_page=True)
            page.set_viewport_size({'width':1100,'height':900})
            # Completing all plan steps never declares the Codex turn complete.
            p['workState']['taskProgress']['steps']=[dict(step='Done step',status='completed')];server.save(p);page.evaluate('load()')
            expect(progress).to_contain_text('1 of 1 plan steps complete');expect(progress).to_contain_text('Codex is still working');expect(page.locator('.work-status')).to_contain_text('Working')
            # A new turn must not reuse the old plan, even if saved metadata lags.
            p['workState']['turnId']='next-turn';server.save(p);page.evaluate('load()')
            expect(progress.locator('progress')).to_have_count(0);expect(progress).to_contain_text('Working');expect(progress).to_contain_text('No measurable plan')
            expect(progress.locator('[role="progressbar"]')).not_to_have_attribute('aria-valuenow',__import__('re').compile('.+'))
            page.emulate_media(reduced_motion='reduce');assert progress.locator('.task-progress-pulse').evaluate('n=>getComputedStyle(n).animationName')=='none'
            # A monitoring failure also hides any old numerical progress.
            p['workState']['taskProgress']['turnId']='next-turn';p['workState']['monitorError']='Connection unavailable';server.save(p);page.evaluate('load()');expect(progress).to_contain_text('Checking status');expect(progress.locator('progress')).to_have_count(0)
            p['workState']={'phase':'idle','outcome':'completed'};server.save(p);page.evaluate('load()');expect(progress).to_have_count(0)
            page.set_viewport_size({'width':390,'height':844});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert not errors,errors
            browser.close()
        print('PASS: explicit step bar/counts, current/completed steps, escaped text, no fake task completion, old-turn and monitor-error fallback, no invented percentage, reduced motion, themes and mobile; no messages sent')
    finally:http.shutdown();http.server_close();worker.join()
