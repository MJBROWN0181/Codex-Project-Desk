"""Direct suggestion acceptance uses the existing durable send reservation."""
from pathlib import Path
import tempfile,unittest,uuid
from unittest.mock import patch
import server
from desk_codex import DeskCodex,message_text

CHAT='00000000-0000-4000-8000-000000000001'
OTHER='00000000-0000-4000-8000-000000000002'
class SuggestionSendTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_db=server.DB;server.DB=Path(self.temp.name)/'suggestion.sqlite3';server.initialize()
        self.p=server.new_project('Suggestion fixture');self.p.update(status='Unreviewed',nextAction='Keep my old plan',preferredChatId=CHAT,chats=[{'id':OTHER},{'id':CHAT}],suggestion={'text':'Implement the displayed step','reason':'It resolves the current blocker.','source':'Codex agent','at':server.now()})
        server.save(self.p);self.service=DeskCodex(server)
    def tearDown(self):server.DB=self.old_db;self.temp.cleanup()
    def body(self):return dict(projectId=self.p['id'],requestId=str(uuid.uuid4()),suggestion=dict(self.p['suggestion']))
    def test_exact_suggestion_preferred_chat_no_manual_conversion_and_one_send(self):
        draft=dict(threadId=CHAT,action='Keep my unsent draft',reason='Private notes',instructions='Do not lose these')
        server.save_draft(dict(projectId=self.p['id'],expectedRevision=0,draft=draft))
        body=self.body()
        with patch('desk_codex.threading.Thread') as worker:
            receipt=self.service.send_suggestion(dict(body,threadId=OTHER))
            self.assertEqual(receipt,self.service.send_suggestion(body))
        self.assertEqual(worker.call_count,1);self.assertEqual(receipt['threadId'],CHAT)
        self.assertEqual(receipt['message'],message_text(dict(action=self.p['suggestion']['text'],reason=self.p['suggestion']['reason'])))
        saved=self.service.project(self.p['id']);self.assertEqual(saved['workState']['phase'],'sending');self.assertEqual(saved['status'],'Active')
        self.assertIsNone(saved['suggestion']);self.assertEqual(saved['nextAction'],'Keep my old plan');self.assertEqual(saved['actionDraft']['action'],draft['action'])
        self.assertTrue(receipt['preserveActionDraft'])
        with self.assertRaises(ValueError):self.service.send_suggestion(dict(body,suggestion=dict(body['suggestion'],text='Different task')))
    def test_stale_or_changed_suggestion_is_not_sent(self):
        body=self.body();p=self.service.project(self.p['id']);p['suggestion']['text']='Newer suggestion';server.save(p)
        with patch('desk_codex.threading.Thread') as worker:
            with self.assertRaisesRegex(ValueError,'suggestion changed'):self.service.send_suggestion(body)
        worker.assert_not_called();self.assertEqual(self.service.project(p['id'])['suggestion']['text'],'Newer suggestion')
    def test_missing_ambiguous_or_cloud_preferred_chat_never_guesses(self):
        for chats,preferred in [([],None),([{'id':CHAT},{'id':OTHER}],None),([{'id':CHAT,'hostId':'cloud'},{'id':OTHER}],CHAT),([{'id':CHAT,'connectionStatus':'unavailable'}],CHAT)]:
            p=self.service.project(self.p['id']);p.update(chats=chats,preferredChatId=preferred);server.save(p)
            with patch('desk_codex.threading.Thread') as worker:
                with self.assertRaisesRegex(ValueError,'Review and send'):self.service.send_suggestion(self.body())
            worker.assert_not_called();self.assertEqual(self.service.project(p['id'])['suggestion'],self.p['suggestion'])
    def test_single_linked_local_chat_is_used_and_paused_or_busy_still_hold(self):
        p=self.service.project(self.p['id']);p.update(chats=[{'id':CHAT}],preferredChatId=None,workPaused=True);server.save(p)
        with self.assertRaisesRegex(ValueError,'Resume'):self.service.send_suggestion(self.body())
        p.update(workPaused=False,workState={'phase':'working'});server.save(p)
        with self.assertRaises(ValueError):self.service.send_suggestion(self.body())
        p['workState']={};p['suggestion']=dict(self.p['suggestion']);server.save(p)
        with patch('desk_codex.threading.Thread'):receipt=self.service.send_suggestion(self.body())
        self.assertEqual(receipt['threadId'],CHAT)
    def test_old_accept_route_cannot_silently_save_a_manual_action(self):
        with self.assertRaisesRegex(ValueError,'Reload'):server.update(dict(id=self.p['id'],action='accept'))
        self.assertEqual(self.service.project(self.p['id'])['nextAction'],'Keep my old plan')
