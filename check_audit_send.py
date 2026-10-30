"""Audit highlights and reviewed routing with fake native chat transport."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import uuid
from playwright.sync_api import sync_playwright,expect
import server
from desk_codex import DeskCodex,message_text
from test_codex_actions import CHAT

with tempfile.TemporaryDirectory() as directory:
    server.DB=Path(directory)/'audit-send.sqlite3';server.initialize()
    other=str(uuid.uuid4());unrelated=str(uuid.uuid4())
    p=server.new_project('Audit send fixture');p['nextAction']='Keep existing next action'
    p['preferredChatId']=CHAT;p['chats']=[dict(id=CHAT,title='Intended project chat',url='codex://threads/'+CHAT,at=server.now()),dict(id=other,title='Another project chat',url='codex://threads/'+other,at=server.now())]
    p['auditReport']=dict(id=str(uuid.uuid4()),grade='D',summary='Usable areas exist, but a blocking issue remains.',completedAt=server.now(),fixPrompt='Verify the reported access-control gap, fix it, and check keyboard behavior.',
        findings=[dict(severity='high',title='Access check missing <script>as text</script>',evidence='fixture.py:14',recommendation='Verify ownership before reading private data.'),dict(severity='low',title='Copy consistency',evidence='page.html:5',recommendation='Use the same label.')],
        checks=[dict(name='Access regression',result='failed',evidence='Fixture test failed.'),dict(name='Keyboard flow',result='not-run',evidence='Not yet exercised.'),dict(name='Static parse',result='passed',evidence='Parsing passed.')],limitations=['Physical device not tested.'])
    server.save(p)
    normal=dict(threadId=CHAT,action='Keep my unfinished plan',reason='Original reasoning',instructions='Original unsent details')
    server.save_draft(dict(projectId=p['id'],expectedRevision=0,draft=normal));original=copy.deepcopy(server.load_projects()[0]['actionDraft'])
    service=DeskCodex(server);server.CODEX_SERVICE=service;sent=[];recommendations=[]
    service.native_chats=lambda:[dict(id=unrelated,title='Unrelated chat'),dict(id=CHAT,title='Intended project chat'),dict(id=other,title='Another project chat')]
    def recommend(body):recommendations.append(body);raise ValueError('An audit send must not generate a different recommendation')
    service.recommendation=recommend
    def send(body):
        sent.append(copy.deepcopy(body));r=dict(id=body['requestId'],projectId=p['id'],threadId=body['threadId'],status='received',title='Reviewed destination',message=message_text(body),createdAt=server.now())
        server.metadata('codexMessages',{r['id']:r});return r
    service.send=send
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1200,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.fixtureCopiedAudit=text;}}})")
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle')
            page.get_by_role('button',name='Audit report',exact=False).click();report=page.locator('#work-report')
            expect(report.locator('.audit-highlight.urgent')).to_have_count(2)
            expect(report.locator('.audit-highlight.caution')).to_contain_text('Physical device not tested')
            expect(report.locator('.audit-grade')).to_have_text('Grade D')
            expect(report.locator('script')).to_have_count(0)
            assert report.locator('.audit-full-evidence').get_attribute('open') is None
            report.get_by_role('button',name='Copy fix prompt',exact=True).click()
            expected=page.locator('#work-fix-prompt').input_value();assert page.evaluate('window.fixtureCopiedAudit')==expected
            assert 'installed skills' in expected and 'available tools' in expected and 'Rerun relevant checks' in expected
            assert p['auditReport']['id'] in expected and '/data/reports' in expected
            Path('output').mkdir(exist_ok=True);page.screenshot(path='output/audit-highlights-desktop.png')
            report.get_by_role('button',name='Send to Codex',exact=True).click();review=page.locator('#action-review')
            expect(review.get_by_role('heading',name='Review audit fixes',exact=True)).to_be_visible()
            expect(review.get_by_label('Send to Codex chat',exact=True)).to_have_value(CHAT)
            expect(review.locator('#recommend-action')).to_be_hidden()
            assert not sent and not recommendations
            instructions=review.get_by_label('Additional instructions (optional)',exact=True)
            expect(instructions).to_have_value(expected)
            edited=expected+'\n\nAlso test the keyboard path with my added scenario.';instructions.fill(edited)
            review.get_by_role('button',name='Cancel',exact=True).click()
            assert service.project(p['id'])['actionDraft']==original
            page.get_by_role('button',name='Audit report',exact=False).click();report.get_by_role('button',name='Send to Codex',exact=True).click()
            expect(instructions).to_have_value(edited)
            review.get_by_label('Send to Codex chat',exact=True).select_option(other)
            expect(instructions).to_have_value(edited);assert not recommendations and not sent
            review.get_by_role('button',name='Send to Codex',exact=True).click()
            expect(page.locator('#delivery-title')).to_have_text('Received by Codex')
            assert len(sent)==1 and sent[0]['threadId']==other and sent[0]['preserveActionDraft']
            assert sent[0]['instructions'].replace('\r\n','\n')==edited.replace('\r\n','\n'),(len(sent[0]['instructions']),len(edited),repr(sent[0]['instructions'][-100:]),repr(edited[-100:]))
            expect(page.locator('#delivery-message')).to_contain_text('added scenario')
            assert service.project(p['id'])['actionDraft']==original
            page.locator('#delivery').get_by_role('button',name='Close dialog',exact=True).click()
            page.locator('.next-action-link').click()
            expect(review.get_by_label('Next action',exact=True)).to_have_value(normal['action'])
            expect(review.get_by_label('Additional instructions (optional)',exact=True)).to_have_value(normal['instructions'])
            expect(review.locator('#recommend-action')).to_be_visible()
            review.get_by_role('button',name='Cancel',exact=True).click()
            # Clean reports have no placeholder sends. Oversized recommendations
            # remain in the saved report and are referenced rather than truncated.
            clean=service.project(p['id']);clean['auditReport']=dict(id=str(uuid.uuid4()),grade='A',summary='No required fixes.',fixPrompt='',findings=[],checks=[],limitations=[]);server.save(clean);page.evaluate('load()')
            page.get_by_role('button',name='Audit report',exact=False).click()
            expect(report.get_by_role('button',name='Send to Codex',exact=True)).to_be_disabled()
            expect(report.get_by_role('button',name='Copy fix prompt',exact=True)).to_be_disabled()
            report.get_by_role('button',name='Close report',exact=True).click()
            clean['auditReport']['fixPrompt']='Detailed recommended repair. '*500;server.save(clean);page.evaluate('load()')
            page.get_by_role('button',name='Audit report',exact=False).click();report.get_by_role('button',name='Send to Codex',exact=True).click()
            assert len(instructions.input_value())<=6000
            assert 'complete recommended prompt' in instructions.input_value() and 'has not been truncated' in instructions.input_value()
            page.set_viewport_size({'width':390,'height':900});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert len(sent)==1 and not recommendations and not errors,errors
            browser.close()
        print('PASS: selective highlights, copy/send, review/edit before one exact-target send, independent audit drafts, preserved normal draft, no replacement recommendation, clean-report guard, long-prompt reference, mobile; no live Codex messages')
    finally:http.shutdown();http.server_close();worker.join()
