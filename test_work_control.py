"""Lifecycle tests use synthetic turn evidence; they never send live messages."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
import uuid

import server
from desk_codex import DeskCodex
from test_codex_actions import CHAT


class WorkControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_db=server.DB
        server.DB=Path(self.temp.name)/'control.sqlite3';server.initialize()
        self.p=server.update(dict(name='Working test',nextAction='Build it'))
        self.p['preferredChatId']=CHAT
        self.p['chats']=[dict(id=CHAT,title='Exact chat',url='codex://threads/'+CHAT,at=server.now())]
        server.save(self.p);self.service=DeskCodex(server);self.control=self.service.control
        self.native=MagicMock();self.native.call.return_value={'data':[]}

    def tearDown(self):server.DB=self.old_db;self.temp.cleanup()
    def project(self):return self.service.project(self.p['id'])
    def body(self):return dict(projectId=self.p['id'],threadId=CHAT,requestId=str(uuid.uuid4()),action='Build it',reason='Needed')
    def queue(self,text='Extra detail'):
        return self.control.queue(dict(projectId=self.p['id'],requestId=str(uuid.uuid4()),text=text))
    def control_action(self,action):return self.control.control(dict(projectId=self.p['id'],action=action))
    def sent(self,body=None):
        with patch('desk_codex.threading.Thread'):receipt=self.service.send(body or self.body())
        self.service._receipt(receipt['id'],status='received',turnId='exact-turn')
        return receipt
    def turns(self,status='completed',identity='exact-turn'):
        self.native.call.return_value={'data':[dict(id=identity,status=status,startedAt=int(time.time()),completedAt=int(time.time()),items=[dict(type='agentMessage',phase='final_answer',text='Work result')])]}

    def test_received_is_not_completed_and_queue_waits(self):
        receipt=self.sent();self.queue();self.turns('inProgress')
        with patch.object(self.service,'send') as send:self.control.tick(self.native)
        send.assert_not_called();self.assertEqual(self.project()['workState']['phase'],'working')
        self.assertEqual(self.project()['contentQueue'][0]['state'],'pending')
        self.turns()
        with patch('desk_codex.threading.Thread') as worker:self.control.tick(self.native)
        worker.assert_called_once()
        p=self.project();self.assertEqual(p['workState']['phase'],'sending')
        self.assertEqual(p['contentQueue'][0]['state'],'sent')
        receipts=server.metadata('codexMessages');self.assertEqual(len(receipts),2)
        queued=next(r for r in receipts.values() if r['id']!=receipt['id'])
        self.assertIn('Extra detail',queued['message']);self.assertEqual(queued['threadId'],CHAT)
        self.assertEqual(p['latestReply']['text'],'Work result')
        self.assertEqual(p['status'],'Active')

    def test_pause_completes_current_then_holds_and_resume_drains(self):
        self.sent();self.queue();self.control_action('pause');self.turns()
        with patch.object(self.service,'send') as send:self.control.tick(self.native)
        send.assert_not_called();p=self.project();self.assertEqual(p['status'],'Paused')
        self.assertEqual(p['workState']['phase'],'idle')
        self.control_action('resume')
        with patch('desk_codex.threading.Thread'):self.control.tick(self.native)
        self.assertEqual(self.project()['contentQueue'][0]['state'],'sent')

    def test_restart_unknown_delivery_never_retransmits(self):
        with patch('desk_codex.threading.Thread'):receipt=self.service.send(self.body())
        self.queue();service=DeskCodex(server)
        self.assertEqual(service.job(receipt['id'])['status'],'unknown')
        with patch.object(service,'send') as send:service.control.tick(self.native)
        send.assert_not_called();self.assertEqual(service.project(self.p['id'])['workState']['phase'],'attention')

    def test_queue_idempotency_and_restart_fifo(self):
        body=dict(projectId=self.p['id'],requestId=str(uuid.uuid4()),text='First')
        self.control.queue(body);self.control.queue(body);self.queue('Second')
        with self.assertRaises(ValueError):self.control.queue(dict(body,text='Changed'))
        service=DeskCodex(server)
        with patch('desk_codex.threading.Thread'):service.control.tick(self.native)
        self.assertEqual([i['state'] for i in self.project()['contentQueue']],['sent','pending'])

    def test_failure_holds_queue_and_can_be_acknowledged(self):
        self.sent();self.queue();self.turns('failed')
        with patch.object(self.service,'send') as send:self.control.tick(self.native)
        send.assert_not_called();self.assertEqual(self.project()['workState']['phase'],'attention')
        self.control_action('retry-monitor');self.assertTrue(self.project()['workPaused'])
        self.assertEqual(self.project()['workState']['phase'],'idle')

    def test_failed_delivery_acknowledgement_does_not_retry(self):
        r=self.sent();self.service._receipt(r['id'],status='failed',turnId=None,error='Queue rejected')
        self.control.tick(self.native);self.assertEqual(self.project()['workState']['phase'],'attention')
        with patch.object(self.service,'send') as send:self.control_action('retry-monitor')
        send.assert_not_called();self.assertEqual(self.project()['workState']['phase'],'idle')

    def test_busy_blocks_edits_completion_recommendation_and_duplicate_sends(self):
        self.sent()
        with self.assertRaises(ValueError):server.update(dict(id=self.p['id'],name='Changed'))
        with self.assertRaises(ValueError):server.complete_action(dict(id=self.p['id'],expectedAction='Build it',requestId=str(uuid.uuid4())))
        with self.assertRaises(ValueError):self.service.recommendation(dict(projectId=self.p['id'],threadId=CHAT))
        with self.assertRaises(ValueError):self.service.send(self.body())
        server.update(dict(id=self.p['id'],pinned=True));self.assertTrue(self.project()['pinned'])
        p=self.project();p['suggestion']=dict(text='Stale snapshot suggestion');server.save(p)
        self.assertIsNone(self.project()['suggestion'])

    def test_wrap_runs_after_turn_then_pauses_queue(self):
        self.sent();self.queue();self.control_action('wrap');self.turns()
        with patch('desk_codex.threading.Thread'):self.control.tick(self.native)
        p=self.project();self.assertEqual(p['workState']['kind'],'wrap')
        self.assertEqual(p['contentQueue'][0]['state'],'pending')
        self.service._receipt(p['workState']['requestId'],status='received',turnId='wrap-turn')
        self.turns(identity='wrap-turn')
        with patch.object(self.service,'send') as send:self.control.tick(self.native)
        send.assert_not_called();self.assertTrue(self.project()['workPaused']);self.assertNotIn('wrapRequestId',self.project())

    def test_external_active_turn_discovered_and_completed(self):
        self.turns('inProgress')
        self.control.tick(self.native,scan_idle=True)
        self.assertEqual(self.project()['workState']['phase'],'working')
        self.control_action('pause');self.turns();self.control.tick(self.native)
        self.assertEqual(self.project()['workState']['phase'],'idle')

    def test_operation_restart_does_not_replay_mutations(self):
        p=self.project();p['workState']=dict(phase='operation',operation='release',id='saved');p['releaseState']=dict(pushed=True,published=False);server.save(p)
        service=DeskCodex(server)
        with patch.object(service.control,'_operation') as operation:service.control.tick(self.native)
        operation.assert_not_called();self.assertTrue(self.project()['releaseState']['pushed'])
        self.assertEqual(self.project()['workState']['phase'],'attention')

    def test_live_turn_repairs_false_attention_without_sending(self):
        self.sent();self.queue();self.turns('failed');self.control.tick(self.native)
        self.assertTrue(self.project()['workPaused'])
        self.turns('inProgress')
        with patch.object(self.service,'send') as send:self.control.tick(self.native)
        send.assert_not_called();p=self.project()
        self.assertEqual(p['workState']['phase'],'working')
        self.assertFalse(p['workPaused']);self.assertEqual(p['status'],'Active')
        self.assertNotIn('outcome',p['workState'])
        self.assertEqual(p['contentQueue'][0]['state'],'pending')

    def test_live_recovery_preserves_explicit_user_pause(self):
        self.sent();self.control_action('pause');self.turns('failed');self.control.tick(self.native)
        self.turns('inProgress');self.control.tick(self.native)
        self.assertEqual(self.project()['workState']['phase'],'working')
        self.assertTrue(self.project()['workPaused'])

    def test_unconfirmed_interruption_never_pauses_or_dispatches(self):
        self.sent();self.queue();self.turns('interrupted')
        self.native.call.return_value['data'][0]['completedAt']=None
        with patch.object(self.service,'send') as send:self.control.tick(self.native)
        send.assert_not_called();p=self.project()
        self.assertEqual(p['workState']['phase'],'working')
        self.assertFalse(p.get('workPaused',False));self.assertNotIn('outcome',p['workState'])

    def test_completion_clears_legacy_false_hold(self):
        self.sent();p=self.project()
        p['workState'].update(phase='attention',outcome='interrupted',detail='Codex work interrupted. Queued additions are held. Check the chat before resuming.')
        p['workPaused']=True;p['status']='Paused';server.save(p)
        self.turns('completed')
        with patch('work_control.threading.Thread'):self.control.tick(self.native)
        p=self.project();self.assertEqual(p['workState']['phase'],'idle')
        self.assertFalse(p['workPaused']);self.assertEqual(p['status'],'Active')

if __name__=='__main__':unittest.main()
