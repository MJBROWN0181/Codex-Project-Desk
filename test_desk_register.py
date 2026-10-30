"""Registration tests never send messages or touch the real Project Desk DB."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
from urllib.request import Request, urlopen
import server
from desk_register import register

class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_db=server.DB
        self.folder=Path(self.temp.name)/'Project';self.folder.mkdir()
        server.DB=Path(self.temp.name)/'register.sqlite3';server.initialize()
        self.thread=str(uuid.uuid4());self.native=str(uuid.uuid4())
        self.chat=dict(id=self.thread,name='Current verified chat',updatedAt=1793300000,cwd=str(self.folder))
        self.body=dict(threadId=self.thread,nativeProjectId=self.native,name='Registered project',kind='Website',path=str(self.folder),repo='example/project',nextAction='Verify the next step',nextActionReason='It is still unfinished.')
    def tearDown(self):server.DB=self.old_db;self.temp.cleanup()
    def test_create_repeat_verify_and_import_do_not_duplicate(self):
        (self.folder/'index.html').write_text('<link rel="canonical" href="https://project.example/">')
        first=register(server,self.body,self.chat);again=register(server,self.body,self.chat)
        self.assertTrue(first['created']);self.assertFalse(again['created'])
        self.assertEqual(first['projectId'],self.native);self.assertEqual(len(server.load_projects()),1)
        p=server.load_projects()[0];self.assertEqual(p['websiteUrl'],'https://project.example/')
        self.assertEqual(p['nextAction'],'Verify the next step');self.assertEqual(len(p['chats']),1)
        self.assertEqual(len(p['activity']),1);self.assertEqual(p['preferredChatId'],self.thread)
        self.sync_fixture()
        self.assertEqual(len(server.load_projects()),1);self.assertEqual(len(server.load_projects()[0]['chats']),2)
    def sync_fixture(self):
        export=Path(self.temp.name)/'export.json'
        export.write_text(json.dumps(dict(checkedAt='2026-10-29T11:00:00Z',projects=[dict(projectId=self.native,projectKind='local',label='Native label',path=str(self.folder))],threads=[dict(id=str(uuid.uuid4()),projectId=self.native,kind='codex',title='Later imported chat',updatedAt='2026-10-29T10:00:00Z')])))
        with patch.object(server,'EXPORT',export),patch.object(server,'INDEX',Path(self.temp.name)/'missing.json'):server.sync_codex()
    def test_reuse_custom_card_and_native_alias_survives_import(self):
        p=server.update(dict(name='My curated name',path=str(self.folder)))
        result=register(server,self.body,self.chat)
        self.assertEqual(result['projectId'],p['id']);self.assertFalse(result['created'])
        self.assertEqual(result['name'],'My curated name')
        self.sync_fixture();self.assertEqual(len(server.load_projects()),1)
        self.assertEqual(server.load_projects()[0]['codexProjectId'],self.native)
        self.assertEqual(len(server.load_projects()[0]['chats']),2)
    def test_restore_preserves_work_state_queues_drafts_history_and_existing_fields(self):
        p=server.new_project('Keep name',identity=self.native)
        p.update(path=str(self.folder),status='Paused',kind='App',archived=True,pinned=True,nextAction='Curated step',blocker='Existing blocker',actionDraft={'action':'Unsent draft'},contentQueue=[{'id':'addition','text':'Keep queued content','state':'pending'}],completedActions=[{'id':'done','action':'Earlier action'}],preferredChatId='existing-chat',workState={'phase':'working','threadId':'existing-chat'})
        server.save(p);before=copy.deepcopy(p)
        result=register(server,self.body,self.chat);saved=server.load_projects()[0]
        self.assertTrue(result['restored']);self.assertFalse(saved['archived'])
        for key in ['name','status','kind','pinned','nextAction','blocker','actionDraft','contentQueue','completedActions','preferredChatId','workState']:
            self.assertEqual(saved[key],before[key],key)
    def test_wrong_chat_and_ambiguous_folder_fail_without_writes(self):
        with self.assertRaises(ValueError):register(server,self.body,dict(self.chat,id=str(uuid.uuid4())))
        self.assertEqual(server.load_projects(),[])
        for name in ['One','Two']:server.update(dict(name=name,path=str(self.folder)))
        before=server.load_projects()
        with self.assertRaises(ValueError):register(server,dict(self.body,nativeProjectId=''),self.chat)
        self.assertEqual(server.load_projects(),before)
    def test_existing_chat_is_reused_and_explicit_wrong_card_is_rejected(self):
        p=server.new_project('Original owner');p['chats']=[dict(id=self.thread,title='Old label',url='codex://threads/'+self.thread,at=server.now())];server.save(p)
        other=server.new_project('Other');server.save(other)
        result=register(server,self.body,self.chat);self.assertEqual(result['projectId'],p['id'])
        with self.assertRaises(ValueError):register(server,dict(self.body,projectId=other['id']),self.chat)
        self.assertEqual(len(server.load_projects()),2)
    def test_projectless_business_chat_and_invalid_fields(self):
        body=dict(threadId=self.thread,name='Business plan',kind='Business')
        result=register(server,body,dict(self.chat,cwd=str(Path.home())))
        self.assertEqual(result['kind'],'Business');self.assertEqual(result['path'],'')
        for field,value in [('repo','bad; command'),('websiteUrl','file:///secret'),('kind','Unknown')]:
            with self.assertRaises(ValueError):register(server,dict(body,**{field:value}),self.chat)
    def test_verifier_is_required_when_chat_is_not_supplied(self):
        with patch('desk_register.verify_chat',return_value=self.chat) as verify:
            register(server,self.body)
        verify.assert_called_once_with(self.body)
    def test_http_registration_advertises_support_and_confirms_saved_chat(self):
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
        root=f'http://127.0.0.1:{http.server_port}'
        try:
            request=Request(root+'/api/project/register',data=json.dumps(self.body).encode(),headers={'Origin':root,'Content-Type':'application/json'})
            with patch('desk_register.verify_chat',return_value=self.chat):
                with urlopen(request) as response:result=json.load(response)
            with urlopen(root+'/api/projects') as response:snapshot=json.load(response)
            self.assertTrue(snapshot['features']['projectRegister'])
            self.assertTrue(result['registered'])
            self.assertEqual(snapshot['projects'][0]['chats'][0]['id'],self.thread)
        finally:http.shutdown();http.server_close();worker.join()

if __name__=='__main__':unittest.main()
