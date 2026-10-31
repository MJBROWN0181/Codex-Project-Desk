import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from finish_agents import AuditEngine, CodexError, ROLES, capture_baseline, execute_cli, run_agent, validate, REVIEW_SCHEMA


def check(result='passed'):
    return {'name': 'Existing tests', 'result': result, 'purpose': 'required', 'evidence': 'python -m unittest: 8 tests completed.'}


def finding():
    return {'title': 'Broken submit', 'severity': 'medium', 'required': True, 'evidence': 'form.py:22 loses state',
            'recommendation': 'Preserve input on error.', 'fixPrompt': 'Fix form.py:22 and verify submission.'}


class FakeRunner:
    def __init__(self, issue=False, limits=False, fail_role=None):
        self.calls = []
        self.issue = issue
        self.limits = limits
        self.fail_role = fail_role

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        role = kwargs['role']
        if role == self.fail_role:
            raise RuntimeError('Unavailable tool')
        if role == 'boss-plan':
            return {'summary': 'Plan', 'assignments': {r: 'Inspect actual project.' for r in ROLES}}
        if role == 'boss-fix':
            return {'summary': 'Fixed form.', 'changedFiles': ['form.py'], 'checks': [check()], 'limitations': [], 'readinessLimitations': []}
        if role == 'boss-report':
            return {'grade': 'A', 'summary': 'Ready after checks.', 'ready': True, 'findings': [],
                    'checks': [check()], 'limitations': [], 'readinessLimitations': [], 'fixPrompt': '', 'rerunRecommendation':{'when':'After material project changes.','why':'Refresh readiness evidence after behavior changes.','conditions':[]}}
        return {'summary': 'Inspected.', 'applicable': True,
                'findings': [finding()] if self.issue and 'round 1.' in kwargs['prompt'] else [],
                'checks': [check('not-run' if self.limits else 'passed')],
                'limitations': ['Real device not tested.'] if self.limits else [],
                'readinessLimitations': ['Real device not tested.'] if self.limits else []}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'project'
        self.folder.mkdir()
        self.store = SimpleNamespace(DATA=Path(self.temp.name) / 'desk-data')
        self.project = {'id': 'p1', 'name': 'Example', 'path': str(self.folder), 'kind': 'App'}

    def engine(self, runner):
        return AuditEngine(self.store, runner=runner, folder_resolver=lambda project: self.folder)

    @patch('finish_agents.capture_baseline', return_value={'existingWork': [], 'omitted': []})
    def test_team_has_boss_six_independent_reviewers_and_rechecks(self, state):
        runner = FakeRunner(issue=True)
        progress = []
        report = self.engine(runner).run(self.project, team=True, progress=progress.append)
        self.assertEqual(report['grade'], 'A')
        self.assertTrue(report['ready'])
        self.assertEqual(report['mode'], 'finish-team')
        self.assertEqual(len(report['rounds']), 2)
        self.assertEqual([c['role'] for c in runner.calls].count('boss-fix'), 1)
        for role in ROLES:
            self.assertEqual([c['role'] for c in runner.calls].count(role), 2)
        self.assertEqual(len(runner.calls), 15)
        self.assertEqual([c['role'] for c in runner.calls if c['sandbox'] == 'workspace-write'], ['boss-fix'])
        self.assertIn('readiness A', report['markdown'])
        self.assertEqual(progress[-1]['phase'], 'complete')

    @patch('finish_agents.capture_baseline', return_value={'existingWork': [{'path': 'unrelated.py', 'state': 'saved'}], 'omitted': []})
    def test_dirty_worktree_receives_authorized_focused_edits_with_preservation(self, state):
        runner = FakeRunner(issue=True)
        report = self.engine(runner).run(self.project)
        self.assertIn('boss-fix', [c['role'] for c in runner.calls])
        fix_prompt = next(c['prompt'] for c in runner.calls if c['role'] == 'boss-fix')
        self.assertIn('unrelated.py', fix_prompt)
        self.assertIn('Never revert, reset, stash, clean', fix_prompt)
        self.assertTrue(report['ready'])
        self.assertEqual(len(report['rounds'][1]), 1)

    @patch('finish_agents.capture_baseline', return_value={'existingWork': [], 'omitted': []})
    def test_limits_cannot_be_hidden_by_boss_a(self, state):
        report = self.engine(FakeRunner(limits=True)).run(self.project, team=True)
        self.assertEqual(report['grade'], 'B')
        self.assertIn('Real device not tested.', report['limitations'])
        self.assertTrue(any(c['result'] == 'not-run' for c in report['checks']))

    @patch('finish_agents.capture_baseline', return_value={'existingWork': [], 'omitted': []})
    def test_unavailable_specialist_does_not_fabricate_success(self, state):
        report = self.engine(FakeRunner(fail_role='security')).run(self.project, team=True)
        self.assertEqual(report['grade'], 'B')
        self.assertIn('Unavailable tool', ' '.join(report['limitations']))
        self.assertEqual(report['rounds'][1][0]['summary'], 'Review not completed.')

    @patch('finish_agents.capture_baseline', return_value={'existingWork': [], 'omitted': []})
    def test_final_synthesis_failure_returns_evidence_and_nonready_grade(self, state):
        report = self.engine(FakeRunner(fail_role='boss-report')).run(self.project)
        self.assertEqual(report['grade'], 'D')
        self.assertFalse(report['ready'])
        self.assertTrue(report['fixPrompt'])
        self.assertIn('Existing tests', report['markdown'])

    @patch('finish_agents.capture_baseline', return_value={'existingWork': [], 'omitted': []})
    def test_boss_cannot_hide_unresolved_second_review_findings(self, state):
        runner = FakeRunner()
        def remaining(**kwargs):
            result = runner(**kwargs)
            if kwargs['role'] == 'assessor':
                result['findings'] = [finding()]
            return result
        report = self.engine(remaining).run(self.project)
        self.assertEqual(report['grade'], 'C')
        self.assertEqual(report['findings'][0]['title'], 'Broken submit')
        self.assertIn('form.py:22', report['fixPrompt'])

    def test_validation_rejects_unstructured_or_invalid_result(self):
        with self.assertRaises(CodexError):
            validate({'summary': 'Looks great'}, REVIEW_SCHEMA)
        value = FakeRunner()(role='assessor', prompt='')
        value['checks'][0]['result'] = 'probably passed'
        with self.assertRaises(CodexError):
            validate(value, REVIEW_SCHEMA)

    def test_historical_failure_and_optional_discovery_do_not_poison_fresh_grade(self):
        runner = FakeRunner()
        def historical(**kwargs):
            result = runner(**kwargs)
            if kwargs['role'] == 'assessor':
                result['checks'] += [dict(check('failed'), name='Old missing Python', purpose='historical'),
                                     dict(check('failed'), name='Unused py launcher', purpose='optional')]
                result['limitations'] = ['No hosted UI; this local library does not require one.']
                result['findings'] = [dict(finding(), title='Optional extra tests', required=False)]
            return result
        report = self.engine(historical).run(self.project, verify_only=True)
        self.assertEqual(report['grade'], 'A')
        self.assertTrue(report['ready'])
        self.assertTrue(any(c['purpose'] == 'historical' and c['result'] == 'failed' for c in report['checks']))
        self.assertTrue(report['limitations'])
        self.assertFalse(report['readinessLimitations'])
        self.assertIn('(historical): failed', report['markdown'])
        self.assertEqual(report['fixPrompt'], '')

    def test_current_required_failure_still_caps_grade_even_when_boss_omits_it(self):
        runner = FakeRunner()
        def failed(**kwargs):
            result = runner(**kwargs)
            if kwargs['role'] == 'assessor':result['checks'] = [check('failed')]
            return result
        report = self.engine(failed).run(self.project, verify_only=True)
        self.assertEqual(report['grade'], 'D')
        self.assertFalse(report['ready'])

    def test_ready_report_does_not_offer_no_op_repair_chat(self):
        runner = FakeRunner()
        def no_op_prompt(**kwargs):
            result = runner(**kwargs)
            if kwargs['role'] == 'boss-report':result['fixPrompt'] = 'No repairs needed; verify again.'
            return result
        report = self.engine(no_op_prompt).run(self.project, verify_only=True)
        self.assertEqual(report['grade'], 'A')
        self.assertEqual(report['fixPrompt'], '')

    def test_material_gap_still_blocks_a_with_passing_tests(self):
        runner = FakeRunner()
        def limited(**kwargs):
            result = runner(**kwargs)
            if kwargs['role'] == 'assessor':result['readinessLimitations'] = ['Required sign-in flow unverified.']
            return result
        report = self.engine(limited).run(self.project, verify_only=True)
        self.assertEqual(report['grade'], 'B')
        self.assertIn('Required sign-in flow unverified.', report['rerunRecommendation']['conditions'])
        self.assertIn('Required sign-in flow unverified.', report['markdown'])

    def test_synthesis_cannot_relabel_required_failure_as_historical(self):
        runner = FakeRunner()
        def relabeled(**kwargs):
            result = runner(**kwargs)
            if kwargs['role'] == 'assessor':result['checks'] = [check('failed')]
            if kwargs['role'] == 'boss-report':result['checks'] = [dict(check('failed'), purpose='historical')]
            return result
        self.assertEqual(self.engine(relabeled).run(self.project, verify_only=True)['grade'], 'D')

    @patch('finish_agents.execute_cli')
    @patch('finish_agents.executable', return_value='codex.exe')
    def test_cli_uses_explicit_sandbox_no_shell_and_bounded_timeout(self, exe, command):
        def result(args, **kwargs):
            output = Path(args[args.index('--output-last-message') + 1])
            output.write_text('{"answer":"ok"}', encoding='utf-8')
            self.assertEqual(kwargs['input'], 'prompt')
            self.assertEqual(kwargs['timeout'], 123)
            self.assertNotIn('shell', kwargs)
            self.assertIn('read-only', args)
            return subprocess.CompletedProcess(args, 0)
        command.side_effect = result
        answer = run_agent(role='test', prompt='prompt', cwd=self.folder,
                           sandbox='read-only', schema={}, timeout=123)
        self.assertEqual(answer, {'answer': 'ok'})

    def test_dirty_git_baseline_saves_work_without_resetting_it(self):
        def git(*args):
            result = subprocess.run(['git', *args], cwd=self.folder, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        git('init')
        git('config', 'user.name', 'Test')
        git('config', 'user.email', 'test@example.invalid')
        file = self.folder / 'app.py'
        file.write_text('original\n', encoding='utf-8')
        git('add', 'app.py')
        git('commit', '-m', 'baseline')
        file.write_text('existing staged work\n', encoding='utf-8')
        git('add', 'app.py')
        file.write_text('existing staged work\nexisting unstaged work\n', encoding='utf-8')
        (self.folder / 'new.py').write_text('new user work\n', encoding='utf-8')
        before = git('status', '--porcelain')
        baseline = capture_baseline(self.store, self.folder, 'baseline-test')
        target = Path(baseline['path'])
        self.assertEqual(git('status', '--porcelain'), before)
        self.assertEqual(file.read_text(encoding='utf-8'), 'existing staged work\nexisting unstaged work\n')
        self.assertIn('existing staged work', (target / 'staged.patch').read_text(encoding='utf-8'))
        self.assertIn('existing unstaged work', (target / 'unstaged.patch').read_text(encoding='utf-8'))
        self.assertEqual((target / 'files/new.py').read_text(encoding='utf-8'), 'new user work\n')

    def test_non_git_baseline_copies_project_code_and_omits_credentials_and_dependencies(self):
        (self.folder / 'app.py').write_text('code\n', encoding='utf-8')
        (self.folder / '.env').write_text('SECRET=never prompt this', encoding='utf-8')
        (self.folder / 'node_modules').mkdir()
        (self.folder / 'node_modules/package.js').write_text('dependency', encoding='utf-8')
        baseline = capture_baseline(self.store, self.folder, 'plain-test')
        self.assertEqual(baseline['type'], 'files')
        self.assertEqual([item['path'] for item in baseline['files']], ['app.py'])
        self.assertIn('.env', baseline['omitted'])
        self.assertFalse((Path(baseline['path']) / 'files/.env').exists())

    @patch('finish_agents.capture_baseline', side_effect=CodexError('Snapshot size limit reached.'))
    def test_precise_baseline_failure_holds_only_repairs_and_preserves_audit(self, baseline):
        runner = FakeRunner(issue=True)
        report = self.engine(runner).run(self.project)
        self.assertNotIn('boss-fix', [c['role'] for c in runner.calls])
        self.assertIn('Snapshot size limit reached.', report['limitations'])
        self.assertEqual(len(report['rounds']), 2)

    @patch('finish_agents.os.killpg', create=True)
    @patch('finish_agents.subprocess.run')
    @patch('finish_agents.subprocess.Popen')
    def test_timeout_terminates_only_spawned_process_tree(self, popen, command, killpg):
        import os
        process = popen.return_value
        process.pid = 12345
        process.poll.return_value = None
        process.communicate.side_effect = [subprocess.TimeoutExpired(['codex'], 30), ('', '')]
        with self.assertRaises(subprocess.TimeoutExpired):
            execute_cli(['codex', 'exec'], input='prompt', timeout=30)
        if os.name == 'nt':
            self.assertEqual(command.call_args.args[0], ['taskkill', '/PID', '12345', '/T', '/F'])
        else:
            self.assertEqual(killpg.call_args.args[0], 12345)
        process.stdin.close.assert_called_once()
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
