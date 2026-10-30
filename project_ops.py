"""Bounded website checks and explicit, resumable-in-the-report GitHub releases.

No operation runs on import. ``release`` is a user-triggered operation; callers
should serialize it with other project mutations. Commands never use a shell.
"""
from copy import deepcopy
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def _site_url(value):
    if not isinstance(value, str):return None
    value=value.strip()
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:return None
        parsed.port
    except ValueError:return None
    return value


class _SiteMetadata(HTMLParser):
    def __init__(self):
        super().__init__();self.canonical=[];self.social=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='link' and 'canonical' in attrs.get('rel','').lower().split():
            self.canonical.append(attrs.get('href'))
        if tag=='meta' and attrs.get('property','').lower()=='og:url':
            self.social.append(attrs.get('content'))


class ProjectOperationError(RuntimeError):
    """Failure with an accurate record of already completed external actions."""

    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = deepcopy(result or {})
        self.result.update(ok=False, error=str(message))


def run_command(args, *, cwd, timeout=120):
    return subprocess.run(args, cwd=str(cwd), timeout=timeout, check=False,
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', creationflags=(subprocess.CREATE_NO_WINDOW
                          if os.name == 'nt' else 0))


def _repo(value):
    value = str(value or '').strip().removesuffix('.git').rstrip('/')
    match = re.fullmatch(r'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)?([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)', value)
    if not match:
        raise ProjectOperationError('Configure a GitHub repository as owner/repository.')
    result = match.group(1)
    if any(part in ('.', '..') for part in result.split('/')):
        raise ProjectOperationError('Invalid GitHub repository.')
    return result


def _origin_repo(value):
    if not str(value).startswith(('https://github.com/', 'git@github.com:', 'ssh://git@github.com/')):
        raise ProjectOperationError('Origin must use an HTTPS or SSH GitHub URL.')
    return _repo(value)


def _version(tag):
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', str(tag))
    return tuple(map(int, match.groups())) if match else None


def _confirmed_release(value, repository, version):
    expected = f'https://github.com/{repository}/releases/tag/{version}'
    return (value.get('isDraft') is False and value.get('tagName') == version
            and str(value.get('url', '')).rstrip('/').lower() == expected.lower())


def _credential(path):
    parts = [part.lower() for part in path.replace('\\', '/').split('/')]
    name = parts[-1]
    examples = ('.env.example', '.env.sample', '.env.template')
    return (name not in examples and (name == '.env' or name.startswith('.env.'))
            or name in ('id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', 'credentials.json',
                        'service-account.json', '.npmrc', '.pypirc')
            or name.endswith(('.key', '.pem', '.p12', '.pfx', '.keystore'))
            or '.ssh' in parts or '.aws' in parts)


