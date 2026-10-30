import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import server
from desk_codex import DeskCodex
from test_codex_actions import CHAT

class WorkflowFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=server.DB;server.DB=Path(self.temp.name)/'features.sqlite3';server.initialize()
        self.p=server.update({'name':'Feature fixture','nextAction':'Original step'})
    def tearDown(self):server.DB=self.old;self.temp.cleanup()

    def test_draft_round_trip_conflict_and_pin_preserve_project(self):
        draft=dict(threadId=CHAT,action=' Edited step ',reason='Why',instructions='Extra details')
        result=server.save_draft(dict(projectId=self.p['id'],expectedRevision=0,draft=draft))
        saved=next(p for p in server.load_projects() if p['id']==self.p['id'])
        self.assertEqual(saved['actionDraft']['action'],' Edited step ')
        self.assertEqual(saved['nextAction'],'Original step');self.assertEqual(saved['activity'],[])
        with self.assertRaisesRegex(ValueError,'another window'):
            server.save_draft(dict(projectId=self.p['id'],expectedRevision=0,draft=None))
        pinned=server.update({'id':self.p['id'],'pinned':True})
        self.assertTrue(pinned['pinned']);self.assertEqual(pinned['actionDraft']['instructions'],'Extra details')
        cleared=server.save_draft(dict(projectId=self.p['id'],expectedRevision=result['revision'],draft=None))
        self.assertIsNone(cleared['draft'])
        self.assertTrue(next(p for p in server.load_projects() if p['id']==self.p['id'])['pinned'])
        with self.assertRaises(ValueError):server.update({'id':self.p['id'],'pinned':'true'})

    def test_final_reply_excludes_commentary_and_does_not_fabricate_activity(self):
        self.p['chats']=[dict(id=CHAT,title='Verified conversation',hostId='local',at='2026-10-29T10:00:00Z')];server.save(self.p)
        class FakeClient:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def call(self,*args):return {'data':[{'id':'new-turn','status':'inProgress','startedAt':int(time.time()),'items':[
                {'type':'agentMessage','phase':'commentary','text':'Still working'}]},
                {'id':'done-turn','status':'completed','completedAt':1793268000,'items':[
                    {'type':'reasoning','text':'Do not display this'},
                    {'type':'agentMessage','phase':'final_answer','text':'Finished the milestone <script>unsafe()</script>'}]}]}
        with patch('desk_codex.Client',FakeClient):result=DeskCodex(server).refresh_replies()
        saved=next(p for p in server.load_projects() if p['id']==self.p['id'])
        self.assertEqual(result['refreshed'],1)
        self.assertEqual(saved['latestReply']['turnId'],'done-turn')
        self.assertNotIn('Still working',saved['latestReply']['text'])
        self.assertEqual(saved['activity'],[]);self.assertEqual(saved['nextAction'],'Original step')
        self.assertEqual(saved['latestReply']['title'],'Verified conversation')

if __name__=='__main__':unittest.main()
