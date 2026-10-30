import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from advisor_panel import AdvisorPanel, ROLES, run_advisor

def review(verdict='continue'):
    return dict(grade='C',verdict=verdict,confidence='medium',summary='Specific assessment.',
        reasons=['The project has a concrete constraint.'],strengths=['A defined audience.'],risks=['A verified gap.'],
        evidence=[dict(kind='project',reference='README.md:3',finding='The current goal and gap are stated.')],
        unconventionalOpportunity='A small specialist audience may be viable if this gap is fixed.',
        reconsiderIf='Verified usage or revised constraints change the conclusion.',
        fixes=[dict(title='Verify the gap',why='The current behavior is incomplete.',scope='Targeted workflow',priority='high')],limitations=[])

class AdvisorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.project=dict(id='fixture',name='Advisor fixture',kind='App',path=str(self.root),activity=[])
        self.store=SimpleNamespace(ROOT=self.root)
    def tearDown(self):self.temp.cleanup()
    def runner(self,votes=None,failed=None,answers=None):
        calls=[];lock=threading.Lock()
        def run(**args):
            with lock:calls.append(args)
            if args['phase']=='review':
                if args['role']==failed:raise RuntimeError('Fixture reviewer unavailable')
                return copy.deepcopy((answers or {}).get(args['role']) or review((votes or {}).get(args['role'],'continue')))
            return dict(prompts=[dict(title='Fix the verified gap',prompt='Inspect the cited workflow, apply the focused fix and verify it with existing checks.',priority='high')],limitations=[])
        return run,calls
    def test_three_roles_grade_and_create_prompts_with_research(self):
        runner,calls=self.runner();report=AdvisorPanel(self.store,runner=runner).run(self.project)
        self.assertEqual(set(a['role'] for a in report['advisors']),set(ROLES))
        self.assertEqual(report['decision'],'continue');self.assertEqual(len(report['fixPrompts']),3)
        self.assertTrue(report['readOnly']);self.assertEqual(len(calls),6)
        self.assertTrue(all(c['research'] for c in calls if c['phase']=='review'))
        self.assertTrue(all(not c['research'] for c in calls if c['phase']=='prompts'))
    def test_unanimous_shelve_never_runs_prompt_generation(self):
        runner,calls=self.runner({role:'shelve' for role in ROLES})
        report=AdvisorPanel(self.store,runner=runner).run(self.project)
        self.assertEqual(report['decision'],'shelve');self.assertEqual(report['fixPrompts'],[])
        self.assertEqual(len(calls),3);self.assertTrue(all(c['phase']=='review' for c in calls))
        self.assertTrue(all(a['fixes']==[] for a in report['advisors']))
        self.assertEqual(len(report['shelveReasons']),3);self.assertIn('No fix prompts were generated',report['markdown'])
    def test_two_negative_votes_do_not_suppress_other_supported_fixes(self):
        runner,_=self.runner({'coder':'shelve','social':'shelve','marketing':'continue'})
        report=AdvisorPanel(self.store,runner=runner).run(self.project)
        self.assertEqual(report['decision'],'split');self.assertTrue(report['fixPrompts'])
    def test_unavailable_advisor_is_not_a_negative_vote(self):
        runner,_=self.runner({role:'shelve' for role in ROLES},failed='social')
        report=AdvisorPanel(self.store,runner=runner).run(self.project)
        self.assertEqual(report['decision'],'inconclusive');self.assertEqual(report['votes']['shelve'],2)
        self.assertEqual(report['advisors'][1]['status'],'unavailable')
    def test_unsupported_shelving_and_fake_urls_do_not_form_consensus(self):
        answer=review('shelve');answer['evidence']=[dict(kind='web',reference='javascript:alert(1)',finding='Unsupported claim.')]
        runner,_=self.runner({role:'shelve' for role in ROLES},answers={'social':answer})
        report=AdvisorPanel(self.store,runner=runner).run(self.project)
        self.assertEqual(report['decision'],'inconclusive');self.assertEqual(report['advisors'][1]['evidence'],[])
    def test_missing_source_does_not_prove_a_software_project_is_bad(self):
        runner,_=self.runner({role:'shelve' for role in ROLES})
        report=AdvisorPanel(self.store,runner=runner).run(dict(self.project,path=''),research=False)
        self.assertEqual(report['decision'],'inconclusive');self.assertEqual(report['advisors'][0]['grade'],'N/A')
        self.assertFalse(report['researchEnabled']);self.assertTrue(report['limitations'])
    def test_runner_enables_search_and_uses_read_only_sandbox(self):
        def execute(args,**kwargs):
            output=Path(args[args.index('--output-last-message')+1]);output.write_text(json.dumps(review()),encoding='utf-8')
            return SimpleNamespace(returncode=0)
        with patch('advisor_panel.executable',return_value='codex'),patch('advisor_panel.execute_cli',side_effect=execute) as run:
            run_advisor(role='coder',phase='review',prompt='Inspect fixture',cwd=self.root,schema={},timeout=30,research=True)
        command=run.call_args.args[0];self.assertIn('--search',command)
        self.assertEqual(command[command.index('--sandbox')+1],'read-only')
        self.assertNotIn('shell',run.call_args.kwargs)

class AdvisorOperationTests(unittest.TestCase):
    def test_separate_report_is_saved_without_overwriting_audit_or_archiving(self):
        import server
        from desk_codex import DeskCodex
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'DATA',Path(directory)),patch.object(server,'DB',Path(directory)/'operations.sqlite3'):
            server.initialize();p=server.new_project('Business concept','Business');p['auditReport']={'grade':'B'};server.save(p)
            service=DeskCodex(server)
            with patch('work_control.threading.Thread'):
                service.control.control(dict(projectId=p['id'],action='advisors'))
            active=service.project(p['id']);self.assertEqual(active['workState']['phase'],'operation')
            result=dict(decision='shelve',summary='All three agree.',markdown='Fixture report',advisors=[],fixPrompts=[])
            with patch('advisor_panel.AdvisorPanel.run',return_value=result) as run:
                service.control._operation(p['id'],'advisors',active['workState']['id'])
            saved=service.project(p['id']);self.assertEqual(saved['auditReport'],{'grade':'B'})
            self.assertEqual(saved['advisorReport']['decision'],'shelve');self.assertFalse(saved.get('archived',False))
            self.assertEqual(saved['workState']['phase'],'idle');self.assertTrue(run.call_args.kwargs['research'])
            self.assertEqual(len(list((Path(directory)/'reports').glob('*.md'))),1)

if __name__=='__main__':unittest.main()
