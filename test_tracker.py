"""Behavior checks use a temporary database, never Michael's saved project data."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from unittest.mock import patch

import server

class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = server.DB
        self.old_export,self.old_index = server.EXPORT,server.INDEX
        server.DB = Path(self.temp.name) / 'test.sqlite3'
        server.EXPORT=Path(self.temp.name)/'fixture-export.json'
        server.INDEX=Path(self.temp.name)/'missing-index.json'
        server.EXPORT.write_text(json.dumps({'checkedAt':'2026-10-29T11:00:00Z',
            'projects':[{'projectId':'fixture','projectKind':'local','label':'Fixture project','path':self.temp.name}],
            'threads':[{'id':'fixture-chat','projectId':'fixture','kind':'codex','title':'Fixture planning','updatedAt':'2026-10-29T10:00:00Z'}]}),encoding='utf-8')
        server.initialize()

    def tearDown(self):
        server.DB = self.old_db
        server.EXPORT,server.INDEX = self.old_export,self.old_index
        self.temp.cleanup()

    def test_suggestion_review_preserves_last_worked_and_manual_edits(self):
        p=server.new_project('Business plan', 'Business')
        server.event(p, '2026-10-28T10:00:00+00:00', 'Outlined offer', 'Manual update', 'old')
        p['suggestion']={'text':'Draft the pricing page'}
        server.save(p)
        p=server.update({'id':p['id'], 'action':'accept'})
        self.assertEqual(p['nextAction'],'Draft the pricing page')
        self.assertEqual(p['activity'][0]['id'],'old')
        server.update({'id':p['id'], 'nextAction':'Test pricing with three customers'})
        # A source refresh must not replace the accepted action.
        server.sync_codex()
        p=next(x for x in server.load_projects() if x['id']==p['id'])
        self.assertEqual(p['nextAction'],'Test pricing with three customers')
        p=server.update({'id':p['id'], 'action':'log','note':'Chose the customer segment'})
        self.assertEqual(p['activity'][0]['note'],'Chose the customer segment')
        saved=next(x for x in server.load_projects() if x['id']==p['id'])
        self.assertEqual(saved['name'],'Business plan')

    def test_canonical_project_path_survives_old_exports_and_restart_repair(self):
        server.sync_codex()
        canonical=str(Path(self.temp.name)/'Relocated Project')
        server.metadata('projectPathOverrides',{'fixture':canonical})
        server.sync_codex()
        p=next(p for p in server.load_projects() if p['id']=='fixture')
        self.assertEqual(p['path'],canonical)
        activity=list(p['activity'])
        # Simulate an older still-running server importing its stale snapshot.
        p['path']='old location';server.save(p)
        server.apply_project_path_overrides()
        p=next(p for p in server.load_projects() if p['id']=='fixture')
        self.assertEqual(p['path'],canonical)
        self.assertEqual(p['activity'],activity)
        self.assertEqual(len(p['chats']),1)

    def test_dismissed_setup_suggestion_stays_dismissed(self):
        server.sync_codex()
        p=next(p for p in server.load_projects() if p['suggestion'])
        server.update({'id':p['id'],'action':'dismiss'})
        server.sync_codex()
        p=next(x for x in server.load_projects() if x['id']==p['id'])
        self.assertIsNone(p['suggestion'])

    def test_http_rejects_cross_origin_mutation_and_invalid_payload(self):
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True); thread.start()
        url=f'http://127.0.0.1:{http.server_port}'
        try:
            for origin, body, expected in [('https://example.com',{},403),(url,[],400)]:
                request=urllib.request.Request(url+'/api/projects',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':origin})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code,expected)
            with urllib.request.urlopen(url+'/api/projects') as response:
                self.assertEqual(json.load(response)['projects'],[])
        finally:
            http.shutdown(); http.server_close(); thread.join()

    def test_new_types_and_agency_survive_reload(self):
        for kind in ('Website','App'):
            saved=server.update({'name':kind+' project','kind':kind})
            self.assertEqual(saved['kind'],kind)
        with self.assertRaisesRegex(ValueError,'agency'):
            server.update({'name':'Document job','kind':'Documents Render'})
        p=server.update({'name':'Document job','kind':'Documents Render','agency':'  Example County Library  '})
        loaded=next(x for x in server.load_projects() if x['id']==p['id'])
        self.assertEqual(loaded['agency'],'Example County Library')
        server.update({'id':p['id'],'blocker':'Waiting on the source document'})
        self.assertEqual(next(x for x in server.load_projects() if x['id']==p['id'])['agency'],'Example County Library')

    def test_completion_records_history_is_idempotent_and_rejects_stale_form(self):
        p=server.update({'name':'Completion test','nextAction':'Draft the proposal','blocker':'Awaiting source files','status':'Waiting'})
        payload=dict(id=p['id'],action='complete-action',expectedAction='Draft the proposal',requestId=str(uuid.uuid4()),
                     nextAction='Review the proposal',note='First draft saved')
        result=server.update(payload)
        self.assertEqual(result['nextAction'],'Review the proposal')
        self.assertEqual(result['completedActions'][0]['action'],'Draft the proposal')
        self.assertEqual(result['completedActions'][0]['note'],'First draft saved')
        self.assertEqual(result['activity'][0]['source'],'Completed action')
        self.assertEqual(result['activity'][0]['at'],result['completedActions'][0]['at'])
        self.assertEqual(result['status'],'Waiting')
        self.assertEqual(result['blocker'],'Awaiting source files')
        retried=server.update(payload)
        self.assertEqual(len(retried['completedActions']),1)
        self.assertEqual(len(retried['activity']),1)
        with self.assertRaisesRegex(ValueError,'changed'):
            server.update(dict(payload,requestId=str(uuid.uuid4())))
        result=server.update(dict(payload,expectedAction='Review the proposal',requestId=str(uuid.uuid4()),nextAction='',note=''))
        self.assertEqual(result['nextAction'],'')
        self.assertEqual(len(result['completedActions']),2)
        with self.assertRaisesRegex(ValueError,'no next action'):
            server.update(dict(payload,requestId=str(uuid.uuid4())))
        server.sync_codex()
        reloaded=next(x for x in server.load_projects() if x['id']==p['id'])
        self.assertEqual(reloaded['completedActions'],result['completedActions'])
        self.assertEqual(reloaded['nextAction'],'')
        self.assertIsNone(reloaded['suggestion'])

    def test_chat_move_transfers_activity_and_survives_stale_import(self):
        source=server.new_project('Source',identity='source')
        source['codexProjectId']='source'
        target=server.new_project('Target',identity='target')
        target['codexProjectId']='target'
        target['nextAction']='Keep my accepted action'
        chat={'id':'chat-1','title':'Document planning','url':'codex://threads/chat-1','at':'2026-10-29T10:00:00+00:00'}
        source['chats']=[chat]
        server.event(source,chat['at'],chat['title'],'Codex chat activity','codex:chat-1')
        server.event(source,'2026-10-28T09:00:00+00:00','Other work','Manual update','manual')
        server.save(source); server.save(target)
        moved=server.move_chat({'threadId':'chat-1','targetProjectId':'target','native':True})
        self.assertEqual(moved['nativeStatus'],'pending')
        old_export,old_index=server.EXPORT,server.INDEX
        try:
            server.EXPORT=Path(self.temp.name)/'export.json'; server.INDEX=Path(self.temp.name)/'missing.json'
            server.EXPORT.write_text(json.dumps({'checkedAt':'2026-10-29T11:00:00+00:00','projects':[],
                'threads':[{'id':'chat-1','projectId':'source','kind':'codex','title':'Document planning',
                'updatedAt':1793268000}]}),encoding='utf-8')
            server.sync_codex()
        finally:
            server.EXPORT,server.INDEX=old_export,old_index
        rows={p['id']:p for p in server.load_projects()}
        self.assertEqual(rows['source']['chats'],[])
        self.assertEqual(rows['source']['activity'][0]['id'],'manual')
        self.assertEqual(rows['target']['chats'][0]['id'],'chat-1')
        self.assertEqual(rows['target']['nextAction'],'Keep my accepted action')
        self.assertEqual(rows['target']['activity'][0]['id'],'codex:chat-1')
        with self.assertRaisesRegex(ValueError,'different'):
            server.move_chat({'threadId':'chat-1','targetProjectId':'target'})
        with self.assertRaises(ValueError):
            server.move_chat({'threadId':'missing','targetProjectId':'target'})

    def test_activity_orders_actual_times_and_refreshes_without_duplicate(self):
        p=server.new_project('Timestamp test')
        server.event(p,'2026-10-29T23:00:00Z','Earlier','Manual update','earlier')
        server.event(p,'2026-10-29T19:00:00-05:00','Later','Codex chat activity','later')
        self.assertEqual(p['activity'][0]['id'],'later')
        server.event(p,'2026-10-30T01:00:00Z','Newest chat update','Codex chat activity','later')
        self.assertEqual(len(p['activity']),2)
        self.assertEqual(p['activity'][0]['note'],'Newest chat update')
        server.event(p,'2026-10-29T20:00:00Z','Stale update','Codex chat activity','later')
        self.assertEqual(p['activity'][0]['note'],'Newest chat update')

    def test_github_refresh_preserves_manual_work_saved_during_request(self):
        p=server.update({'name':'Concurrent refresh','repo':'owner/project','nextAction':'Keep this action'})
        fetching=threading.Event();resume=threading.Event();failures=[]
        def fake_gh(*args):
            path=args[1]
            if '/issues?' in path:return []
            if '/commits?' in path:
                fetching.set()
                if not resume.wait(5):raise RuntimeError('Test did not resume the request')
                return [{'sha':'commit1','commit':{'committer':{'date':'2026-10-28T10:00:00Z'},'message':'Older commit'}}]
            return {'html_url':'https://github.com/owner/project'}
        def refresh():
            try:server.sync_github(p)
            except Exception as e:failures.append(e)
        with patch.object(server,'gh',side_effect=fake_gh):
            worker=threading.Thread(target=refresh);worker.start()
            try:
                self.assertTrue(fetching.wait(5))
                server.update({'id':p['id'],'action':'log','note':'Planning while GitHub refreshes'})
            finally:resume.set();worker.join(7)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures,[])
        saved=next(x for x in server.load_projects() if x['id']==p['id'])
        self.assertTrue(any(a['note']=='Planning while GitHub refreshes' for a in saved['activity']))
        self.assertEqual(saved['nextAction'],'Keep this action')

    def test_older_codex_snapshot_does_not_regress_chat_link(self):
        p=server.new_project('Snapshot test',identity='snapshot-project')
        p['chats']=[dict(id='chat-stale',title='Newer title',url='codex://threads/chat-stale',at='2026-10-30T01:00:00+00:00')]
        server.event(p,p['chats'][0]['at'],'Newer title','Codex chat activity','codex:chat-stale');server.save(p)
        old_export,old_index=server.EXPORT,server.INDEX
        try:
            server.EXPORT=Path(self.temp.name)/'old.json';server.INDEX=Path(self.temp.name)/'missing'
            server.EXPORT.write_text(json.dumps({'checkedAt':'2026-10-29T11:00:00Z','threads':[
                dict(id='chat-stale',projectId=p['id'],kind='codex',updatedAt='2026-10-29T10:00:00Z',title='Old title')]}),encoding='utf-8')
            server.sync_codex()
        finally:server.EXPORT,server.INDEX=old_export,old_index
        saved=next(x for x in server.load_projects() if x['id']==p['id'])
        self.assertEqual(saved['chats'][0]['title'],'Newer title')
        self.assertEqual(saved['activity'][0]['note'],'Newer title')

    def test_snapshot_keeps_repaired_alias_and_verified_connection(self):
        p=server.new_project('Correct project',identity='right-project')
        p['chats']=[dict(id='correct-chat',title='Correct title',url='codex://threads/correct-chat',
            at=server.utc_stamp('2026-10-29T10:00:00Z'),connectionStatus='verified',checkedAt='2026-10-29T11:00:00Z')]
        server.save(p)
        server.metadata('chatAliases',{'bad-chat':dict(id='correct-chat',projectId=p['id'],title='Correct title')})
        server.EXPORT.write_text(json.dumps({'checkedAt':'2026-10-29T12:00:00Z','threads':[
            dict(id='bad-chat',projectId='wrong-project',kind='codex',updatedAt='2026-10-29T10:00:00Z',title='Wrong title')]}),encoding='utf-8')
        server.sync_codex()
        saved=next(x for x in server.load_projects() if x['id']==p['id'])
        self.assertEqual(len(saved['chats']),1)
        self.assertEqual(saved['chats'][0]['id'],'correct-chat')
        self.assertEqual(saved['chats'][0]['connectionStatus'],'verified')
        self.assertEqual(saved['chats'][0]['title'],'Correct title')

    def test_action_reason_tracks_edits_acceptance_and_completion(self):
        p=server.update({'name':'Reason test','nextAction':'First step'})
        p['nextActionReason']='Reason for first step';server.save(p)
        saved=server.update({'id':p['id'],'blocker':'Waiting on files'})
        self.assertEqual(saved['nextActionReason'],'Reason for first step')
        saved=server.update({'id':p['id'],'nextAction':'Changed step'})
        self.assertNotIn('nextActionReason',saved)
        saved['suggestion']={'text':'Suggested step','reason':'Because it follows the milestone'};server.save(saved)
        saved=server.update({'id':p['id'],'action':'accept'})
        self.assertEqual(saved['nextActionReason'],'Because it follows the milestone')
        saved=server.update({'id':p['id'],'action':'complete-action','requestId':str(uuid.uuid4()),
            'expectedAction':'Suggested step','nextAction':'Replacement'})
        self.assertNotIn('nextActionReason',saved)

if __name__=='__main__':
    unittest.main()
