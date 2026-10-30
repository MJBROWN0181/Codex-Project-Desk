import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock,patch
import uuid
import server
from desk_codex import DeskCodex,message_text

CHAT='01a1878b-d3f8-79d2-9268-a93a2b1de9b1'

class CodexActionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_db=server.DB
        server.DB=Path(self.temp.name)/'actions.sqlite3';server.initialize()
        self.project=server.update({'name':'Action test','nextAction':'Original step','blocker':'Keep blocker'})
        self.service=DeskCodex(server)

    def tearDown(self):
        server.DB=self.old_db;self.temp.cleanup()

    def payload(self):
        return dict(projectId=self.project['id'],threadId=CHAT,requestId=str(uuid.uuid4()),
                    action='Edited action',reason='Edited reason',instructions='Also preserve the existing files.')

    def client(self,message=None):
        client=MagicMock();client.__enter__.return_value=client
        client.read_thread.return_value=dict(id=CHAT,name='Exact destination',updatedAt=int(time.time()))
        def call(method,body,**kwargs):
            if body.get('itemsView')=='notLoaded':return {'data':[]}
            return {'data':[{'id':'turn-1','startedAt':int(time.time()),'items':[
                {'type':'userMessage','content':[{'type':'text','text':message or 'Earlier project context'}]}]}]}
        client.call.side_effect=call
        return client

    def test_reviewed_send_preserves_edits_destination_and_receipt(self):
        body=self.payload();message=message_text(body)
        with patch('desk_codex.threading.Thread') as thread:
            receipt=self.service.send(body)
            duplicate=self.service.send(body)
        self.assertEqual(thread.call_count,1)
        self.assertEqual(receipt,duplicate)
        result=subprocess.CompletedProcess([],0,'Queued message '+str(uuid.uuid4())+' for thread '+CHAT+'.','')
        with patch('desk_codex.Client',return_value=self.client(message)),patch('desk_codex.executable',return_value='codex.exe'),\
             patch('desk_codex.subprocess.run',return_value=result) as run,patch('desk_codex.local_open') as opened:
            self.service._send_worker(receipt)
        args=run.call_args.args[0]
        self.assertEqual(args[args.index('--thread')+1],CHAT)
        self.assertEqual(args[args.index('--message')+1],message)
        self.assertNotIn('shell',run.call_args.kwargs)
        opened.assert_called_once_with(CHAT)
        saved=self.service.job(receipt['id'])
        self.assertEqual(saved['status'],'received')
        self.assertEqual(saved['turnId'],'turn-1')
        p=self.service.project(self.project['id'])
        self.assertEqual(p['nextAction'],'Edited action')
        self.assertEqual(p['blocker'],'Keep blocker')
        self.assertEqual(p['preferredChatId'],CHAT)
        self.assertEqual(p['activity'][0]['source'],'Codex request')

    def test_reused_send_id_cannot_change_destination_or_message(self):
        body=self.payload()
        with patch('desk_codex.threading.Thread'):
            self.service.send(body)
            with self.assertRaises(ValueError):self.service.send(dict(body,action='Different message'))
            with self.assertRaises(ValueError):self.service.send(dict(body,threadId=str(uuid.uuid4())))

    def test_timeout_is_unknown_and_is_not_automatically_retried(self):
        body=self.payload()
        with patch('desk_codex.threading.Thread'):receipt=self.service.send(body)
        with patch('desk_codex.Client',return_value=self.client()),patch('desk_codex.executable',return_value='codex.exe'),\
             patch('desk_codex.subprocess.run',side_effect=subprocess.TimeoutExpired('codex',40)) as run:
            self.service._send_worker(receipt)
        self.assertEqual(self.service.job(receipt['id'])['status'],'unknown')
        with patch('desk_codex.threading.Thread') as thread:self.service.send(body)
        thread.assert_not_called();self.assertEqual(run.call_count,1)
        self.assertEqual(self.service.project(self.project['id'])['nextAction'],'Original step')

    def test_open_rejects_chat_outside_selected_project(self):
        with patch('desk_codex.local_open') as opened:
            with self.assertRaises(ValueError):self.service.open_chat(dict(projectId=self.project['id'],threadId=CHAT))
        opened.assert_not_called()

    def test_old_matching_message_does_not_count_as_new_delivery(self):
        body=self.payload()
        with patch('desk_codex.threading.Thread'):receipt=self.service.send(body)
        receipt['beforeTurns']=['turn-1']
        self.assertFalse(self.service._confirm(receipt,self.client(message_text(body))))
        self.assertEqual(self.service.job(receipt['id'])['status'],'working')

    def test_audit_repairs_exact_id_url_and_preserves_current_notes(self):
        p=self.project
        p['chats']=[dict(id=CHAT,title='Old name',url='https://wrong.example/',at='2026-10-28T10:00:00Z')]
        server.save(p)
        client=self.client()
        def read(identity):
            self.assertEqual(identity,CHAT)
            server.update({'id':p['id'],'action':'log','note':'Manual note during audit'})
            return dict(id=CHAT,name='Verified chat title',updatedAt=int(time.time()))
        client.read_thread.side_effect=read
        with patch('desk_codex.Client',return_value=client):summary=self.service.audit()
        saved=self.service.project(p['id'])
        self.assertEqual(summary['verified'],1)
        self.assertEqual(saved['chats'][0]['url'],'codex://threads/'+CHAT)
        self.assertEqual(saved['chats'][0]['title'],'Verified chat title')
        self.assertTrue(any(a['note']=='Manual note during audit' for a in saved['activity']))
        self.assertEqual(saved['nextAction'],'Original step')

    def test_recommendation_reads_context_without_mutating_project(self):
        def fake_run(args,**kwargs):
            self.assertIn('Earlier project context',kwargs['input'])
            self.assertIn('--ephemeral',args);self.assertIn('read-only',args)
            Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({'action':'Check the next milestone','reason':'The previous step has finished.'}),encoding='utf-8')
            return subprocess.CompletedProcess(args,0,'','')
        with patch('desk_codex.Client',return_value=self.client()),patch('desk_codex.executable',return_value='codex.exe'),patch('desk_codex.subprocess.run',side_effect=fake_run):
            answer=self.service.recommendation(dict(projectId=self.project['id'],threadId=CHAT))
        self.assertEqual(answer['threadId'],CHAT);self.assertTrue(answer['reason'])
        self.assertEqual(self.service.project(self.project['id']),self.project)

if __name__=='__main__':unittest.main()
