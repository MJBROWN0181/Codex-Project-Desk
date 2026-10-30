"""Unreviewed is an import state, cleared by actual review/work actions."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import server
from desk_codex import DeskCodex
from test_codex_actions import CHAT

class ReviewStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_db=server.DB
        server.DB=Path(self.temp.name)/'review.sqlite3';server.initialize()
    def tearDown(self):server.DB=self.old_db;self.temp.cleanup()
    def imported(self):
        p=server.new_project('Imported project');p['status']='Unreviewed'
        p['suggestion']=dict(text='Review next step',source='Codex metadata')
        server.event(p,'2026-10-28T10:00:00Z','Imported chat','Codex chat activity','imported')
        server.save(p);return p

    def test_review_actions_clear_label_without_fabricating_activity(self):
        for action in ('dismiss','reviewed'):
            p=self.imported();updated=server.update(dict(id=p['id'],action=action))
            self.assertEqual(updated['status'],'Active');self.assertTrue(updated['reviewedAt'])
            self.assertEqual(updated['activity'],p['activity'])
        p=self.imported();self.assertEqual(server.update(dict(id=p['id'],name='Edited project',status='Unreviewed'))['status'],'Active')

    def test_pins_and_imported_activity_do_not_claim_review(self):
        p=self.imported();self.assertEqual(server.update(dict(id=p['id'],pinned=True))['status'],'Unreviewed')
        self.assertEqual(server.reconcile_review_statuses(),0)

    def test_sending_marks_reviewed_even_before_delivery(self):
        p=self.imported();service=DeskCodex(server)
        with patch('desk_codex.threading.Thread'):
            service.send(dict(projectId=p['id'],threadId=CHAT,requestId=str(uuid.uuid4()),action='My reviewed step'))
        self.assertEqual(service.project(p['id'])['status'],'Active')

    def test_repair_legacy_evidence_preserves_other_statuses(self):
        stale=self.imported();stale['nextAction']='Accepted before the fix';server.save(stale)
        untouched=self.imported()
        paused=self.imported();paused.update(status='Paused',nextAction='Paused step');server.save(paused)
        done=self.imported();done.update(status='Complete',nextAction='Old step');server.save(done)
        self.assertEqual(server.reconcile_review_statuses(),1)
        projects={p['id']:p for p in server.load_projects()}
        self.assertEqual(projects[stale['id']]['status'],'Active')
        self.assertEqual(projects[stale['id']]['activity'],stale['activity'])
        self.assertEqual(projects[untouched['id']]['status'],'Unreviewed')
        self.assertEqual(projects[paused['id']]['status'],'Paused')
        self.assertEqual(projects[done['id']]['status'],'Complete')
        self.assertEqual(server.reconcile_review_statuses(),0)

    def test_saved_review_draft_marks_active_and_manual_status_survives(self):
        p=self.imported()
        server.save_draft(dict(projectId=p['id'],expectedRevision=0,draft=dict(action='Edited next step')))
        current=next(x for x in server.load_projects() if x['id']==p['id']);self.assertEqual(current['status'],'Active')
        server.update(dict(id=p['id'],status='Waiting'))
        self.assertEqual(server.update(dict(id=p['id'],name='Still waiting'))['status'],'Waiting')

if __name__=='__main__':unittest.main()
