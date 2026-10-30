"""Archive is a reversible visibility flag, never project deletion."""
import copy
from pathlib import Path
import tempfile
import unittest
import server

class ProjectArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_db=server.DB
        server.DB=Path(self.temp.name)/'archive.sqlite3';server.initialize()
        self.p=server.new_project('Keep all project data')
        self.p.update(pinned=True,nextAction='Finish work',actionDraft={'action':'Unsent draft'},completedActions=[{'id':'done','action':'Earlier work'}],chats=[{'id':'chat','title':'Keep chat','url':'codex://threads/chat','at':server.now()}],workState={'phase':'working','threadId':'chat'})
        server.event(self.p,server.now(),'Real activity','Manual update','real')
        server.save(self.p)
    def tearDown(self):server.DB=self.old_db;self.temp.cleanup()
    def test_archive_and_restore_preserve_everything_else_and_running_work(self):
        before=copy.deepcopy(self.p)
        archived=server.update(dict(id=self.p['id'],archived=True))
        self.assertTrue(archived['archived']);self.assertTrue(archived['archivedAt'])
        for key,value in before.items():self.assertEqual(archived[key],value,key)
        self.assertEqual(len(server.load_projects()),1)
        restored=server.update(dict(id=self.p['id'],archived=False))
        self.assertFalse(restored['archived']);self.assertIsNone(restored['archivedAt'])
        for key,value in before.items():self.assertEqual(restored[key],value,key)
    def test_invalid_archive_value_rejected_and_repeat_is_idempotent(self):
        with self.assertRaises(ValueError):server.update(dict(id=self.p['id'],archived='true'))
        first=server.update(dict(id=self.p['id'],archived=True))
        again=server.update(dict(id=self.p['id'],archived=True))
        self.assertEqual(first['archiveUpdatedAt'],again['archiveUpdatedAt'])
    def test_saved_archive_survives_reload_and_later_activity_updates(self):
        server.update(dict(id=self.p['id'],archived=True));server.initialize()
        p=server.load_projects()[0];self.assertTrue(p['archived'])
        p['workState']={'phase':'idle'};server.event(p,server.now(),'Completed existing work','Codex completion','turn')
        server.save(p);self.assertTrue(server.load_projects()[0]['archived'])

if __name__=='__main__':unittest.main()
