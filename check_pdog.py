"""PDog status and interaction checks; isolated data, no Codex messages."""
from pathlib import Path
import tempfile
import threading
from playwright.sync_api import sync_playwright, expect
import server

with tempfile.TemporaryDirectory() as folder:
    server.DB=Path(folder)/'pdog.sqlite3';server.initialize()
    samples=[('Ready',{}),('Working',{'workState':{'phase':'working','detail':'Implementing the reviewed step.'},'workPaused':True}),('Thinking',{'workState':{'phase':'operation','operation':'finish-team','detail':'Reviewing project evidence.'}}),('Blocked',{'blocker':'Need a decision <script>not executable</script>'}),('Paused',{'workPaused':True}),('Finished',{'workState':{'phase':'idle','outcome':'completed','completedAt':server.now()}})]
    for name,fields in samples:
        p=server.new_project(name);p.update(fields);server.save(p)
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1280,'height':1100})
            errors=[];writes=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle')
            expect(page.locator('.pdog')).to_have_count(6)
            response=page.request.get(f'http://127.0.0.1:{http.server_port}/pdog-poses.png')
            assert response.status==200 and response.body().startswith(bytes([137,80,78,71]))
            for name,pose in [('Ready','ready'),('Working','working'),('Thinking','thinking'),('Blocked','blocked'),('Paused','paused'),('Finished','done')]:
                card=page.locator('article').filter(has=page.get_by_role('heading',name=name,exact=True))
                expect(card.locator('.pdog-'+pose)).to_be_visible()
                button=card.locator('.pdog');button.focus();button.press('Enter')
                expect(page.locator('#pdog-status')).to_be_visible()
                expect(page.locator('#pdog-status-project')).to_have_text(name)
                if name=='Working':expect(page.locator('#pdog-status-detail')).to_contain_text('current turn can finish')
                if name=='Blocked':
                    expect(page.locator('#pdog-status-detail')).to_contain_text('<script>not executable</script>')
                    expect(page.locator('#pdog-status script')).to_have_count(0)
                if name=='Finished':expect(page.locator('#pdog-status-detail')).to_contain_text('does not mean the entire project is complete')
                page.keyboard.press('Escape');expect(page.locator('#pdog-status')).to_be_hidden();expect(button).to_be_focused()
            # Attention wins over pause; active work wins over an old blocker.
            assert page.evaluate("pdogState({workState:{phase:'attention'},workPaused:true}).pose")=='blocked'
            assert page.evaluate("pdogState({workState:{phase:'working'},blocker:'old blocker'}).pose")=='working'
            assert page.evaluate("pdogState({websiteHealth:{state:'down'}}).pose")=='blocked'
            assert page.evaluate("pdogState({status:'Complete'}).label")=='Project marked complete'
            assert page.evaluate("pdogState({status:'Paused'}).pose")=='paused'
            page.emulate_media(reduced_motion='reduce')
            assert page.locator('.pdog-working').evaluate('n=>getComputedStyle(n).animationName')=='none'
            page.emulate_media(reduced_motion='no-preference')
            assert page.locator('.pdog-working').evaluate('n=>getComputedStyle(n).animationName')=='pdog-typing'
            Path('output').mkdir(exist_ok=True)
            for theme in ['light','dark']:
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                page.screenshot(path=f'output/pdog-{theme}.png',full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert not writes,writes
            assert not errors,errors
            browser.close()
        print('PASS: six PDog poses, actual asset route, status priority, read-only keyboard dialog, escaped project text, task/project distinction, reduced motion, themes and mobile; no messages sent')
    finally:http.shutdown();http.server_close();worker.join()
