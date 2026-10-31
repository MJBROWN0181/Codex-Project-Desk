"""Real local Git worktrees, no remotes, Codex execution, or production changes."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
from unittest.mock import MagicMock, patch

import project_folders as records
import worktree_workflow as workflow
from project_ops import ProjectOps, ProjectOperationError


@unittest.skipUnless(shutil.which('git'),'Git required for disposable worktree tests')
class WorktreeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pd-worktree-test-')
        self.root=Path(self.temp.name).resolve()
        # Verify the recursive cleanup boundary before populating the fixture.
        self.assertEqual(self.root.parent,Path(tempfile.gettempdir()).resolve())
        self.base=self.root/'Trunk';self.base.mkdir();self.work=self.root/'Search'
        self.hooks=self.root/'empty-hooks';self.hooks.mkdir()
        self.command(self.base,'init','-b','main')
        (self.base/'README.md').write_text('# Disposable checkout test\n\nLocal Git routing fixture. app.py prints a constant. No remote or release.\n',encoding='utf-8')
        (self.base/'app.py').write_text('print("baseline")\n',encoding='utf-8')
        self.command(self.base,'add','README.md','app.py')
        self.commit(self.base,'Seed local fixture')
        self.command(self.base,'worktree','add','-b','work/search',str(self.work),'HEAD')
        self.p=dict(id=str(uuid.uuid4()),name='Workspace',path=str(self.base),features=[],activeFeature='')
        records.scaffold(self.p,self.root/'Records')
        records.add_feature(self.p,'Search');self.p['activeFeature']='Search'

    def tearDown(self):self.temp.cleanup()

    def command(self,folder,*args):
        return subprocess.check_output(['git','-C',str(folder),*args],stderr=subprocess.STDOUT,text=True).strip()

    def commit(self,folder,message):
        # README skill: verify the displayed README and staged scope before
        # every disposable setup/checkpoint commit. No real project is committed.
        self.assertIn('Local Git routing fixture.',(folder/'README.md').read_text())
        staged=self.command(folder,'diff','--cached','--name-only').splitlines()
        self.assertTrue(set(staged)<= {'README.md','app.py'})
        self.command(folder,'-c','user.name=Local Workflow Test','-c','user.email=test@example.invalid',
                     '-c','commit.gpgsign=false','-c','core.hooksPath='+str(self.hooks),
                     'commit','--allow-empty','-m',message)

    def test_feature_routes_to_worktree_preserves_dirty_files(self):
        (self.work/'app.py').write_text('print("unfinished user work")\n',encoding='utf-8')
        before=self.command(self.work,'diff')
        result=records.prepare(self.p,'Continue search','folder',str(uuid.uuid4()))
        self.assertEqual(result['cwd'],str(self.work))
        self.assertNotEqual(result['cwd'],result['recordsScope'])
        self.assertEqual(result['sourceCheckout']['branch'],'work/search')
        self.assertIn('AGENTS.md',result['message']);self.assertIn('.agents/PROJECT-HANDOFF.md',result['message'])
        self.assertTrue(result['sourceCheckout']['status'])
        self.assertEqual(self.command(self.work,'diff'),before)

    def test_unbound_feature_never_falls_back_to_main(self):
        self.p['activeFeature']=''
        with self.assertRaisesRegex(ValueError,'Trunk is never the fallback'):
            records.prepare(self.p,'Change source','folder',str(uuid.uuid4()))
        records.add_feature(self.p,'Unmapped');self.p['activeFeature']='Unmapped'
        with self.assertRaises(ValueError):workflow.resolve(self.p)

    def test_explicit_binding_and_reject_main_or_other_repo(self):
        records.add_feature(self.p,'Search screen');self.p['activeFeature']='Search screen'
        workflow.bind(self.p,'Search screen',str(self.work))
        self.assertEqual(workflow.resolve(self.p)['path'],str(self.work))
        with self.assertRaises(ValueError):workflow.bind(self.p,'Search screen',str(self.base))
        with self.assertRaises(ValueError):workflow.bind(self.p,'Search screen',str(self.root))

    def test_branch_change_blocks_resolve_and_delivery(self):
        workflow.bind(self.p,'Search',str(self.work))
        receipt=records.prepare(self.p,'Continue','folder',str(uuid.uuid4()))
        self.command(self.work,'branch','-m','work/changed')
        with self.assertRaises(ValueError):workflow.resolve(self.p)
        with self.assertRaises(ValueError):workflow.verify_receipt(self.p,receipt)

    def test_commit_change_blocks_stale_delivery(self):
        receipt=records.prepare(self.p,'Continue','folder',str(uuid.uuid4()))
        self.commit(self.work,'Advance disposable checkout')
        with self.assertRaises(ValueError):workflow.verify_receipt(self.p,receipt)
        refreshed=workflow.continuation(self.p,receipt['sourceCheckout'])
        self.assertEqual(refreshed['head'],self.command(self.work,'rev-parse','HEAD'))
        self.assertNotEqual(refreshed['head'],receipt['sourceCheckout']['head'])

    def test_wrap_captures_git_and_preserves_project_handoff(self):
        established=self.work/'.agents'/'PROJECT-HANDOFF.md';established.parent.mkdir()
        established.write_text('Existing project handoff\n',encoding='utf-8')
        receipt=records.prepare(self.p,'Continue','folder',str(uuid.uuid4()));receipt['recordsFeature']='Search'
        state=dict(threadId=str(uuid.uuid4()),kind='wrap')
        turn=dict(id='wrap',status='completed',items=[dict(type='agentMessage',phase='final_answer',text='Done. Next: filters.')])
        records.record_turn(self.p,state,turn,receipt)
        saved=json.loads((Path(receipt['recordsSession'])/'session.json').read_text())
        self.assertEqual(saved['checkoutAtWrap']['branch'],'work/search')
        self.assertEqual(saved['checkoutAtWrap']['head'],self.command(self.work,'rev-parse','HEAD'))
        self.assertEqual(established.read_text(),'Existing project handoff\n')
        self.assertIn('Done. Next: filters.',records.prepare(self.p,'Next','folder',str(uuid.uuid4()))['message'])

    def test_generic_release_blocked_before_any_publish_commands(self):
        operation=ProjectOps(MagicMock())
        with patch.object(operation,'_git') as git,patch.object(operation,'_cmd') as command:
            with self.assertRaisesRegex(ProjectOperationError,'exact-commit'):
                operation.release(self.p)
        git.assert_not_called();command.assert_not_called()

    def test_broad_audits_read_only_and_fixes_only_selected_checkout(self):
        both=[str(self.base),str(self.work)]
        self.assertTrue(workflow.audit_is_read_only(self.p,both))
        self.assertTrue(workflow.audit_is_read_only(self.p,[str(self.base)]))
        self.assertFalse(workflow.audit_is_read_only(self.p,[str(self.work)]))
        with self.assertRaises(ValueError):workflow.safe_audit_fixes(self.p,both)
        workflow.safe_audit_fixes(self.p,[str(self.work)])

    def test_removed_worktree_and_detached_checkout_rejected(self):
        workflow.bind(self.p,'Search',str(self.work))
        self.command(self.work,'checkout','--detach')
        with self.assertRaises(ValueError):workflow.resolve(self.p)
