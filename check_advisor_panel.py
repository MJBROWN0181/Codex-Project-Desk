"""Advisor button/report browser checks; model calls and clipboard are isolated."""
import copy
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
import server
from desk_codex import DeskCodex
from advisor_panel import AdvisorPanel,ROLES
from test_advisor_panel import review

with tempfile.TemporaryDirectory() as directory,patch.object(server,'DB',Path(directory)/'advisors.sqlite3'),patch.object(server,'DATA',Path(directory)):
    server.initialize();p=server.new_project('Advisor browser fixture','App');p['path']=directory;p['auditReport']={'grade':'B'};server.save(p)
    def runner(**args):
        if args['phase']=='review':return review('continue')
        return dict(prompts=[dict(title='Fixture fix',prompt='Verify the concrete fixture issue <script>as text</script>.',priority='high')],limitations=[])
    continuing=AdvisorPanel(server,runner=runner).run(p)
    def negative(**args):return review('shelve')
    shelving=AdvisorPanel(server,runner=negative).run(p)
    # A malformed/stale artifact cannot bypass the UI's no-prompts shelving gate.
    shelving['fixPrompts']=[dict(advisor='Untrusted fixture',title='Must be hidden',prompt='DO NOT EXPOSE THIS PROMPT',priority='high')]
    continuing['advisors'][0]['summary']='Fixture <script>not executable</script>'
    continuing['advisors'][0]['evidence'].append(dict(kind='web',reference='javascript:alert(1)',finding='Unsafe source must not be a link.'))
    service=DeskCodex(server);server.CODEX_SERVICE=service
    gate=threading.Event();mode={'shelve':False}
    def fake_panel(*args,**kwargs):
        if not gate.wait(10):raise RuntimeError('Fixture wait timed out')
        return copy.deepcopy(shelving if mode['shelve'] else continuing)
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    def wait_report(decision):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if service.project(p['id']).get('advisorReport',{}).get('decision')==decision:return
            time.sleep(.02)
        raise AssertionError('Fixture advisor operation did not finish')
    try:
        with patch('advisor_panel.AdvisorPanel.run',side_effect=fake_panel),sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1200,'height':1000})
            page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.fixtureCopiedPrompt=text;}}})")
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle')
            card=page.locator('article.project');button=card.get_by_role('button',name='Panel of advisors',exact=True)
            button.click();expect(button).to_be_disabled();expect(card.locator('.work-status')).to_contain_text('Working')
            gate.set();wait_report('continue');page.evaluate('load()')
            card.get_by_role('button',name='Advisor report',exact=True).click();dialog=page.locator('#advisor-report')
            expect(dialog.locator('.advisor-grade-list>span')).to_have_count(3)
            expect(dialog).to_contain_text('Fixture <script>not executable</script>')
            expect(dialog.locator('script')).to_have_count(0)
            expect(dialog.locator('a[href^="javascript:"]')).to_have_count(0)
            dialog.get_by_role('button',name='Copy all fix prompts',exact=True).click()
            expect(page.locator('#advisor-copy-status')).to_contain_text('copied')
            assert 'Verify the concrete fixture issue' in page.evaluate('window.fixtureCopiedPrompt')
            Path('output').mkdir(exist_ok=True);page.screenshot(path='output/advisors-report-desktop.png')
            dialog.get_by_role('button',name='Close advisor report',exact=True).click()
            mode['shelve']=True;button.click();wait_report('shelve');page.evaluate('load()')
            card.get_by_role('button',name='Advisor report',exact=True).click()
            expect(dialog.locator('.advisor-decision')).to_contain_text('Shelve this project')
            expect(dialog).to_contain_text('No fix prompts were generated')
            expect(dialog.locator('[data-copy-advisor],[data-send-advisor],textarea,.advisor-prompts')).to_have_count(0)
            assert 'DO NOT EXPOSE THIS PROMPT' not in dialog.inner_text()
            self_saved=service.project(p['id']);assert self_saved['auditReport']=={'grade':'B'}
            assert not self_saved.get('archived')
            page.set_viewport_size({'width':390,'height':900});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            page.screenshot(path='output/advisors-report-mobile.png')
            assert not errors,errors
            browser.close()
        print('PASS: advisor button, working indicator, three grades, separate saved report, safe text/sources, prompt copying, unanimous-shelve hides every prompt control, no auto-archive, mobile; no real model calls')
    finally:gate.set();http.shutdown();http.server_close();worker.join()
