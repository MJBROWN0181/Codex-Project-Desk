"""Direct accept and editable suggestion review, isolated native transport."""
import copy
from pathlib import Path
import tempfile,threading,uuid
from playwright.sync_api import sync_playwright,expect
import server
from desk_codex import DeskCodex

CHAT='00000000-0000-4000-8000-000000000001'
OTHER='00000000-0000-4000-8000-000000000002'
with tempfile.TemporaryDirectory() as folder:
    server.DB=Path(folder)/'suggestion.sqlite3';server.initialize()
    p=server.new_project('Suggestion fixture');p.update(preferredChatId=CHAT,chats=[{'id':CHAT,'title':'Preferred project chat','url':'codex://threads/'+CHAT,'at':server.now()},{'id':OTHER,'title':'Other linked chat','url':'codex://threads/'+OTHER,'at':server.now()}],suggestion={'text':'Ship the displayed suggestion','reason':'It follows the last completed task.','source':'Codex agent'},nextAction='Unrelated manual plan')
    server.save(p);server.save_draft(dict(projectId=p['id'],expectedRevision=0,draft=dict(threadId=CHAT,action='Unrelated unsent draft',reason='Keep this reasoning',instructions='Keep these notes')))
    service=DeskCodex(server);server.CODEX_SERVICE=service;sent=[];recommendations=[]
    service.native_chats=lambda:[dict(id=CHAT,title='Preferred project chat'),dict(id=OTHER,title='Other linked chat')]
    def recommend(body):recommendations.append(body);raise ValueError('Must preserve the displayed suggestion')
    service.recommendation=recommend
    def worker(receipt):
        sent.append(copy.deepcopy(receipt));service._receipt(receipt['id'],status='received',title='Preferred project chat')
    service._send_worker=worker
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1100,'height':850});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle')
            card=page.locator('article.project');expect(card.locator('.suggestion').get_by_role('button',name='Change',exact=True)).to_have_count(0)
            card.get_by_role('button',name='Accept',exact=True).click()
            expect(page.locator('#delivery-title')).to_have_text('Received by Codex')
            expect(page.locator('#action-review')).to_be_hidden();assert len(sent)==1 and sent[0]['threadId']==CHAT
            assert sent[0]['action']=='Ship the displayed suggestion' and sent[0]['reason']==p['suggestion']['reason']
            expect(card.locator('.suggestion')).to_have_count(0);expect(card.locator('.next')).to_be_hidden();expect(card.locator('.work-status')).to_contain_text('Sending to Codex')
            saved=service.project(p['id']);assert saved['actionDraft']['action']=='Unrelated unsent draft' and saved['nextAction']=='Unrelated manual plan'
            page.locator('#delivery .close').click()
            # The review edits this suggestion, not an old normal draft or a newly
            # generated recommendation, and sends only after the final click.
            saved['workState']={};saved['suggestion']=dict(p['suggestion'],text='Review this exact suggestion');server.save(saved);page.evaluate('load()')
            card.get_by_role('button',name='Review and send',exact=True).click();review=page.locator('#action-review')
            expect(review.get_by_role('heading',name='Review suggestion',exact=True)).to_be_visible()
            expect(review.get_by_label('Next action',exact=True)).to_have_value('Review this exact suggestion')
            expect(review.locator('#recommend-action')).to_be_hidden();assert len(sent)==1 and not recommendations
            review.get_by_label('Next action',exact=True).fill('My edited suggestion')
            review.get_by_label('Additional instructions (optional)',exact=True).fill('Include my added details.')
            review.get_by_role('button',name='Cancel',exact=True).click();assert service.project(p['id'])['actionDraft']['action']=='Unrelated unsent draft'
            card.get_by_role('button',name='Review and send',exact=True).click()
            expect(review.get_by_label('Next action',exact=True)).to_have_value('My edited suggestion')
            review.locator('#chat-picker-toggle').click();review.get_by_label('Find a chat',exact=True).fill('Other linked');review.locator('.chat-choice').click()
            expect(review.get_by_label('Next action',exact=True)).to_have_value('My edited suggestion')
            review.get_by_role('button',name='Send to Codex',exact=True).click();expect(page.locator('#delivery')).to_be_visible();expect(page.locator('#delivery-title')).to_have_text('Received by Codex')
            assert len(sent)==2 and sent[1]['threadId']==OTHER and sent[1]['action']=='My edited suggestion' and 'Include my added details.' in sent[1]['message'],[(r['threadId'],r['action'],r['message']) for r in sent]
            assert service.project(p['id'])['actionDraft']['action']=='Unrelated unsent draft';assert not recommendations
            page.locator('#delivery .close').click()
            saved=service.project(p['id']);saved.update(workState={},preferredChatId=None,chats=[],suggestion=dict(p['suggestion'],text='A new suggestion without a destination'));server.save(saved);page.evaluate('load()')
            card.get_by_role('button',name='Accept',exact=True).click()
            expect(page.locator('#notice')).to_contain_text('Use Review and send to choose')
            expect(card.locator('.suggestion')).to_be_visible();expect(page.locator('#action-review')).to_be_hidden();assert len(sent)==2
            page.set_viewport_size({'width':390,'height':844});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert not errors,errors
            browser.close()
        print('PASS: Accept sends once without review to the exact preferred chat; no Change; review preserves displayed suggestion and edits; separate drafts; missing destination sends nothing; no live Codex messages')
    finally:http.shutdown();http.server_close();thread.join()
