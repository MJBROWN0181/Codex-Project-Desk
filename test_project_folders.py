"""Records integration tests use temporary folders; no live Codex execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
import subprocess
import time
import uuid

import server
import project_folders as folders
from desk_codex import DeskCodex


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.old_db=server.DB;server.DB=self.root/'db.sqlite3';server.initialize()
        self.p=server.update(dict(name='Example'))
        folders.scaffold(self.p,self.root/'Projects');server.save(self.p)
        self.service=DeskCodex(server)

    def tearDown(self):
        server.DB=self.old_db;self.temp.cleanup()

    def test_scaffold_and_validation(self):
        root=Path(self.p['recordsRoot'])
        for child in ('Features','Project Audit','Project Advisors','Marketing/Images','Marketing/Social Media Ads','Brain Dump','Branding','Chat'):
            self.assertTrue((root/child).is_dir())
        for name in ('../bad','a/b','CON','bad.',''):
            with self.assertRaises(ValueError):folders.add_feature(self.p,name)
        folders.add_feature(self.p,'Search')
        for child in ('Audit','Advisor','Chat','New Ideas'):
            self.assertTrue((root/'Features'/'Search'/child).is_dir())
        with self.assertRaises(ValueError):folders.add_feature(self.p,'search')

    def test_scope_isolated_handoff_after_successful_wrap(self):
        folders.add_feature(self.p,'Search');folders.add_feature(self.p,'Billing')
        self.p['activeFeature']='Search'
        receipt=folders.prepare(self.p,'Build search','normal',str(uuid.uuid4()))
        receipt['recordsFeature']='Search'
        state=dict(threadId=str(uuid.uuid4()),kind='wrap')
        failed=dict(id='failure',status='failed',items=[dict(type='agentMessage',text='Incomplete')])
        folders.record_turn(self.p,state,failed,receipt)
        self.assertIsNone(folders.latest_handoff(folders.scope(self.p)))
        complete=dict(id='complete',status='completed',items=[dict(type='agentMessage',phase='final_answer',text='Done: search. Tests pass. Next: filters.')])
        folders.record_turn(self.p,state,complete,receipt)
        folders.record_turn(self.p,state,complete,receipt)
        record=json.loads((Path(receipt['recordsSession'])/'session.json').read_text())
        self.assertEqual(len(record['turns']),2)
        self.assertTrue((Path(receipt['recordsSession'])/'Pass On Log.md').exists())
        next_chat=folders.prepare(self.p,'Add filters','normal',str(uuid.uuid4()))
        self.assertIn('Next: filters.',next_chat['message'])
        self.p['activeFeature']='Billing'
        self.assertNotIn('Next: filters.',folders.prepare(self.p,'Billing','normal',str(uuid.uuid4()))['message'])

    def test_send_new_chat_idempotency_and_queue_inherits_scope(self):
        body=dict(projectId=self.p['id'],requestId=str(uuid.uuid4()),action='Build it')
        with patch('desk_codex.threading.Thread'):
            receipt=self.service.send(body)
            retry=self.service.send(body)
        self.assertEqual(receipt['id'],retry['id'])
        self.assertTrue(receipt['newFolderChat']);self.assertIsNone(receipt['threadId'])
        self.assertEqual(receipt['cwd'],self.p['recordsRoot'])
        chat=str(uuid.uuid4());p=self.service.project(self.p['id'])
        p['workState']={'phase':'idle'}
        p['recordChats']={chat:{k:receipt[k] for k in ('recordsSession','recordsScope','recordsFeature','title','sourceCheckout')}}
        server.save(p)
        with patch('desk_codex.threading.Thread'):
            addition=self.service.send(dict(projectId=p['id'],threadId=chat,requestId=str(uuid.uuid4()),action='Extra'),internal=True,kind='addition')
        self.assertEqual(addition['recordsSession'],receipt['recordsSession'])
        self.assertEqual(addition['threadId'],chat)

    def test_report_history_retained_and_feature_routing(self):
        folders.add_feature(self.p,'Search')
        for identity,grade in (('first','D'),('second','A')):
            self.p['auditReport']=dict(id=identity,grade=grade,completedAt='2026-10-30T12:00:00Z',summary='Evidence')
            server.save(self.p)
        self.assertEqual(len(list((Path(self.p['recordsRoot'])/'Project Audit').glob('*.json'))),2)
        self.p['advisorReport']=dict(id='advice',grade='B',completedAt='2026-10-30T12:00:00Z',summary='Advice',recordsFeature='Search')
        server.save(self.p)
        self.assertEqual(len(list((Path(self.p['recordsRoot'])/'Features'/'Search'/'Advisor').glob('*.json'))),1)

    def test_existing_folder_never_adopted(self):
        p={'name':'Example','path':'somewhere'}
        with self.assertRaises(ValueError):folders.scaffold(p,self.root/'Projects')

    def test_explicit_migration_preserves_existing_code(self):
        root=self.root/'Projects'/'Existing source';root.mkdir()
        (root/'app.py').write_text('existing code',encoding='utf-8')
        p=server.new_project('Existing source');p['path']=str(root)
        with self.assertRaises(ValueError):folders.scaffold(p,self.root/'Projects')
        folders.scaffold(p,self.root/'Projects',allow_existing=True)
        self.assertEqual((root/'app.py').read_text(),'existing code')
        self.assertEqual(p['path'],str(root))
        foreign=server.new_project('Existing source')
        with self.assertRaises(ValueError):folders.scaffold(foreign,self.root/'Projects',allow_existing=True)

    def test_native_worker_wrap_completion_then_next_chat(self):
        folders.add_feature(self.p,'Search');self.p['activeFeature']='Search';server.save(self.p)
        body=dict(projectId=self.p['id'],requestId=str(uuid.uuid4()),action='Build search')
        with patch('desk_codex.threading.Thread'): receipt=self.service.send(body)
        chat=str(uuid.uuid4());native=MagicMock();native.__enter__.return_value=native
        native.read_thread.return_value=dict(id=chat,name=receipt['title'],updatedAt=int(time.time()))
        def call(method,params,**kwargs):
            if method=='thread/start':
                self.assertEqual(params['cwd'],self.p['path'])
                return {'thread':{'id':chat}}
            if method=='thread/name/set':
                self.assertEqual(params['name'],receipt['title']);return {}
            if params.get('itemsView')=='notLoaded':return {'data':[]}
            return {'data':[dict(id='build-turn',startedAt=int(time.time()),items=[dict(type='userMessage',content=[dict(type='text',text=receipt['message'])])])]}
        native.call.side_effect=call
        result=subprocess.CompletedProcess([],0,'Queued message '+str(uuid.uuid4())+' for thread '+chat+'.','')
        with patch('desk_codex.Client',return_value=native),patch('desk_codex.executable',return_value='codex.exe'),patch('desk_codex.subprocess.run',return_value=result),patch('desk_codex.local_open'):
            self.service._send_worker(receipt)
        self.assertEqual(self.service.job(receipt['id'])['status'],'received')
        p=self.service.project(self.p['id'])
        self.service.control._finish_turn(p,dict(id='build-turn',status='completed',items=[dict(type='agentMessage',phase='final_answer',text='Search implemented.')]))
        p=self.service.project(p['id'])
        with patch('desk_codex.threading.Thread'):self.service.control._dispatch(p,chat,wrap=True)
        p=self.service.project(p['id']);wrap_id=p['workState']['requestId']
        self.assertEqual(self.service.job(wrap_id)['recordsSession'],receipt['recordsSession'])
        self.service.control._finish_turn(p,dict(id='wrap-turn',status='completed',items=[dict(type='agentMessage',phase='final_answer',text='Search done. Next: filters. Tests: 3 passed.')]))
        p=self.service.project(p['id'])
        self.assertIn(chat,p['closedRecordChats']);self.assertTrue(p['workPaused'])
        self.service.control.control(dict(projectId=p['id'],action='resume'))
        with patch('desk_codex.threading.Thread'):next_receipt=self.service.send(dict(body,requestId=str(uuid.uuid4()),action='Add filters'))
        self.assertIsNone(next_receipt['threadId']);self.assertIn('Tests: 3 passed.',next_receipt['message'])
        self.assertNotEqual(next_receipt['recordsSession'],receipt['recordsSession'])


if __name__=='__main__':unittest.main()
