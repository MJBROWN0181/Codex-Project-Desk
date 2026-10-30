"""Exercise refresh and async UI edges without sending any Codex messages."""
from pathlib import Path
import tempfile
import threading
import uuid
from playwright.sync_api import sync_playwright,expect
import server
from desk_codex import DeskCodex

CHAT='00000000-0000-4000-8000-000000000001'
with tempfile.TemporaryDirectory() as directory:
    server.DB=Path(directory)/'smooth.sqlite3';server.initialize()
    p=server.update({'name':'Workflow alpha','kind':'App','nextAction':'Review milestone'})
    p['chats']=[dict(id=CHAT,title='Fixture chat',url='codex://threads/'+CHAT,at='2026-10-29T10:00:00Z')];server.save(p)
    service=DeskCodex(server);server.CODEX_SERVICE=service
    service.native_chats=lambda:[dict(id=CHAT,title='Fixture chat')]
    service.recommendation=lambda body:dict(action='Suggested step',reason='Fixture reason')
    service.refresh_replies=lambda:dict(refreshed=0,unavailable=[])
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1100,'height':900})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            root=f'http://127.0.0.1:{http.server_port}'
            page.goto(root);page.wait_for_load_state('networkidle')
            page.get_by_role('searchbox').fill('Workflow');page.locator('#kind').select_option('App')
            server.update({'id':p['id'],'name':'Workflow updated'})
            page.locator('#refresh-desk').click()
            expect(page.locator('article h3')).to_have_text('Workflow updated')
            expect(page.get_by_role('searchbox')).to_have_value('Workflow')
            expect(page.locator('#kind')).to_have_value('App')
            expect(page.get_by_role('switch')).to_have_attribute('aria-checked','true')
            expect(page.locator('#refresh-desk')).to_be_enabled()
            # An older response must not replace the result of a newer refresh.
            data=page.request.get(root+'/api/projects').json()
            page.evaluate('''() => {window.originalFetch=window.fetch;window.refreshResolvers=[];
                window.fetch=(url,...args)=>url==='/api/projects'?new Promise(resolve=>refreshResolvers.push(resolve)):originalFetch(url,...args);
                window.firstLoad=load();window.secondLoad=load();}''')
            newer={**data,'projects':[{**data['projects'][0],'name':'Workflow newest'}]}
            page.evaluate('''async body=>{refreshResolvers[1](new Response(JSON.stringify(body)));await secondLoad;}''',newer)
            page.evaluate('''async body=>{refreshResolvers[0](new Response(JSON.stringify(body)));await firstLoad;window.fetch=originalFetch;}''',data)
            expect(page.locator('article h3')).to_have_text('Workflow newest')
            # Clearing a target while a recommendation is pending unlocks text fields.
            page.route('**/api/codex/jobs/*',lambda route:route.fulfill(json={'id':'pending','status':'working'}))
            page.locator('.next-action-link').click()
            review=page.locator('#action-review')
            expect(review.get_by_label('Next action',exact=True)).to_have_attribute('readonly','')
            review.get_by_label('Send to Codex chat',exact=True).select_option('')
            expect(review.get_by_label('Next action',exact=True)).not_to_have_attribute('readonly','')
            expect(page.locator('#send-action')).to_be_disabled()
            review.get_by_role('button',name='Cancel',exact=True).click()
            page.unroute('**/api/codex/jobs/*')
            # A response for a closed receipt must never overwrite a different receipt.
            a=dict(id=str(uuid.uuid4()),projectId=p['id'],status='queued',message='Message A',title='Chat A',createdAt=server.now())
            b=dict(id=str(uuid.uuid4()),projectId=p['id'],status='received',message='Message B',title='Chat B',createdAt=server.now())
            server.metadata('codexMessages',{a['id']:a,b['id']:b})
            page.evaluate('''id=>{window.originalFetch=window.fetch;
                window.fetch=(url,...args)=>url.endsWith('/jobs/'+id)?new Promise(resolve=>window.releaseReceipt=body=>resolve(new Response(JSON.stringify(body)))):originalFetch(url,...args);}''',a['id'])
            page.evaluate('receipt=>{openDelivery(receipt);}',a)
            page.locator('#delivery').get_by_role('button',name='Close dialog').click()
            page.evaluate('receipt=>{openDelivery(receipt);}',b)
            expect(page.locator('#delivery-title')).to_have_text('Received by Codex')
            page.evaluate('receipt=>{releaseReceipt(receipt);window.fetch=originalFetch;}',a)
            expect(page.locator('#delivery-chat')).to_have_text('Chat B')
            expect(page.locator('#delivery-title')).to_have_text('Received by Codex')
            page.locator('#delivery').get_by_role('button',name='Close dialog').click()
            Path('output').mkdir(exist_ok=True);page.screenshot(path='output/smooth-desktop.png')
            for width in (390,430,768):
                page.set_viewport_size({'width':width,'height':900})
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),width
                expect(page.locator('#refresh-desk')).to_be_visible()
            page.screenshot(path='output/smooth-narrow.png')
            assert not errors,errors
            assert not server.metadata('codexMessages')[a['id']].get('queueId')
            browser.close()
        print('PASS: header refresh, preserved filters/theme, stale response protection, cleared target controls, receipt race, responsive widths, no messages sent')
    finally:http.shutdown();http.server_close();worker.join()
