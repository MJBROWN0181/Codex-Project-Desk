"""Card stats and one-time celebrations with isolated data; no live work."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import re
import tempfile
import threading
from playwright.sync_api import sync_playwright,expect
import server

with tempfile.TemporaryDirectory() as folder:
    server.DB=Path(folder)/'card-states.sqlite3';server.initialize()
    now=datetime.now(timezone.utc);old=(now-timedelta(days=12)).isoformat()
    fixtures=[('Working',{'workState':{'phase':'working'},'workPaused':True,'blocker':'Old blocker','auditReport':{'grade':'F','completedAt':old,'summary':'Earlier audit found gaps.','findings':[]}}),('Needs attention',{'workState':{'phase':'attention','detail':'Confirm delivery.'}}),('Blocked',{'blocker':'Choose the missing requirement.'}),('Paused',{'workPaused':True}),('Finished',{'workState':{'phase':'idle','outcome':'completed','completedAt':old}}),('Complete',{'status':'Complete'}),('Ready',{}),('Queued',{'workState':{'phase':'queued'}})]
    saved={}
    for name,fields in fixtures:
        p=server.new_project(name);p.update(fields)
        if name!='Ready':server.event(p,old,'Earlier planning','Manual','old-note')
        server.save(p);saved[name]=p
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1360,'height':1000});errors=[];writes=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle')
            def card(name):return page.locator('article.project[data-id="'+saved[name]['id']+'"]')
            for name,state in [('Working','working'),('Needs attention','attention'),('Blocked','blocked'),('Paused','paused'),('Finished','finished'),('Complete','complete'),('Ready','ready'),('Queued','waiting')]:
                expect(card(name)).to_have_attribute('data-work-state',state)
            expect(card('Working').locator('.card-audit-stat')).to_contain_text('Audit F')
            expect(card('Working').locator('.card-audit-stat')).to_contain_text(page.evaluate('(date)=>cardShortDate(date)',old))
            expect(card('Working').locator('.card-quiet')).to_have_count(0)
            expect(card('Paused').locator('.card-quiet')).to_have_text('Quiet for 12 days')
            expect(card('Ready').locator('.card-signals')).to_contain_text('No activity yet')
            expect(card('Complete').locator('.card-quiet')).to_have_count(0)
            expect(page.locator('.card-celebrating')).to_have_count(0)
            card('Working').locator('.card-audit-stat').click();expect(page.locator('#work-report')).to_be_visible()
            expect(page.locator('#work-report-body')).to_contain_text('Earlier audit found gaps.')
            page.locator('#work-report').get_by_role('button',name='Close report').click()
            # A real completion evidence update triggers a single small celebration.
            p=saved['Working'];stamp=server.now();p['workPaused']=False;p['blocker']=''
            p['workState']={'phase':'idle','outcome':'completed','completedAt':stamp}
            server.event(p,stamp,'Codex work completed','Codex completion','turn:fixture');server.save(p)
            page.evaluate('load()');expect(card('Working')).to_have_attribute('data-work-state','finished')
            expect(card('Working')).to_have_class(re.compile('card-celebrating'))
            expect(card('Working').locator('.card-celebration-message')).to_have_text('Task finished in Working.')
            assert card('Working').evaluate("n=>getComputedStyle(n,'::after').animationIterationCount")=='1'
            box=card('Working').bounding_box();page.evaluate('render()')
            expect(page.locator('.card-celebrating')).to_have_count(0)
            assert box==card('Working').bounding_box(),'Celebration must not change card layout'
            page.evaluate('load()');expect(page.locator('.card-celebrating')).to_have_count(0)
            page.reload();page.wait_for_load_state('networkidle');expect(page.locator('.card-celebrating')).to_have_count(0)
            # A completed turn followed immediately by queued work still celebrates
            # its saved completion event, while the next work keeps the cyan look.
            p['workState']={'phase':'working'};server.save(p);page.evaluate('load()')
            stamp=server.now();server.event(p,stamp,'Codex work completed','Codex completion','turn:next');server.save(p)
            page.evaluate('load()');expect(card('Working')).to_have_attribute('data-work-state','working')
            expect(card('Working')).to_have_class(re.compile('card-celebrating'))
            page.emulate_media(reduced_motion='reduce')
            assert card('Working').evaluate("n=>getComputedStyle(n,'::before').animationName")=='none'
            assert card('Working').evaluate("n=>getComputedStyle(n,'::after').animationName")=='none'
            page.emulate_media(reduced_motion='no-preference')
            # Manual completions work too; a stopped turn never celebrates.
            ready=saved['Ready'];ready['completedActions']=[{'id':'manual-fixture','at':server.now(),'action':'Small task'}];server.save(ready)
            page.evaluate('load()');expect(card('Ready')).to_have_class(re.compile('card-celebrating'))
            p['workState']={'phase':'attention','outcome':'failed'};server.save(p);page.evaluate('load()')
            expect(card('Working')).to_have_attribute('data-work-state','blocked');expect(page.locator('.card-celebrating')).to_have_count(0)
            assert page.evaluate("cardActivity({activity:[{at:'bad date'}]}).text")=='No activity yet'
            assert page.evaluate("cardActivity({activity:[{at:'2099-01-01'}]}).text")=='Check activity date'
            assert page.evaluate("cardWorkState({auditReport:{grade:'F'}}).key")=='ready'
            Path('output').mkdir(exist_ok=True)
            for theme in ['dark','light']:
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                page.screenshot(path=f'output/card-states-{theme}.png',full_page=True)
            for width in [390,768,1360]:
                page.set_viewport_size({'width':width,'height':900});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert not writes,writes
            assert not errors,errors
            browser.close()
        print('PASS: work-state priority, separate audit/date and activity stats, quiet threshold, report link, one-time task and manual celebrations, queue-chain evidence, no failure/refresh replay, stable layout, reduced motion, themes, mobile; no live messages')
    finally:http.shutdown();http.server_close();thread.join()
