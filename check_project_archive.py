"""Real browser/storage/HTTP checks without native chat or GitHub actions."""
import copy
from pathlib import Path
import tempfile
import threading
from playwright.sync_api import sync_playwright,expect
import server

with tempfile.TemporaryDirectory() as directory:
    server.DB=Path(directory)/'archive.sqlite3';server.initialize()
    a=server.new_project('Archive working project');a.update(pinned=True,workState={'phase':'working','detail':'Fixture work continues'},actionDraft={'action':'Keep this draft'})
    server.event(a,server.now(),'Existing activity','Manual update','existing');server.save(a)
    b=server.new_project('Second project');server.save(b)
    before=copy.deepcopy(a)
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    root=f'http://127.0.0.1:{http.server_port}'
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1100,'height':950});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(root);page.wait_for_load_state('networkidle')
            card=page.locator('article').filter(has=page.get_by_role('heading',name=a['name'],exact=True))
            expect(card.locator('.card-organize button')).to_have_count(2)
            card.get_by_role('button',name='Archive project',exact=True).click();expect(card).to_have_count(0)
            expect(page.locator('#notice')).to_contain_text('Project archived.')
            saved=next(p for p in server.load_projects() if p['id']==a['id']);assert saved['archived']
            for key,value in before.items():assert saved[key]==value,key
            page.reload();page.wait_for_load_state('networkidle');expect(card).to_have_count(0)
            page.locator('#archive-view').click();expect(card).to_have_count(1)
            expect(card.locator('.work-status')).to_contain_text('Working')
            page.set_viewport_size({'width':390,'height':900});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            positions=card.locator('.card-organize button').evaluate_all('buttons=>buttons.map(button=>button.getBoundingClientRect().top)')
            assert abs(positions[0]-positions[1])<1,'Archive/restore should stay next to Pin'
            card.get_by_role('button',name='Restore project',exact=True).click();expect(card).to_have_count(0)
            expect(page.locator('#notice')).to_contain_text('Project restored')
            page.locator('#archive-view').click();expect(card).to_have_count(1)
            # Old running backends remain usable while long reviews finish.
            # A browser saves a pending visibility choice, then syncs it once the
            # updated backend advertises archive support.
            def legacy(route):
                if route.request.method!='GET':route.continue_();return
                response=route.fetch();data=response.json();data.pop('features',None);route.fulfill(response=response,json=data)
            page.route('**/api/projects',legacy);page.reload();page.wait_for_load_state('networkidle')
            second=page.locator('article').filter(has=page.get_by_role('heading',name=b['name'],exact=True))
            second.get_by_role('button',name='Archive project',exact=True).click();expect(second).to_have_count(0)
            assert not next(p for p in server.load_projects() if p['id']==b['id']).get('archived')
            page.reload();page.wait_for_load_state('networkidle');expect(second).to_have_count(0)
            page.unroute('**/api/projects',legacy);page.evaluate('load()')
            assert next(p for p in server.load_projects() if p['id']==b['id'])['archived']
            assert page.evaluate("localStorage.getItem('project-desk-archive-pending')")=='{}'
            other=browser.new_page();other.goto(root);other.wait_for_load_state('networkidle')
            expect(other.locator('article.project')).to_have_count(1)
            other.locator('#archive-view').click();expect(other.get_by_role('heading',name=b['name'],exact=True)).to_be_visible()
            assert len(server.load_projects())==2
            assert not errors,errors
            browser.close()
        print('PASS: archive beside Pin, active work preserved, hidden after reload, restore, small layout, old-backend fallback, synchronization, fresh browser profile; no deletions or chat sends')
    finally:http.shutdown();http.server_close();worker.join()
