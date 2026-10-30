"""One durable verification audit after exact fix-turn completion; no live agents."""
import copy
from pathlib import Path
import tempfile,time,unittest,uuid
from unittest.mock import MagicMock,patch
import server
from desk_codex import DeskCodex
from finish_agents import AuditEngine
from test_finish_agents import FakeRunner

CHAT='00000000-0000-4000-8000-000000000001'
class AuditFollowUpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_db=server.DB;self.old_data=server.DATA
        server.DATA=Path(self.temp.name);server.DB=server.DATA/'followup.sqlite3';server.initialize()
        self.p=server.new_project('Audit follow-up fixture');self.p.update(path=self.temp.name,preferredChatId=CHAT,chats=[dict(id=CHAT,title='Audit',at=server.now())],auditReport=self.report('D'))
        server.save(self.p);self.service=DeskCodex(server);self.control=self.service.control
        self.native=MagicMock();self.native.call.return_value={'data':[]}
    def tearDown(self):server.DB=self.old_db;server.DATA=self.old_data;self.temp.cleanup()
    def report(self,grade):
        return dict(id=str(uuid.uuid4()),projectId='fixture',projectName='Fixture',mode='finish-team',completedAt=server.now(),grade=grade,ready=False,summary='Evidence-based review',findings=[],checks=[],limitations=['One check remains'],fixPrompt='Fix the reported issue.',rerunRecommendation=dict(when='After the missing check is available.',why='Current evidence is incomplete.',conditions=['Run the missing check.']),assessmentComplete=True)
    def project(self):return self.service.project(self.p['id'])
    def arm(self,mode='finish-team'):
        p=self.project();p['auditReport']['mode']=mode;server.save(p)
        body=dict(projectId=p['id'],requestId=str(uuid.uuid4()),action='Fix the audit issues',auditSourceKey=p['auditReport']['id'])
        with patch('desk_codex.threading.Thread'):receipt=self.service.send_audit(body)
        self.service._receipt(receipt['id'],threadId=CHAT,status='received',turnId='fix-turn')
        p=self.project();p['workState'].update(threadId=CHAT,turnId='fix-turn');server.save(p)
        return receipt,body
    def turns(self,status='completed',identity='fix-turn'):
        self.native.call.return_value={'data':[dict(id=identity,status=status,startedAt=int(time.time()),completedAt=int(time.time()),items=[])]}
    def test_completed_fix_starts_same_team_once_updates_grade_and_stops(self):
        receipt,body=self.arm();source=self.project()['auditReport']['id'];self.turns()
        with patch('work_control.threading.Thread') as worker:self.control.tick(self.native)
        worker.assert_called_once();p=self.project();self.assertEqual(p['auditFollowUp']['status'],'running')
        operation=p['workState']['id'];result=self.report('B')
        with patch('finish_agents.AuditEngine.run',return_value=result) as run:self.control._operation(p['id'],'finish-team',operation)
        self.assertTrue(run.call_args.kwargs['verify_only']);self.assertTrue(run.call_args.kwargs['team'])
        p=self.project();self.assertEqual(p['auditReport']['grade'],'B');self.assertEqual(p['auditReport']['previousGrade'],'D');self.assertEqual(p['auditReport']['followUpOf'],source)
        self.assertEqual(p['auditFollowUp']['status'],'completed');self.assertEqual(p['auditHistory'][0]['reportId'],source)
        self.assertTrue((server.DATA/'reports'/(operation+'.json')).is_file())
        with patch('work_control.threading.Thread') as worker:self.control.tick(self.native)
        worker.assert_not_called()
        with patch('desk_codex.threading.Thread') as worker:self.service.send_audit(body)
        worker.assert_not_called()
    def test_in_progress_or_failed_fix_never_starts_an_audit(self):
        self.arm();self.turns('inProgress')
        with patch('work_control.threading.Thread') as worker:self.control.tick(self.native)
        worker.assert_not_called();self.assertEqual(self.project()['auditFollowUp']['status'],'waiting-fixes')
        self.turns('failed')
        with patch('work_control.threading.Thread') as worker:self.control.tick(self.native)
        worker.assert_not_called();self.assertEqual(self.project()['auditFollowUp']['status'],'fixes-failed');self.assertEqual(self.project()['auditReport']['grade'],'D')
    def test_pause_holds_followup_and_resume_runs_readiness_mode(self):
        self.arm('readiness');p=self.project();p['workPaused']=True;server.save(p);self.turns()
        with patch('work_control.threading.Thread') as worker:self.control.tick(self.native)
        worker.assert_not_called();self.assertEqual(self.project()['auditFollowUp']['status'],'queued')
        self.control.control(dict(projectId=p['id'],action='resume'))
        with patch('work_control.threading.Thread') as worker:self.control.tick(self.native)
        self.assertEqual(worker.call_args.kwargs['args'][1],'assess')
        p=self.project()
        with patch('finish_agents.AuditEngine.run',return_value=self.report('C')) as run:self.control._operation(p['id'],'assess',p['workState']['id'])
        self.assertFalse(run.call_args.kwargs['team']);self.assertTrue(run.call_args.kwargs['verify_only'])
    def test_queued_additions_finish_before_the_followup(self):
        self.arm();addition=str(uuid.uuid4());self.control.queue(dict(projectId=self.p['id'],requestId=addition,text='Also cover this repair detail.'));self.turns()
        with patch('work_control.threading.Thread'):self.control.tick(self.native)
        p=self.project();self.assertEqual(p['workState']['kind'],'addition');self.assertEqual(p['auditFollowUp']['status'],'queued')
        self.service._receipt(addition,status='received',turnId='addition-turn');self.turns(identity='addition-turn')
        with patch('work_control.threading.Thread') as worker:self.control.tick(self.native)
        self.assertEqual(self.project()['auditFollowUp']['status'],'running');self.assertEqual(worker.call_args.kwargs['args'][1],'finish-team')
    def test_interrupted_verification_never_replays_or_changes_old_grade(self):
        self.arm();self.turns()
        with patch('work_control.threading.Thread'):self.control.tick(self.native)
        with patch('work_control.threading.Thread') as worker:service=DeskCodex(server)
        worker.assert_not_called();p=service.project(self.p['id']);self.assertEqual(p['auditFollowUp']['status'],'attention');self.assertEqual(p['auditReport']['grade'],'D')
    def test_failed_grading_saves_evidence_and_retains_previous_report(self):
        self.arm();self.turns()
        with patch('work_control.threading.Thread'):self.control.tick(self.native)
        p=self.project();old=copy.deepcopy(p['auditReport']);result=self.report('F');result['assessmentComplete']=False
        with patch('finish_agents.AuditEngine.run',return_value=result):self.control._operation(p['id'],'finish-team',p['workState']['id'])
        p=self.project();self.assertEqual(p['auditReport'],old);self.assertEqual(p['auditFollowUp']['status'],'attention');self.assertTrue(p['workPaused'])
        self.assertTrue((server.DATA/'reports'/(p['auditFollowUp']['operationId']+'.json')).is_file())
    def test_changed_source_is_not_overwritten_by_a_pending_followup(self):
        self.arm();p=self.project();p['auditFollowUp']['status']='queued';p['workState']={};p['auditReport']=self.report('A');server.save(p)
        with patch('work_control.threading.Thread') as worker:self.control._start_audit_follow_up(p)
        worker.assert_not_called();self.assertEqual(self.project()['auditFollowUp']['status'],'superseded');self.assertEqual(self.project()['auditReport']['grade'],'A')
    def test_stale_audit_reference_is_rejected_before_creating_chat(self):
        with patch('desk_codex.threading.Thread') as worker:
            with self.assertRaisesRegex(ValueError,'source audit changed'):self.service.send_audit(dict(projectId=self.p['id'],requestId=str(uuid.uuid4()),action='Fix issues',auditSourceKey='not-current'))
        worker.assert_not_called()
    def test_verification_engine_uses_same_specialists_without_writes(self):
        runner=FakeRunner(issue=True);engine=AuditEngine(server,runner=runner,folder_resolver=lambda p:Path(self.temp.name))
        with patch('finish_agents.capture_baseline') as baseline:report=engine.run(self.project(),team=True,verify_only=True)
        baseline.assert_not_called();self.assertEqual(len(runner.calls),8)
        self.assertTrue(all(c['sandbox']=='read-only' for c in runner.calls));self.assertNotIn('boss-fix',[c['role'] for c in runner.calls])
        self.assertEqual(len(report['rounds']),1);self.assertEqual(report['grade'],'C');self.assertTrue(report['rerunRecommendation']['conditions'])
        self.assertIn('When to re-audit',report['markdown'])
