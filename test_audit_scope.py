import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import audit_scope


class AuditScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'project';self.source.mkdir()
        (self.source/'.git').mkdir()
        self.other=self.root/'candidate';self.other.mkdir()
        self.project=dict(id='fixture',name='Project',path=str(self.source))
        self.store=SimpleNamespace(ROOT=self.source)
        self.git=patch('audit_scope.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=f'worktree {self.source.as_posix()}\nbranch refs/heads/old\n\nworktree {self.other.as_posix()}\nbranch refs/heads/new\n'))
        self.git.start()
    def tearDown(self):self.git.stop();self.temp.cleanup()
    def test_multiple_worktrees_require_choice_and_all_is_explicit(self):
        with self.assertRaisesRegex(ValueError,'multiple folders'):audit_scope.choose(self.store,self.project)
        self.assertEqual(audit_scope.choose(self.store,self.project,'all'),[str(self.source),str(self.other)])
        self.assertEqual(audit_scope.choose(self.store,self.project,[str(self.other)]),[str(self.other)])
    def test_subprojects_are_found_but_dependencies_are_not(self):
        for name in ['backend','node_modules']:
            child=self.source/name;child.mkdir();(child/'package.json').write_text('{}')
        found=[row['path'] for row in audit_scope.discover(self.store,self.project)]
        self.assertIn(str(self.source/'backend'),found);self.assertNotIn(str(self.source/'node_modules'),found)
    def test_outside_or_stale_selection_cannot_bypass_discovery(self):
        with self.assertRaises(ValueError):audit_scope.choose(self.store,self.project,[str(self.root/'unrelated')])
        with self.assertRaises(ValueError):audit_scope.choose(self.store,self.project,[])
    def test_all_runs_each_folder_and_retains_worst_grade_and_evidence(self):
        calls=[]
        def run(project):
            calls.append(project['path'])
            return dict(grade='A' if project['path']==str(self.source) else 'D',ready=project['path']==str(self.source),findings=[dict(title='Finding')],checks=[],limitations=[],fixPrompt='Fix source',markdown='Full evidence')
        folders=[str(self.source),str(self.other)]
        report=audit_scope.run_scoped(self.project,folders,'finish-team',run)
        self.assertEqual(calls,folders);self.assertEqual(report['grade'],'D');self.assertFalse(report['ready'])
        self.assertEqual(report['auditedFolders'],folders);self.assertEqual(len(report['folderReports']),2)
        self.assertIn(str(self.other),report['fixPrompt']);self.assertEqual(len(report['findings']),2)
    def test_both_operations_reject_ambiguous_scope_before_starting(self):
        import server
        from desk_codex import DeskCodex
        with patch.object(server,'DB',self.root/'test.sqlite3'):
            server.initialize();p=server.update(dict(name='Project',path=str(self.source)))
            service=DeskCodex(server)
            for action in ['finish-team','advisors']:
                with self.assertRaisesRegex(ValueError,'multiple folders'):service.control.control(dict(projectId=p['id'],action=action))
                self.assertNotEqual(service.project(p['id']).get('workState',{}).get('phase'),'operation')
                with patch('work_control.threading.Thread'):
                    selected=service.control.control(dict(projectId=p['id'],action=action,auditFolders=[str(self.other)]))
                self.assertEqual(selected['workState']['auditFolders'],[str(self.other)])
                selected['workState']=dict(phase='idle');server.save(selected)

    def test_advisors_only_shelve_when_every_selected_folder_does(self):
        def run(project):
            shelved=project['path']==str(self.source)
            verdict='shelve' if shelved else 'continue'
            return dict(decision=verdict,summary='Fixture',advisors=[dict(name='Advisor',role='coder',verdict=verdict,status='complete')],votes={verdict:3},fixPrompts=[] if shelved else [dict(title='Fix',prompt='Inspect code')],shelveReasons=['Reason'] if shelved else [],limitations=[],markdown='Evidence')
        report=audit_scope.run_scoped(self.project,[str(self.source),str(self.other)],'advisors',run)
        self.assertEqual(report['decision'],'split');self.assertEqual(len(report['fixPrompts']),1)
        self.assertIn(str(self.other),report['fixPrompts'][0]['prompt'])
        report=audit_scope.run_scoped(self.project,[str(self.source),str(self.source)],'advisors',run)
        self.assertEqual(report['decision'],'shelve');self.assertEqual(report['fixPrompts'],[])
