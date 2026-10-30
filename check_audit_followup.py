"""Reviewed audit fixes -> one same-team verification -> current grade; mock agents."""
from pathlib import Path
import tempfile,threading,time,uuid
from unittest.mock import patch,MagicMock
from playwright.sync_api import sync_playwright,expect
import server
from desk_codex import DeskCodex

CHAT='00000000-0000-4000-8000-000000000001'
with tempfile.TemporaryDirectory() as folder:
    server.DATA=Path(folder);server.DB=server.DATA/'reaudit.sqlite3';server.initialize()
    p=server.new_project('Re-audit fixture');p.update(path=folder,chats=[],auditReport=dict(id=str(uuid.uuid4()),projectName='Re-audit fixture',projectId=p['id'],mode='finish-team',grade='D',summary='One required fix remains.',completedAt=server.now(),fixPrompt='Fix the required issue.',findings=[],checks=[],limitations=[],rerunRecommendation=dict(when='After the required fix is verified.',why='A fresh review must confirm the repaired behavior.',conditions=['Verify the repaired workflow.'])))
    server.save(p);service=DeskCodex(server);server.CODEX_SERVICE=service
    def worker(receipt):
        service._receipt(receipt['id'],threadId=CHAT,status='received',turnId='fix-turn',title='Audit')
        current=service.project(p['id']);current['workState'].update(threadId=CHAT,turnId='fix-turn');current['preferredChatId']=CHAT;server.save(current)
    service._send_worker=worker
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as tool:
            browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1100,'height':950});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle')
            card=page.locator('article.project');card.get_by_role('button',name='Audit report',exact=False).click()
            report=page.locator('#work-report');expect(report.locator('.audit-rerun')).to_contain_text('After the required fix is verified.')
            report.get_by_role('button',name='Send to Codex',exact=True).click();page.locator('#action-review').get_by_role('button',name='Send to Codex',exact=True).click()
            expect(page.locator('#delivery')).to_be_visible();expect(page.locator('#delivery-title')).to_have_text('Received by Codex')
            page.locator('#delivery .close').click();expect(card.locator('.card-audit-stat')).to_contain_text('Audit D');expect(card.locator('.card-audit-stat')).to_contain_text('Pending re-audit')
            assert service.project(p['id'])['auditFollowUp']['status']=='waiting-fixes'
            native=MagicMock();native.call.return_value={'data':[dict(id='fix-turn',status='completed',startedAt=int(time.time()),completedAt=int(time.time()),items=[])]}
            with patch('work_control.threading') as scheduler:service.control.tick(native)
            scheduler.Thread.assert_called_once();current=service.project(p['id']);assert current['auditFollowUp']['status']=='running'
            page.evaluate('load()');card.get_by_role('button',name='Audit report',exact=False).click();expect(report.locator('.audit-rerun')).to_contain_text('running one verification audit now');report.get_by_role('button',name='Close report',exact=True).click()
            result=dict(p['auditReport'],id=str(uuid.uuid4()),grade='B',summary='Fix verified; authenticated testing remains.',completedAt=server.now(),rerunRecommendation=dict(when='After authenticated testing is complete.',why='That workflow still lacks real evidence.',conditions=['Run the signed-in workflow on a test account.']),assessmentComplete=True)
            with patch('finish_agents.AuditEngine.run',return_value=result) as engine:service.control._operation(p['id'],'finish-team',current['workState']['id'])
            assert engine.call_args.kwargs['team'] and engine.call_args.kwargs['verify_only']
            page.evaluate('load()');expect(card.locator('.card-audit-stat')).to_contain_text('Audit B');expect(card.locator('.card-audit-stat')).not_to_contain_text('Pending re-audit')
            card.get_by_role('button',name='Audit report',exact=False).click();expect(report.locator('.audit-rerun')).to_contain_text('Grade update: D → B');expect(report.locator('.audit-rerun')).to_contain_text('After authenticated testing is complete.')
            report.locator('.audit-rerun summary').click();expect(report.locator('.audit-rerun')).to_contain_text('Run the signed-in workflow on a test account.')
            with patch('work_control.threading') as scheduler:service.control.tick(native)
            scheduler.Thread.assert_not_called();page.set_viewport_size({'width':390,'height':844});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert not errors,errors
            browser.close()
        print('PASS: audit fix context, pending old grade, same-team verification only, D-to-B grade update, rerun timing/prerequisites, one follow-up then stop, mobile; no live agents or chat messages')
    finally:http.shutdown();http.server_close();thread.join()
