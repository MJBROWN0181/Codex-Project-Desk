"""Browser coverage with real local HTTP/SQLite and synthetic Codex results."""
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch,MagicMock
from playwright.sync_api import sync_playwright,expect
import server
from desk_codex import DeskCodex
from test_codex_actions import CHAT

with tempfile.TemporaryDirectory() as directory:
    server.DB=Path(directory)/'browser.sqlite3';server.DATA=Path(directory);server.initialize()
    a=server.update(dict(name='Control test',kind='Website',nextAction='Build next feature',repo='MJBROWN0181/Codex-Project-Desk',path=str(server.ROOT),websiteUrl='https://example.com'))
    a.update(preferredChatId=CHAT,chats=[dict(id=CHAT,title='Fixture chat',url='codex://threads/'+CHAT,at=server.now())],workState=dict(phase='working',threadId=CHAT,turnId='fixture-turn',detail='Codex is working.'),suggestion=dict(text='Must be hidden'))
    server.save(a);service=DeskCodex(server);server.CODEX_SERVICE=service
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1280,'height':1000})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle')
            card=page.locator('article.project');expect(card.locator('.work-status')).to_contain_text('Working')
            expect(card.locator('.next-action-link')).to_be_hidden()
            expect(card.get_by_role('button',name='Edit project',exact=True)).to_have_count(0)
            expect(card.get_by_role('button',name='Finish agent team',exact=True)).to_be_disabled()
            card.get_by_role('button',name='Add content',exact=True).click()
            dialog=page.locator('#work-addition');dialog.get_by_label('What should Codex know?').fill('Keep this <script> as text')
            dialog.get_by_role('button',name='Save to queue',exact=True).click()
            expect(card.locator('.work-queue')).to_contain_text('1 queued addition')
            card.get_by_role('button',name='Pause',exact=True).click()
            expect(card.locator('.work-status')).to_contain_text('pause after this turn')
            native=MagicMock();native.call.return_value={'data':[dict(id='fixture-turn',status='completed',items=[dict(type='agentMessage',phase='final_answer',text='Finished fixture turn')])]}
            service.control.tick(native)
            page.evaluate('load()');expect(card.locator('.work-status')).to_contain_text('Paused')
            expect(card.locator('.latest-reply')).to_contain_text('Finished fixture turn')
            expect(card.locator('.work-queue')).to_contain_text('1 queued addition')
            assert not server.metadata('codexMessages'),'Pause must not dispatch queued work'
            # Clear fixture queue only, then exercise audit endpoint with a mock engine.
            p=service.project(a['id']);p['contentQueue']=[];server.save(p);page.evaluate('load()')
            report=dict(grade='B',summary='Usable; one check remains.',findings=[dict(title='Fixture <script> finding')],limitations=['Physical device not checked.'],fixPrompt='Verify the fixture issue without losing work.',completedAt=server.now(),markdown='Fixture report')
            with patch('finish_agents.AuditEngine.run',return_value=report):
                card.get_by_role('button',name='Am I done?',exact=True).click()
                deadline=time.monotonic()+10
                while not service.project(a['id']).get('auditReport') and time.monotonic()<deadline:time.sleep(.02)
                assert service.project(a['id']).get('auditReport'), 'Mock audit did not complete'
            page.evaluate('load()');card.get_by_role('button',name='Audit report',exact=False).click(timeout=5000)
            expect(page.locator('#work-report-body')).to_contain_text('Grade B')
            expect(page.locator('#work-report-body')).to_contain_text('Fixture <script> finding')
            expect(page.locator('#work-fix-prompt')).to_have_value(report['fixPrompt'])
            page.locator('#work-report').get_by_role('button',name='Close report').click()
            # The address exists in project metadata, not the separate tracker field.
            fixture=Path(directory)/'site';fixture.mkdir();(fixture/'index.html').write_text('<link rel="canonical" href="https://fixture.example/">')
            p=service.project(a['id']);p['websiteUrl']='';p['path']=str(fixture);server.save(p);page.evaluate('load()')
            class SiteResponse:
                status=200
                def __enter__(self):return self
                def __exit__(self,*args):pass
            opener=MagicMock();opener.open.return_value=SiteResponse()
            with patch('project_ops.build_opener',return_value=opener):
                card.get_by_role('button',name='Check site',exact=True).click()
                expect(card.locator('.website-health')).to_contain_text('Up')
                expect(card.locator('.checked-site-url')).to_have_text('https://fixture.example/')
            assert service.project(a['id'])['websiteUrl']=='https://fixture.example/'
            assert opener.open.call_args.args[0].full_url=='https://fixture.example/'
            page.set_viewport_size({'width':390,'height':900})
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),'Mobile layout overflows'
            Path('output').mkdir(exist_ok=True);page.screenshot(path='output/work-controls-mobile.png',full_page=True)
            page.set_viewport_size({'width':1280,'height':1000});page.screenshot(path='output/work-controls-desktop.png',full_page=True)
            assert not errors,errors
            browser.close()
        print('PASS: working lock, queued content, pause/completion, audit report, safe text, site state, mobile/desktop; no live messages or releases')
    finally:http.shutdown();http.server_close();worker.join()
