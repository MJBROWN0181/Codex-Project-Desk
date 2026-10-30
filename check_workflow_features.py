"""Draft/pin/reply persistence across a real HTTP server restart, with no Codex sends."""
from pathlib import Path
import tempfile
import threading
from playwright.sync_api import sync_playwright,expect
import server
from desk_codex import DeskCodex
from test_codex_actions import CHAT

with tempfile.TemporaryDirectory() as directory:
    server.DB=Path(directory)/'workflow.sqlite3';server.initialize()
    a=server.update({'name':'Alpha project','kind':'App','nextAction':'Accepted action'})
    b=server.update({'name':'Beta project','kind':'Business'})
    a['chats']=[dict(id=CHAT,title='Saved draft destination',url='codex://threads/'+CHAT,at='2026-10-29T10:00:00Z')]
    a['latestReply']=dict(threadId=CHAT,title='Saved draft destination',text='Latest final reply <script>not executable</script>\n'+('Long reply. '*40),at='2026-10-29T11:00:00Z',turnId='fixture',checkedAt=server.now());server.save(a)
    service=DeskCodex(server);server.CODEX_SERVICE=service
    service.native_chats=lambda:[dict(id=CHAT,title='Saved draft destination')]
    calls=[]
    def recommend(body):calls.append(body);return dict(action='Recommended step',reason='Recommended explanation')
    service.recommendation=recommend;service.refresh_replies=lambda:dict(refreshed=0)
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start();port=http.server_port
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1100,'height':900})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            root=f'http://127.0.0.1:{port}'
            page.goto(root);page.wait_for_load_state('networkidle')
            alpha=page.locator('article').filter(has=page.get_by_role('heading',name='Alpha project',exact=True))
            expect(alpha.locator('.latest-reply')).to_contain_text('Latest final reply <script>not executable</script>')
            alpha.get_by_role('button',name='Pin project',exact=True).click()
            expect(alpha.get_by_role('button',name='Unpin project')).to_be_visible()
            page.locator('#focus-only').click();expect(page.locator('article.project')).to_have_count(1)
            alpha.locator('.next-action-link').click();review=page.locator('#action-review')
            expect(page.locator('#action-status')).to_contain_text('Agent recommendation ready')
            review.get_by_label('Next action',exact=True).fill('My unsent draft')
            review.get_by_label('Why this step',exact=True).fill('Keep my explanation')
            review.get_by_label('Additional instructions (optional)').fill('Preserve these added details')
            review.get_by_role('button',name='Cancel',exact=True).click()
            page.wait_for_function('''async id=>{const p=(await (await fetch('/api/projects')).json()).projects.find(p=>p.id===id);return p.actionDraft?.instructions==='Preserve these added details';}''',arg=a['id'])
            # Restart HTTP service and create a fresh integration instance using the same SQLite file.
            http.shutdown();http.server_close();worker.join()
            service=DeskCodex(server);server.CODEX_SERVICE=service
            service.native_chats=lambda:[dict(id=CHAT,title='Saved draft destination')]
            service.recommendation=recommend;service.refresh_replies=lambda:dict(refreshed=0)
            http=server.ThreadingHTTPServer(('127.0.0.1',port),server.Handler)
            worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
            page.reload();page.wait_for_load_state('networkidle')
            expect(page.locator('article.project')).to_have_count(1)
            expect(alpha.get_by_role('button',name='Unpin project')).to_be_visible()
            alpha.locator('.next-action-link').click()
            expect(page.locator('#action-status')).to_contain_text('Saved draft restored')
            expect(review.get_by_label('Next action',exact=True)).to_have_value('My unsent draft')
            expect(review.get_by_label('Why this step',exact=True)).to_have_value('Keep my explanation')
            expect(review.get_by_label('Additional instructions (optional)')).to_have_value('Preserve these added details')
            selfield=review.get_by_label('Send to Codex chat');expect(selfield).to_have_value(CHAT)
            assert len(calls)==1,'Restoring a draft must not regenerate over edits'
            review.get_by_role('button',name='Discard draft').click()
            expect(page.locator('#draft-status')).to_contain_text('Draft discarded')
            review.get_by_role('button',name='Cancel',exact=True).click()
            alpha.get_by_role('button',name='Unpin project').click()
            expect(page.locator('article.project')).to_have_count(0)
            page.locator('#focus-only').click();expect(page.locator('article.project')).to_have_count(2)
            page.set_viewport_size({'width':390,'height':900});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            Path('output').mkdir(exist_ok=True);page.screenshot(path='output/workflow-features.png',full_page=True)
            assert not errors,errors
            assert not server.metadata('codexMessages'),'These tests must not send messages'
            browser.close()
        print('PASS: unsent draft fields/destination, no regeneration, server restart persistence, discard, pins/focus view, safe final reply text, narrow layout; no messages sent')
    finally:http.shutdown();http.server_close();worker.join()
