"""Isolated release checks: local temporary repos, fake GitHub and remote writes."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError, URLError

from project_ops import ProjectOps, ProjectOperationError, run_command


def completed(args, code=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(args, code, stdout, stderr)


class ReleaseRunner:
    def __init__(self, fail=None, draft=False):
        self.commands = []
        self.fail = fail
        self.draft = draft
        self.notes = None
        self.releases = set()
        self.remote_tags = {}

    def __call__(self, args, *, cwd, timeout):
        self.commands.append(args)
        if self.fail and args[:len(self.fail)] == self.fail:
            return completed(args, 1, stderr='Simulated remote failure')
        if args[:2] == ['git', 'ls-remote']:
            return completed(args, stdout='\n'.join(f'{sha}\t{ref}' for ref, sha in self.remote_tags.items() if ref in args))
        if args[:2] == ['git', 'push']:
            if args[-1].startswith('refs/tags/'):
                ref = args[-1]
                self.remote_tags[ref] = run_command(['git', 'rev-parse', ref], cwd=cwd).stdout.strip()
                self.remote_tags[ref + '^{}'] = run_command(['git', 'rev-parse', ref + '^{commit}'], cwd=cwd).stdout.strip()
            return completed(args)
        if args[:2] == ['git', 'fetch']:
            return completed(args)
        if args[:2] == ['gh', 'repo']:
            return completed(args, stdout='{"nameWithOwner":"example/desk"}')
        if args[:3] == ['gh', 'release', 'list']:
            return completed(args, stdout=json.dumps([{'tagName': version} for version in self.releases]))
        if args[:3] == ['gh', 'release', 'create']:
            self.notes = Path(args[args.index('--notes-file') + 1]).read_text(encoding='utf-8')
            self.releases.add(args[3])
            return completed(args, stdout='https://github.com/example/desk/releases/tag/v0.1.0')
        if args[:3] == ['gh', 'release', 'view']:
            if args[3] not in self.releases:
                return completed(args, 1, stderr='release not found')
            return completed(args, stdout=json.dumps({'url': 'https://github.com/example/desk/releases/tag/' + args[3],
                                                      'tagName': args[3], 'isDraft': self.draft}))
        return run_command(args, cwd=cwd, timeout=timeout)


class ProjectOpsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='project-ops-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'tag.gpgsign', 'false')
        self.git('remote', 'add', 'origin', 'https://github.com/example/desk.git')
        (self.repo / 'README.md').write_text('Initial\n', encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-m', 'Initial')
        self.project = {'id': 'test', 'name': 'Test Desk', 'path': str(self.repo), 'repo': 'example/desk'}
        self.runner = ReleaseRunner()
        self.ops = ProjectOps(SimpleNamespace(ROOT=self.repo), runner=self.runner)

    def git(self, *args):
        result = run_command(['git', *args], cwd=self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_publish_commits_pushes_tags_and_confirms(self):
        (self.repo / 'README.md').write_text('Changed\n', encoding='utf-8')
        snapshots = []
        result = self.ops.release(self.project, snapshots.append)
        self.assertTrue(result['published'])
        self.assertTrue(result['committed'])
        self.assertTrue(result['tagPushed'])
        self.assertEqual(result['version'], 'v0.1.0')
        self.assertEqual(snapshots[-1]['phase'], 'complete')
        self.assertEqual(snapshots[0]['published'], False)
        self.assertIn('Commit:', self.runner.notes)
        self.assertEqual(self.git('cat-file', '-t', 'v0.1.0'), 'tag')
        self.assertEqual(self.git('status', '--porcelain'), '')
        commands = self.runner.commands
        create = next(command for command in commands if command[:3] == ['gh', 'release', 'create'])
        self.assertNotIn('--draft', create)
        self.assertIn('--verify-tag', create)
        self.assertEqual(create[create.index('--repo') + 1], 'https://github.com/example/desk')
        self.assertFalse(any('--force' in command for command in commands))

    def test_failure_retains_partial_success(self):
        self.runner.fail = ['gh', 'release', 'create']
        with self.assertRaises(ProjectOperationError) as raised:
            self.ops.release(self.project)
        result = raised.exception.result
        self.assertTrue(result['pushed'])
        self.assertTrue(result['tagPushed'])
        self.assertFalse(result['published'])
        self.assertEqual(result['failedPhase'], 'publishing')
        self.assertEqual(self.git('cat-file', '-t', result['version']), 'tag')

    def test_retry_reuses_incomplete_version_without_retagging(self):
        self.runner.fail = ['gh', 'release', 'create']
        with self.assertRaises(ProjectOperationError) as raised:
            self.ops.release(self.project)
        self.project['releaseState'] = raised.exception.result
        self.runner.fail = None
        self.runner.commands.clear()
        result = self.ops.release(self.project)
        self.assertTrue(result['published'])
        self.assertTrue(result['resumed'])
        self.assertEqual(result['version'], 'v0.1.0')
        self.assertFalse(any(command[:3] == ['git', 'tag', '-a'] for command in self.runner.commands))

    def test_retry_recognizes_publication_after_lost_confirmation(self):
        self.runner.fail = ['gh', 'release', 'view']
        with self.assertRaises(ProjectOperationError) as raised:
            self.ops.release(self.project)
        self.project['releaseState'] = raised.exception.result
        self.runner.fail = None
        self.runner.commands.clear()
        self.assertTrue(self.ops.release(self.project)['published'])
        self.assertFalse(any(command[:3] == ['gh', 'release', 'create'] for command in self.runner.commands))

    def test_retry_rejects_remote_tag_changed_to_other_commit(self):
        self.runner.fail = ['gh', 'release', 'create']
        with self.assertRaises(ProjectOperationError) as raised:
            self.ops.release(self.project)
        self.project['releaseState'] = raised.exception.result
        self.runner.fail = None
        self.runner.remote_tags['refs/tags/v0.1.0^{}'] = '0' * 40
        with self.assertRaisesRegex(ProjectOperationError, 'Remote release tag differs'):
            self.ops.release(self.project)

    def test_push_url_mismatch_blocks_before_commit(self):
        self.git('config', 'remote.origin.pushurl', 'git@github.com:someone/else.git')
        with self.assertRaisesRegex(ProjectOperationError, 'push destination'):
            self.ops.release(self.project)

    def test_origin_cannot_be_local_path_disguised_as_owner_repo(self):
        self.git('remote', 'set-url', 'origin', 'example/desk')
        with self.assertRaisesRegex(ProjectOperationError, 'HTTPS or SSH'):
            self.ops.release(self.project)

    def test_draft_not_reported_published(self):
        self.runner.draft = True
        with self.assertRaises(ProjectOperationError) as raised:
            self.ops.release(self.project)
        self.assertTrue(raised.exception.result['releaseCreated'])
        self.assertFalse(raised.exception.result['published'])

    def test_origin_mismatch_blocks_before_commit(self):
        self.project['repo'] = 'someone/else'
        with self.assertRaisesRegex(ProjectOperationError, 'does not match'):
            self.ops.release(self.project)
        self.assertFalse(any(command[:2] == ['git', 'push'] for command in self.runner.commands))

    def test_credential_files_blocked_and_ignore_respected(self):
        (self.repo / '.env').write_text('TOKEN=secret\n', encoding='utf-8')
        with self.assertRaisesRegex(ProjectOperationError, 'credential'):
            self.ops.release(self.project)
        (self.repo / '.gitignore').write_text('.env\n', encoding='utf-8')
        (self.repo / '.env.example').write_text('TOKEN=\n', encoding='utf-8')
        self.assertTrue(self.ops.release(self.project)['published'])
        self.assertNotIn('.env\n', self.git('ls-files') + '\n')
        self.assertIn('.env.example', self.git('ls-files'))

    def test_private_key_content_blocked(self):
        (self.repo / 'innocent.txt').write_text('-----BEGIN RSA PRIVATE KEY-----\nsecret', encoding='utf-8')
        with self.assertRaisesRegex(ProjectOperationError, 'private key'):
            self.ops.release(self.project)

    def test_staged_key_cannot_be_hidden_by_editing_working_copy(self):
        file = self.repo / 'innocent.txt'
        file.write_text('-----BEGIN PRIVATE KEY-----\nsecret', encoding='utf-8')
        self.git('add', 'innocent.txt')
        file.write_text('Safe current content\n', encoding='utf-8')
        with self.assertRaisesRegex(ProjectOperationError, 'staged private key'):
            self.ops.release(self.project)

    def test_staged_env_cannot_be_hidden_by_deleting_working_copy(self):
        file = self.repo / '.env'
        file.write_text('TOKEN=secret\n', encoding='utf-8')
        self.git('add', '.env')
        file.unlink()
        with self.assertRaisesRegex(ProjectOperationError, 'credential'):
            self.ops.release(self.project)

    def test_semver_patch_uses_highest_tag(self):
        self.git('tag', 'v1.9.7')
        self.git('tag', 'v2.0.3')
        self.assertEqual(self.ops.release(self.project)['version'], 'v2.0.4')

    def test_first_release_package_version(self):
        (self.repo / 'package.json').write_text('{"version":"3.2.1"}', encoding='utf-8')
        self.assertEqual(self.ops.release(self.project)['version'], 'v3.2.1')

    def test_folder_resolution_and_root_guards(self):
        self.assertEqual(self.ops.folder(dict(self.project, path=str(self.root))), self.repo)
        with self.assertRaises(ProjectOperationError):
            self.ops.folder(dict(self.project, path=str(Path.home())))
        with self.assertRaises(ProjectOperationError):
            self.ops.folder(dict(self.project, path='relative'))
        with self.assertRaises(ProjectOperationError):
            self.ops.folder(dict(self.project, path=self.repo.anchor))

    def test_website_health_head_fallback_and_missing_url(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
        methods = []
        class Opener:
            def open(self, request, timeout):
                methods.append(request.method)
                if request.method == 'HEAD':
                    raise HTTPError(request.full_url, 405, 'HEAD unsupported', {}, io.BytesIO())
                return Response()
        ops = ProjectOps(SimpleNamespace(ROOT=self.repo), opener=Opener())
        result = ops.health({'websiteUrl': 'https://example.invalid/'})
        self.assertEqual(result['state'], 'up')
        self.assertEqual(methods, ['HEAD', 'GET'])
        self.assertEqual(ops.health({})['state'], 'not-configured')
        self.assertEqual(ops.health({'websiteUrl': 'file:///etc/passwd'})['state'], 'unknown')
        class Down:
            def open(self, *args, **kwargs): raise URLError('offline')
        self.assertEqual(ProjectOps(None, opener=Down()).health({'websiteUrl': 'https://example.invalid'})['state'], 'down')


if __name__ == '__main__':
    unittest.main()
