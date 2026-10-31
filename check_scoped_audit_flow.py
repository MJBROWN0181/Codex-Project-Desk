"""Browser/HTTP scoped audit flow; source discovery, agents and native CLI are fixtures."""
import copy,json,re,subprocess,tempfile,threading,time,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
from playwright.sync_api import sync_playwright,expect
import server
from desk_codex import DeskCodex

class Harness:
    def __init__(self,root,older,candidate):
        self.root=root;self.older=older;self.candidate=candidate;self.jobs=[];self.calls=[];self.threads={};self.queues=[];self.opened=[]
    def schedule(self,*,target,args,**kwargs):
        self.jobs.append((target,args));return SimpleNamespace(start=lambda:None)
    def run_job(self):
        assert len(self.jobs)==1,self.jobs
        target,args=self.jobs.pop(0);target(*args)
    def run_agent(self,project,team=False,verify_only=False,**kwargs):
        folder=project['path'];assert folder in [str(self.older),str(self.candidate)]
        self.calls.append(dict(folder=folder,verify=verify_only,team=team))
        grade=('A' if folder==str(self.older) else 'B') if verify_only else ('D' if folder==str(self.older) else 'C')
        return dict(id=str(uuid.uuid4()),projectId=project['id'],projectName=project['name'],mode='finish-team' if team else 'readiness',startedAt=server.now(),completedAt=server.now(),grade=grade,ready=grade=='A',assessmentComplete=True,summary='Fixture checks for '+Path(folder).name,
            findings=[] if grade=='A' else [dict(title='Fixture issue',severity='high' if grade=='D' else 'medium' if grade=='C' else 'low',evidence=folder+'/source.txt:1',recommendation='Verify the fixture fix.',fixPrompt='Fix the fixture issue.')],
            checks=[dict(name='Fixture check',result='passed',evidence=folder+'/source.txt was inspected by the fixture')],limitations=[],fixPrompt='' if grade=='A' else 'Fix the fixture issue in '+folder+'.',rerunRecommendation=dict(when='After fixture prerequisites are met.',why='Fresh verification is needed.',conditions=[]),markdown='Fixture reviewer evidence: '+folder)
    def command(self,args,**kwargs):
        assert len(args)>1 and args[1]=='queue',args
        identity=args[args.index('--thread')+1];message=args[args.index('--message')+1];assert identity in self.threads
        self.queues.append(dict(threadId=identity,message=message))
        self.threads[identity]['turn']=dict(id='fix-'+identity,status='inProgress',startedAt=int(time.time()),items=[dict(type='userMessage',content=[dict(type='text',text=message)])])
        return subprocess.CompletedProcess(args,0,'Queued message '+str(uuid.uuid4())+' for thread '+identity+'.','')
    def client(self):
        h=self
        class Native:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read_thread(self,identity):return dict(id=identity,name='Audit',updatedAt=int(time.time()),cwd=h.threads[identity]['cwd'])
            def call(self,method,params):
                if method=='thread/start':
                    identity=str(uuid.uuid4());h.threads[identity]=dict(cwd=params['cwd'],turn=None);return dict(thread=dict(id=identity))
                if method=='thread/name/set':assert params['name']=='Audit';return {}
                assert method=='thread/turns/list',method
                turn=h.threads[params['threadId']]['turn'];return dict(data=[copy.deepcopy(turn)] if turn else [])
        return Native()

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);older=root/'older-checkout';candidate=root/'candidate-checkout'
    for path in [older,candidate]:path.mkdir();(path/'source.txt').write_text('Unchanged fixture source.')
    # This flow covers independent source folders, not guarded trunk/work repos.
    # Real disposable Git worktree guards are covered by test_worktree_workflow.
    options=[dict(path=str(path),label=path.name,configured=path==older,branch='') for path in [older,candidate]]
    server.DATA=root/'desk-data';server.DATA.mkdir();server.DB=server.DATA/'flow.sqlite3';server.initialize()
    harness=Harness(root,older,candidate);service=DeskCodex(server);server.CODEX_SERVICE=service
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start();results=[]
    try:
        with patch('audit_scope.discover',return_value=options),patch('desk_codex.subprocess.run',side_effect=harness.command),patch('desk_codex.Client',side_effect=harness.client),patch('desk_codex.executable',return_value='mock-codex'),patch('desk_codex.local_open',side_effect=harness.opened.append),patch('finish_agents.AuditEngine.run',side_effect=harness.run_agent),patch('work_control.threading',SimpleNamespace(Thread=harness.schedule)):
            with sync_playwright() as tool:
                browser=tool.chromium.launch(headless=True);page=browser.new_page(viewport=dict(width=1200,height=1000));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                for name,choice,expected,initial_grade in [('Selected checkout','1',[str(candidate)],'C'),('All folders','all',[str(older),str(candidate)],'D')]:
                    p=server.new_project(name);p['path']=str(older);server.save(p);before=len(harness.calls)
                    page.goto(f'http://127.0.0.1:{http.server_port}');page.wait_for_load_state('networkidle');card=page.locator('article[data-id="'+p['id']+'"]')
                    card.get_by_role('button',name='Finish agent team',exact=True).click();picker=page.locator('.audit-folder-picker');expect(picker).to_be_visible()
                    picker.locator('input[value="'+choice+'"]').check();picker.get_by_role('button',name='Start project review',exact=True).click()
                    expect(card).to_have_attribute('data-work-state','working');assert service.project(p['id'])['workState']['auditFolders']==expected
                    harness.run_job();initial=service.project(p['id'])['auditReport'];assert initial['auditedFolders']==expected and initial['grade']==initial_grade
                    assert [c['folder'] for c in harness.calls[before:]]==expected
                    page.evaluate('load()');expect(card.locator('.card-audit-stat')).to_contain_text('Audit '+initial_grade)
                    card.get_by_role('button',name='Audit report',exact=False).click();report=page.locator('#work-report')
                    expect(report.locator('.audit-grade')).to_have_text('Grade '+initial_grade)
                    for path in expected:expect(report.locator('.audit-source-folders')).to_contain_text(path)
                    if len(expected)==1:expect(report.locator('.audit-source-folders')).not_to_contain_text(str(older))
                    report.get_by_role('button',name='Send to Codex',exact=True).click();review=page.locator('#action-review')
                    expect(review).to_be_visible();assert len(harness.queues)==len(results),'Review must not send early'
                    expect(review.get_by_label('Additional instructions (optional)',exact=True)).to_have_value(re.compile('Work only in the source folders recorded in the report'))
                    review.get_by_role('button',name='Send to Codex',exact=True).click();expect(page.locator('#delivery')).to_be_visible();expect(page.locator('#delivery-title')).to_have_text('Received by Codex')
                    receipts=server.metadata('codexMessages');receipt=next(r for r in receipts.values() if r['projectId']==p['id']);chat=receipt['threadId']
                    assert receipt['auditFolders']==expected and receipt['cwd']==expected[0]
                    assert harness.threads[chat]['cwd']==expected[0] and harness.opened[-1]==chat
                    for path in expected:assert path in receipt['message'],(name,path,receipt['message'])
                    if len(expected)==1:assert str(older) not in receipt['message']
                    page.locator('#delivery .close').click();expect(card.locator('.card-audit-stat')).to_contain_text('Pending re-audit')
                    assert len(harness.calls)==before+len(expected),'No early verification while fix turn is working'
                    harness.threads[chat]['turn'].update(status='completed',completedAt=int(time.time()))
                    service.control.tick(harness.client());assert service.project(p['id'])['auditFollowUp']['status']=='running'
                    harness.run_job();updated=service.project(p['id']);assert updated['auditFollowUp']['status']=='completed',updated['workState']
                    final=updated['auditReport'];assert final['auditedFolders']==expected and final['grade']=='B'
                    assert [c['folder'] for c in harness.calls[before:] if c['verify']]==expected
                    assert all(c['team'] for c in harness.calls[before:])
                    assert final['previousGrade']==initial_grade and final['followUpOf']==initial['id']
                    if len(expected)==2:assert [r['grade'] for r in final['folderReports']]==['A','B']
                    page.evaluate('load()');expect(card.locator('.card-audit-stat')).to_contain_text('Audit B');expect(card.locator('.card-audit-stat')).not_to_contain_text('Pending re-audit')
                    card.get_by_role('button',name='Audit report',exact=False).click();expect(report.locator('.audit-grade')).to_have_text('Grade B')
                    for path in expected:expect(report.locator('.audit-source-folders')).to_contain_text(path)
                    expect(report.locator('.audit-rerun')).to_contain_text('Grade update: '+initial_grade+' → B')
                    report.get_by_role('button',name='Close report',exact=True).click();service.control.tick(harness.client());assert not harness.jobs
                    for path in [older,candidate]:assert (path/'source.txt').read_text()=='Unchanged fixture source.'
                    results.append(dict(flow=name,folders=[Path(path).name for path in expected],initialGrade=initial_grade,verifiedGrade='B',fixChatFolder=Path(harness.threads[chat]['cwd']).name))
                page.set_viewport_size(dict(width=390,height=844));assert not page.evaluate('document.documentElement.scrollWidth>innerWidth');assert not errors,errors
                browser.close()
        Path('output').mkdir(exist_ok=True);Path('output/scoped-audit-validation.json').write_text(json.dumps(dict(results=results,realAgents=False,realChatMessages=False),indent=2))
        print('PASS: selected checkout C -> B and All folders D -> B; real browser/HTTP/database, exact chat cwd/message/receipt, exact downstream reviewer scopes, current UI grade, no repeat audit; all agents/CLI mocked')
    finally:http.shutdown();http.server_close();worker.join()