class _Redirects(HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
            raise URLError('Unsupported redirect URL')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ProjectOps:
    def __init__(self, store, runner=None, opener=None):
        self.store = store
        self.runner = runner or run_command
        self.opener = opener or build_opener(_Redirects())

    def _cmd(self, args, folder, *, allow_failure=False, timeout=120):
        try:
            result = self.runner(args, cwd=folder, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProjectOperationError(f'{args[0]} could not finish: {exc}') from exc
        if result.returncode and not allow_failure:
            # Bound error output; no environment or full command output is logged.
            detail = (result.stderr or result.stdout or 'Command failed').strip()[-1800:]
            raise ProjectOperationError(f'{args[0]} failed: {detail}')
        return result

    def _git(self, folder, *args, **kwargs):
        return self._cmd(['git', *args], folder, **kwargs)

    def folder(self, project):
        raw = str(project.get('path') or '').strip()
        path = Path(raw).expanduser()
        if not raw or not path.is_absolute():
            raise ProjectOperationError('Set an absolute existing project folder first.')
        path = path.resolve()
        forbidden = {Path(path.anchor).resolve(), Path.home().resolve()}
        for key in ('SystemRoot', 'WINDIR', 'ProgramFiles', 'ProgramFiles(x86)',
                    'ProgramData', 'APPDATA', 'LOCALAPPDATA', 'USERPROFILE'):
            if os.environ.get(key):
                forbidden.add(Path(os.environ[key]).resolve())
        if path in forbidden or not path.is_dir():
            raise ProjectOperationError('Choose an existing project folder, not a system or home folder.')
        for key in ('SystemRoot', 'WINDIR', 'ProgramFiles', 'ProgramFiles(x86)'):
            if os.environ.get(key) and path.is_relative_to(Path(os.environ[key]).resolve()):
                raise ProjectOperationError('System folders cannot be used as project repositories.')
        root = Path(getattr(self.store, 'ROOT', Path(__file__).parent)).resolve()
        # The original Project Desk project was recorded as ME, above this repo.
        # Only use that known child after checking its identity, never guess a repo.
        if root != path and root.is_relative_to(path) and project.get('repo'):
            origin = self._git(root, 'remote', 'get-url', 'origin', allow_failure=True)
            if not origin.returncode:
                try:
                    if _origin_repo(origin.stdout.strip()).lower() == _repo(project['repo']).lower():
                        path = root
                except ProjectOperationError:
                    pass
        return path

    def health(self, project):
        resolved=self.website(project)
        url = resolved.get('url','')
        result = {'url': url, 'checkedAt': datetime.now(timezone.utc).isoformat(),
                  'state': 'not-configured', 'statusCode': None, 'responseMs': None, **resolved}
        if not url:
            return result
        if not _site_url(url):
            return dict(result, state='unknown', detail='Enter a complete HTTP or HTTPS website URL without credentials.')
        started = time.monotonic()
        try:
            # Each request is time bounded and response bodies are never downloaded.
            for method in ('HEAD', 'GET'):
                try:
                    with self.opener.open(Request(url, method=method, headers={
                            'User-Agent': 'ProjectDesk/1.0', 'Range': 'bytes=0-0'}), timeout=5) as response:
                        code = response.status
                except HTTPError as exc:
                    code = exc.code
                    exc.close()
                if code not in (405, 501) or method == 'GET':
                    break
            result.update(state='up' if 200 <= code < 400 or code in (401, 403) else 'down', statusCode=code)
            if code in (401, 403):
                result['detail'] = 'Website is reachable; access is restricted.'
        except (OSError, URLError, ValueError) as exc:
            result.update(state='down', detail=str(exc)[:300])
        result['responseMs'] = round((time.monotonic() - started) * 1000)
        return result

    def website(self, project):
        """Read declared site metadata, never guess from arbitrary source links.

        A manually configured URL wins. Discovery is bounded to small known files,
        stays within the project, and never runs project code or reads env files.
        """
        explicit=str(project.get('websiteUrl') or '').strip()
        if explicit:return dict(url=explicit,urlSource=project.get('websiteUrlSource') or 'Project website URL')
        def choose(values,source):
            urls=list(dict.fromkeys(url for value in values if (url:=_site_url(value))))
            if len(urls)==1:return dict(url=urls[0],urlSource=source,detected=True)
            if len(urls)>1:return dict(url='',detail='Multiple website addresses were declared. Choose the Website URL in Edit project.')
        for key in ('website','siteUrl','productionUrl','homepage'):
            result=choose([project.get(key)],'Project '+key)
            if result:return result
        try:folder=self.folder(project)
        except ProjectOperationError:folder=None
        if folder:
            def read(name):
                path=(folder/name).resolve()
                if not path.is_relative_to(folder):return ''
                try:
                    if not path.is_file() or path.stat().st_size>262144:return ''
                    return path.read_text(encoding='utf-8-sig',errors='replace')
                except OSError:return ''
            cname=read('CNAME').strip()
            if re.fullmatch(r'(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,63}',cname):
                return dict(url='https://'+cname+'/',urlSource='CNAME',detected=True)
            for name in ('index.html','public/index.html','src/index.html','landing/index.html'):
                parser=_SiteMetadata()
                parser.feed(read(name))
                result=choose(parser.canonical or parser.social,name+' website metadata')
                if result:return result
            result=choose([project.get('githubHomepage')],'GitHub repository homepage')
            if result:return result
            try:package=json.loads(read('package.json') or '{}')
            except (ValueError,TypeError):package={}
            result=choose([package.get('homepage')] if isinstance(package,dict) else [],'package.json homepage')
            if result:return result
            for name in ('README.md','README.MD','README'):
                # Only explicitly labelled website links; dependency/docs URLs
                # elsewhere in the README do not identify the project's site.
                values=re.findall(r'^\s*(?:[-*]\s*)?(?:website|live site|production url|site url|homepage)\s*:\s*(?:\[[^\]]*\]\()?\s*(https?://[^\s<>\)]+)',read(name),re.I|re.M)
                result=choose(values,name+' website link')
                if result:return result
        result=choose([project.get('githubHomepage')],'GitHub repository homepage')
        return result or dict(url='',detail='No declared website address found. Set Website URL in Edit project.')

    def _check_files(self, folder):
        # Includes existing staged files, modified tracked files and unignored new
        # files. Never traverses ignored build output or stages ignored credentials.
        names = set()
        staged_names = set(self._git(folder, 'diff', '--cached', '--name-only',
                                    '--diff-filter=ACMR', '-z').stdout.split('\0')) - {''}
        for args in (('diff', '--name-only', '-z'), ('diff', '--cached', '--name-only', '-z'),
                     ('ls-files', '--others', '--exclude-standard', '-z')):
            names.update(self._git(folder, *args).stdout.split('\0'))
        suspicious = [name for name in names if name and _credential(name)
                      and (name in staged_names or (folder / name).exists())]
        if suspicious:
            raise ProjectOperationError('Release blocked: credential files would be committed: '
                                        + ', '.join(sorted(suspicious)))
        # The index can differ from disk (a key can be staged, then replaced).
        # Ask git for filenames only so private material never enters diagnostics.
        if staged_names:
            match = self._git(folder, 'grep', '--cached', '-I', '-l', '-E', '-e',
                              '-----BEGIN ([A-Z0-9 ]* )?PRIVATE KEY-----', '--',
                              *sorted(staged_names), allow_failure=True)
            if match.returncode == 0:
                raise ProjectOperationError('Release blocked: staged private key in '
                                            + ', '.join(match.stdout.splitlines()))
            if match.returncode != 1:
                raise ProjectOperationError('Cannot inspect staged files for private keys.')
        # Detect private keys under innocuous names as well as known filenames.
        for name in names:
            file = folder / name
            if not name or not file.is_file():
                continue
            if file.is_symlink():
                continue
            try:
                with file.open('rb') as handle:
                    data = handle.read(65536)
                if re.search(br'-----BEGIN (?:[A-Z0-9 ]* )?PRIVATE KEY-----', data):
                    raise ProjectOperationError(f'Release blocked: private key found in {name}.')
            except OSError as exc:
                raise ProjectOperationError(f'Cannot inspect release file {name}: {exc}') from exc

    def release(self, project, progress=None):
        """Commit, push, tag, publish. Raise ProjectOperationError with .result.

        ``progress(snapshot)`` receives JSON-safe phase/completed flags. A failed
        attempt deliberately keeps local commits/tags and any successful pushes.
        No rollback or force operation is performed. A clean, unchanged retry may
        reuse its saved incomplete version after checking local and remote tags.
        """
        state = {'ok': False, 'phase': 'checking', 'committed': False, 'pushed': False,
                 'tagCreated': False, 'tagPushed': False, 'published': False,
                 'version': None, 'commit': None, 'branch': None, 'url': None}

        def emit(phase, **values):
            state.update(phase=phase, **values)
            if progress:
                progress(deepcopy(state))

        try:
            emit('checking')
            folder = self.folder(project)
            actual_root = Path(self._git(folder, 'rev-parse', '--show-toplevel').stdout.strip()).resolve()
            if actual_root != folder:
                raise ProjectOperationError('Project folder must be the repository root to publish a release.')
            origin = self._git(folder, 'remote', 'get-url', 'origin').stdout.strip()
            repository = _origin_repo(origin)
            if project.get('repo') and repository.lower() != _repo(project['repo']).lower():
                raise ProjectOperationError('Git origin does not match this project’s configured GitHub repository.')
            push_urls = self._git(folder, 'remote', 'get-url', '--push', '--all', 'origin').stdout.splitlines()
            if not push_urls or any(_origin_repo(url.strip()).lower() != repository.lower() for url in push_urls):
                raise ProjectOperationError('Git push destination does not match this project’s GitHub repository.')
            state['repo'] = repository
            gh_repository = f'https://github.com/{repository}'
            branch = self._git(folder, 'symbolic-ref', '--quiet', '--short', 'HEAD').stdout.strip()
            if not branch or branch.startswith('-'):
                raise ProjectOperationError('Check out a named branch before publishing.')
            state['branch'] = branch
            self._git(folder, 'rev-parse', '--verify', 'HEAD')
            self._git(folder, 'diff', '--check')
            self._git(folder, 'diff', '--cached', '--check')
            self._check_files(folder)
            # Detect a diverged/behind remote before making a new local commit.
            self._git(folder, 'fetch', 'origin', '--tags', timeout=120)
            remote = self._git(folder, 'rev-parse', '--verify', f'refs/remotes/origin/{branch}', allow_failure=True)
            if not remote.returncode:
                behind = self._git(folder, 'rev-list', '--count', f'HEAD..refs/remotes/origin/{branch}').stdout.strip()
                if int(behind or '0'):
                    raise ProjectOperationError('This branch is behind or diverged from GitHub; synchronize it before releasing.')
            # Check gh access before committing or pushing anything.
            self._cmd(['gh', 'repo', 'view', gh_repository, '--json', 'nameWithOwner'], folder)
            releases = json.loads(self._cmd(['gh', 'release', 'list', '--repo', gh_repository,
                                           '--json', 'tagName', '--limit', '100'], folder).stdout)
            tags = self._git(folder, 'tag', '--list').stdout.splitlines()
            tags += [item['tagName'] for item in releases]
            versions = [value for tag in tags if (value := _version(tag)) is not None]
            if versions:
                major, minor, patch = max(versions)
                version = f'v{major}.{minor}.{patch + 1}'
            else:
                package_version = None
                package = folder / 'package.json'
                if package.is_file():
                    try:
                        package_version = _version(json.loads(package.read_text(encoding='utf-8-sig')).get('version'))
                    except (OSError, ValueError):
                        pass
                version = 'v' + '.'.join(map(str, package_version or (0, 1, 0)))
            previous = project.get('releaseState') or {}
            head = self._git(folder, 'rev-parse', 'HEAD').stdout.strip()
            clean = not self._git(folder, 'status', '--porcelain', '-z').stdout
            retry = (not previous.get('published') and previous.get('commit') == head
                     and previous.get('repo', '').lower() == repository.lower()
                     and _version(previous.get('version')) and clean)
            existing_tag = False
            if retry:
                version = previous['version']
                state.update(version=version, commit=head, resumed=True,
                             committed=bool(previous.get('committed')),
                             pushed=bool(previous.get('pushed')),
                             tagCreated=bool(previous.get('tagCreated')),
                             tagPushed=bool(previous.get('tagPushed')))
                tag = self._git(folder, 'rev-parse', '--verify', f'refs/tags/{version}^{{commit}}', allow_failure=True)
                existing_tag = not tag.returncode
                if existing_tag and (tag.stdout.strip() != head or self._git(folder, 'cat-file', '-t', f'refs/tags/{version}').stdout.strip() != 'tag'):
                    raise ProjectOperationError('Saved release tag no longer identifies this commit as an annotated tag.')
                remote_tags = self._git(folder, 'ls-remote', '--tags', 'origin',
                                        f'refs/tags/{version}', f'refs/tags/{version}^{{}}').stdout.splitlines()
                remote_values = dict(line.split(None, 1)[::-1] for line in remote_tags if line.strip())
                if remote_values and remote_values.get(f'refs/tags/{version}^{{}}') != head:
                    raise ProjectOperationError('Remote release tag differs from the saved release commit.')
                # A previous create may have succeeded before the confirmation was
                # saved. Verify that case instead of creating a duplicate release.
                existing = self._cmd(['gh', 'release', 'view', version, '--repo', gh_repository,
                                      '--json', 'url,isDraft,tagName'], folder, allow_failure=True)
                if not existing.returncode:
                    published = json.loads(existing.stdout)
                    if not _confirmed_release(published, repository, version) or not remote_values:
                        raise ProjectOperationError('Existing release is a draft or its remote tag cannot be verified.')
                    emit('complete', ok=True, published=True, pushed=True, tagCreated=existing_tag,
                         tagPushed=True, commit=head, version=version, url=published['url'])
                    return deepcopy(state)
                if 'not found' not in (existing.stderr + existing.stdout).lower():
                    raise ProjectOperationError('Cannot confirm whether the previous release was published; check GitHub before retrying.')
            emit('committing', version=version)
            self._git(folder, 'add', '--all', '--', '.')
            staged = self._git(folder, 'diff', '--cached', '--quiet', allow_failure=True)
            if staged.returncode not in (0, 1):
                raise ProjectOperationError('Could not inspect staged changes.')
            if staged.returncode == 1:
                self._git(folder, 'commit', '-m', f'Release {version}')
                state['committed'] = True
            sha = self._git(folder, 'rev-parse', 'HEAD').stdout.strip()
            emit('pushing', commit=sha)
            self._git(folder, 'push', '--set-upstream', 'origin', f'HEAD:refs/heads/{branch}', timeout=180)
            emit('tagging', pushed=True)
            if not existing_tag:
                self._git(folder, 'tag', '-a', version, '-m', f'Release {version}', sha)
            emit('pushing-tag', tagCreated=True)
            self._git(folder, 'push', 'origin', f'refs/tags/{version}', timeout=180)
            emit('publishing', tagPushed=True)
            log = self._git(folder, 'log', '-10', '--format=- %h %s').stdout.strip()
            notes = f'## {project.get("name") or repository} {version}\n\nCommit: {sha}\n\nRecent work:\n{log}\n\nPublished from Project Desk.\n'
            with tempfile.TemporaryDirectory(prefix='project-desk-release-') as temp:
                notes_path = Path(temp) / 'notes.md'
                notes_path.write_text(notes, encoding='utf-8')
                self._cmd(['gh', 'release', 'create', version, '--repo', gh_repository,
                           '--verify-tag', '--title', f'{project.get("name") or repository} {version}',
                           '--notes-file', str(notes_path)], folder, timeout=180)
            # Record creation separately: failure to verify is not proof of publish.
            emit('verifying', releaseCreated=True)
            published = json.loads(self._cmd(['gh', 'release', 'view', version, '--repo', gh_repository,
                                             '--json', 'url,isDraft,tagName'], folder).stdout)
            if not _confirmed_release(published, repository, version):
                raise ProjectOperationError('GitHub did not confirm a published release.')
            emit('complete', ok=True, published=True, url=published['url'])
            return deepcopy(state)
        except Exception as exc:
            state.update(ok=False, failedPhase=state['phase'], error=str(exc))
            emit('failed')
            raise ProjectOperationError(str(exc), state) from exc
