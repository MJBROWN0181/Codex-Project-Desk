"""Browser review/send checks with an isolated database; --live uses the existing echo-test chat."""
import argparse
import os
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
import uuid
from playwright.sync_api import sync_playwright,expect
import server
from desk_codex import DeskCodex

parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
chat=os.environ.get('PROJECT_DESK_TEST_CHAT','00000000-0000-4000-8000-000000000001')
if args.live and 'PROJECT_DESK_TEST_CHAT' not in os.environ:parser.error('--live requires PROJECT_DESK_TEST_CHAT set to an authorized test chat UUID')
message='Project Desk review/send integration test. Reply exactly PROJECT_DESK_REVIEW_SEND_OK. Do not use tools, edit files, contact anyone, or resume previous work.'
with tempfile.TemporaryDirectory() as directory:
    server.DB=Path(directory)/'actions.sqlite3';server.initialize()
    p=server.new_project('Connection test fixture',identity='test-fixture')
    p['nextAction']='Review this next step'
    p['chats']=[dict(id=chat,title='Reply with studio confirmation',url='codex://threads/'+chat,at='2026-10-29T10:00:00Z')]
    server.save(p);service=DeskCodex(server);server.CODEX_SERVICE=service
    if not args.live:
        service.refresh_replies=lambda:dict(refreshed=0,unavailable=[])
        service.native_chats=lambda:[dict(id=chat,title='Reply with studio confirmation')]
        recommend_finish=threading.Event();recommend_state={'fail':False}
        def recommend(body):
            if not recommend_finish.wait(10):raise ValueError('Test recommendation timed out')
            if recommend_state['fail']:raise ValueError('Recommendation test failure')
            return dict(action='Agent recommended step',reason='It follows the previous result.',threadId=chat)
        service.recommendation=recommend
        def send(body):
            from desk_codex import message_text
            receipt=dict(id=body['requestId'],projectId=p['id'],threadId=chat,status='received',title='Reply with studio confirmation',message=message_text(body),createdAt=server.now())
            server.metadata('codexMessages',{receipt['id']:receipt});return receipt
        service.send=send
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1100,'height':950});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle')
            page.locator('.next-action-link').click();review=page.locator('#action-review')
            expect(review).to_be_visible()
            if not args.live:
                expect(page.locator('#recommendation-thinking')).to_be_visible()
                expect(page.locator('#recommend-action')).to_have_text('Thinking…')
                expect(page.locator('#recommend-action')).to_have_attribute('aria-busy','true')
                expect(page.locator('#send-action')).to_be_disabled()
                page.emulate_media(reduced_motion='reduce')
                assert page.locator('.recommendation-spinner').evaluate('node=>getComputedStyle(node).animationName')=='none'
                page.emulate_media(reduced_motion='no-preference')
                Path('output').mkdir(exist_ok=True);page.screenshot(path='output/recommendation-thinking.png')
                recommend_finish.set()
            expect(page.locator('#action-status')).to_contain_text('Agent recommendation ready',timeout=210000)
            expect(page.locator('#recommendation-thinking')).to_be_hidden()
            expect(page.locator('#recommend-action')).to_have_attribute('aria-busy','false')
            if not args.live:
                recommend_finish.clear();recommend_state['fail']=True
                page.locator('#recommend-action').click()
                expect(page.locator('#recommendation-thinking')).to_be_visible()
                recommend_finish.set()
                expect(page.locator('#action-status')).to_contain_text('Recommendation test failure')
                expect(page.locator('#recommendation-thinking')).to_be_hidden()
                expect(page.locator('#recommend-action')).to_be_enabled()
                expect(page.locator('#send-action')).to_be_enabled()
            Path('output').mkdir(exist_ok=True)
            # Exercise the actual review selector's rows in both themes, including
            # unselected options, without sending any message or changing a target.
            selector=review.get_by_label('Send to Codex chat',exact=True)
            for theme in ('light','dark'):
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                colors=selector.evaluate('''select=>Array.from(select.options,option=>{
                  const css=getComputedStyle(option);
                  return {color:css.color,background:css.backgroundColor};
                })''')
                def luminance(css):
                    import re
                    channels=[int(n)/255 for n in re.findall(r'\d+',css)[:3]]
                    linear=[n/12.92 if n<=.04045 else ((n+.055)/1.055)**2.4 for n in channels]
                    return sum(n*w for n,w in zip(linear,[.2126,.7152,.0722]))
                for pair in colors:
                    assert pair['background']!='rgba(0, 0, 0, 0)',pair
                    light,dark=sorted([luminance(pair['color']),luminance(pair['background'])],reverse=True)
                    assert (light+.05)/(dark+.05)>=4.5,(theme,pair)
                # Listbox rendering exposes option rows in a browser screenshot;
                # native operating-system popups may be painted outside the page.
                selector.evaluate('select=>select.size=4')
                page.screenshot(path=f'output/chat-options-{theme}.png')
                selector.evaluate('select=>select.removeAttribute("size")')
            page.screenshot(path='output/review-next-action.png')
            expect(review.get_by_label('Next action',exact=True)).not_to_be_empty()
            expect(review.get_by_label('Why this step',exact=True)).not_to_be_empty()
            # Selecting or generating a recommendation has not sent anything.
            assert not server.metadata('codexMessages')
            review.get_by_label('Next action',exact=True).fill(message if args.live else 'My edited step')
            review.get_by_label('Why this step',exact=True).fill('Verify that the reviewed text reaches the exact destination.')
            review.get_by_label('Additional instructions (optional)',exact=True).fill('This is a connection test only. Preserve all project files.')
            review.locator('summary').click()
            expect(page.locator('#action-preview')).to_contain_text('Preserve all project files.')
            page.set_viewport_size({'width':430,'height':950})
            page.screenshot(path='output/review-next-action-narrow.png')
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            review.get_by_role('button',name='Send to Codex',exact=True).click()
            expect(page.locator('#delivery-title')).to_have_text('Received by Codex',timeout=90000)
            expect(page.locator('#delivery-message')).to_contain_text('Preserve all project files.')
            receipts=server.metadata('codexMessages');assert len(receipts)==1
            receipt=next(iter(receipts.values()));assert receipt['threadId']==chat
            page.locator('#delivery').get_by_role('button',name='Close dialog').click()
            page.reload();page.wait_for_load_state('networkidle')
            expect(page.get_by_role('button',name='Received by Codex',exact=True)).to_be_visible()
            assert not errors,errors
            browser.close()
        print('PASS: agent recommendation, editable step/reason/additions, no pre-review sends, exact destination, receipt, narrow layout, persistence'+(' (LIVE CODEX DELIVERY)' if args.live else ' (mock transport)'))
    finally:
        http.shutdown();http.server_close();worker.join()
