"""Trust only acknowledged structured plans scoped to the exact current turn."""
import json
from pathlib import Path
import tempfile,unittest
from unittest.mock import MagicMock,patch
import server,turn_evidence
from task_progress import normalize_plan,progress_for_turn
from desk_codex import DeskCodex

PLAN=[dict(step='Inspect',status='completed'),dict(step='Implement',status='in_progress'),dict(step='Verify',status='pending')]
class TaskProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=self.root/'session.jsonl'
        self.patch=patch.object(turn_evidence,'SESSION_ROOT',self.root);self.patch.start();turn_evidence._cache.clear()
        self.row('session_meta',dict(id='chat'));self.row('event_msg',dict(type='task_started',turn_id='turn'))
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def row(self,kind,body):
        with self.path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(dict(type=kind,payload=body,timestamp='2026-10-30T06:00:00Z'))+'\n')
    def evidence(self):return turn_evidence.session_evidence(self.path,'chat')
    def plan(self,plan=PLAN,call='plan',ack=True):
        self.row('response_item',dict(type='function_call',name='update_plan',call_id=call,arguments=json.dumps(dict(plan=plan))))
        if ack:self.row('response_item',dict(type='function_call_output',call_id=call,output='Plan updated'))
    def test_explicit_steps_count_only_completed_not_partial_work(self):
        p=normalize_plan(PLAN);self.assertEqual((p['completed'],p['total'],p['currentStep']),(1,3,'Implement'))
        self.assertEqual(normalize_plan([dict(step='Current',status='inProgress')])['completed'],0)
        for value in [[],None,[dict(step='Bad',status='almost done')],[dict(step='Bad',status=[])],[dict(step=' ',status='completed')],[dict(step='A',status='in_progress'),dict(step='B',status='in_progress')]]:self.assertIsNone(normalize_plan(value))
    def test_session_plan_requires_matching_success_ack(self):
        self.plan(ack=False);self.assertNotIn('plan',self.evidence()['turn'])
        self.row('response_item',dict(type='function_call_output',call_id='unrelated',output='Plan updated'));self.assertNotIn('plan',self.evidence()['turn'])
        self.row('response_item',dict(type='function_call_output',call_id='plan',output='Plan updated'));self.assertEqual(self.evidence()['turn']['plan']['completed'],1)
    def test_plan_revision_replaces_counts_and_new_turn_inherits_nothing(self):
        self.plan();self.assertEqual(self.evidence()['turn']['plan']['total'],3)
        self.plan([dict(step='New scope',status='pending')],call='revision');self.assertEqual(self.evidence()['turn']['plan']['completed'],0);self.assertEqual(self.evidence()['turn']['plan']['total'],1)
        self.row('event_msg',dict(type='task_started',turn_id='next-turn'));self.assertNotIn('plan',self.evidence()['next-turn'])
        self.assertEqual(turn_evidence.session_evidence(self.path,'other-chat'),{})
    def test_failed_or_malformed_plan_does_not_invent_progress(self):
        self.plan(ack=False);self.row('response_item',dict(type='function_call_output',call_id='plan',output='Error: invalid plan'));self.assertNotIn('plan',self.evidence()['turn'])
        self.plan();self.evidence();self.plan([],call='clear');self.assertNotIn('plan',self.evidence()['turn'])
    def test_native_items_need_success_and_prose_is_not_a_plan(self):
        item=dict(type='dynamicToolCall',tool='update_plan',namespace='functions',status='completed',success=True,arguments=dict(plan=PLAN))
        progress=progress_for_turn(dict(id='turn',items=[item]));self.assertEqual(progress['completed'],1);self.assertEqual(progress['turnId'],'turn')
        for changes in [dict(success=False),dict(status='inProgress'),dict(tool='exec_command'),dict(namespace='untrusted')]:self.assertIsNone(progress_for_turn(dict(id='turn',items=[dict(item,**changes)])))
        self.assertIsNone(progress_for_turn(dict(id='turn',items=[dict(type='plan',text='- [x] one\n- [ ] two'),dict(type='agentMessage',text='90% done')],taskProgress=dict(turnId='older',steps=PLAN))))
    def test_monitor_attaches_plan_without_modifying_native_data(self):
        self.plan();client=MagicMock();client.read_thread.return_value=dict(path=str(self.path));client.call.return_value=dict(data=[dict(id='turn',status='inProgress',items=[])])
        page=turn_evidence.monitor_turns(client,dict(threadId='chat'));self.assertEqual(progress_for_turn(page['data'][0])['completed'],1)
        self.assertNotIn('taskProgress',client.call.return_value['data'][0])
    def test_work_control_saves_current_plan_and_clears_it_when_unavailable(self):
        original=server.DB;server.DB=self.root/'progress.sqlite3';server.initialize()
        try:
            p=server.new_project('Progress fixture');p.update(preferredChatId='chat',chats=[],workState=dict(phase='working',threadId='chat',turnId='turn'));server.save(p);service=DeskCodex(server)
            item=dict(type='dynamicToolCall',tool='update_plan',status='completed',success=True,arguments=dict(plan=PLAN));client=MagicMock();client.read_thread.side_effect=ValueError('No session snapshot')
            client.call.return_value=dict(data=[dict(id='turn',status='inProgress',items=[item])]);service.control.tick(client)
            current=service.project(p['id']);self.assertEqual(current['workState']['taskProgress']['completed'],1)
            client.call.return_value=dict(data=[dict(id='turn',status='inProgress',items=[])]);service.control.tick(client)
            self.assertNotIn('taskProgress',service.project(p['id'])['workState'])
        finally:server.DB=original
