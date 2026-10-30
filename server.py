"""Private, loopback-only project tracker. Python standard library only."""
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
import sys
from urllib.parse import urlparse
import uuid

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('PROJECT_TRACKER_DATA', str(ROOT / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'tracker.sqlite3'
INDEX = Path.home() / 'Desktop/Projects/CMChats/workspace-index.json'
EXPORT = ROOT / 'data/codex-export.json'
STATUSES = ('Unreviewed', 'Active', 'Waiting', 'Paused', 'Complete')
KINDS = ('Software', 'Business', 'Mixed', 'Website', 'App', 'Documents Render')
MUTATION_LOCK = threading.RLock()
CODEX_SERVICE = None

def codex_service():
    global CODEX_SERVICE
    with MUTATION_LOCK:
        if CODEX_SERVICE is None:
            from desk_codex import DeskCodex
            CODEX_SERVICE = DeskCodex(sys.modules[__name__])
        return CODEX_SERVICE

def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with MUTATION_LOCK:
            return function(*args, **kwargs)
    return wrapped

def utc_stamp(value):
    stamp = datetime.fromtimestamp(value, timezone.utc) if isinstance(value, (int, float)) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat(timespec='microseconds')

def order_activity(p):
    for item in p['activity']:
        item['at'] = utc_stamp(item['at'])
    p['activity'].sort(key=lambda item:item['at'], reverse=True)

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

def initialize():
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

def load_projects():
    with connect() as db:
        return [json.loads(row['document']) for row in db.execute('SELECT document FROM projects')]

def save(p):
    order_activity(p)
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO projects VALUES (?,?)', (p['id'], json.dumps(p)))

def metadata(key, value=None):
    with connect() as db:
        if value is not None:
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(value)))
        row = db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

def new_project(name, kind='Mixed', identity=None):
    return dict(id=identity or str(uuid.uuid4()), name=name, kind=kind, status='Active', nextAction='',
                blocker='', repo='', agency='', chats=[], activity=[], suggestion=None, path='', githubCheckedAt=None)

def event(p, date, note, source, identity):
    date = utc_stamp(date)
    existing = next((a for a in p['activity'] if a['id'] == identity), None)
    if existing is None:
        p['activity'].append(dict(id=identity, at=date, note=note, source=source))
    elif date >= utc_stamp(existing['at']):
        existing.update(at=date, note=note, source=source)
    order_activity(p)
    p['activity'] = p['activity'][:60]

def gh(*args):
    executable = shutil.which('gh')
    if not executable:
        raise ValueError('GitHub CLI is unavailable. Manual updates and Codex imports still work.')
    result = subprocess.run([executable, *args], capture_output=True, text=True, encoding='utf-8', timeout=35)
    if result.returncode:
        raise ValueError('GitHub could not read this repository. Check its owner/name and your GitHub CLI sign-in.')
    return json.loads(result.stdout)

def infer_repo(path):
    if not path or not Path(path, '.git').exists():
        return ''
    try:
        output = subprocess.run(['git', '-C', path, 'remote', 'get-url', 'origin'], capture_output=True,
                                text=True, timeout=3).stdout.strip()
        match = re.search(r'github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$', output)
        return match[1] if match else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''

@serialized
def sync_codex():
    sources = []
    for path, label in ((EXPORT, 'Native Codex export'), (INDEX, 'My Workspace snapshot')):
        if path.exists():
            d = json.loads(path.read_text(encoding='utf-8-sig'))
            stamp = d.get('checkedAt') or d.get('appSnapshotAt') or d.get('generatedAt')
            sources.append((stamp or '', label, d))
    if not sources:
        raise ValueError('No Codex export or My Workspace snapshot is available.')
    sources.sort(key=lambda x:utc_stamp(x[0]) if x[0] else '')
    projects = {p['id']:p for p in load_projects()}
    ignored = {'clean', 'organize us', 'mjbro', 'v1.0'}
    imported = set()
    overrides = metadata('chatAssignments') or {}
    aliases = metadata('chatAliases') or {}
    # Older snapshot first; the most recent export wins for project metadata.
    for stamp, label, d in sources:
        for row in d.get('projects', []):
            if row.get('projectKind') != 'local' or row.get('label', '').lower() in ignored:
                continue
            identity = row['projectId']
            if identity not in projects:
                projects[identity] = new_project(row['label'], identity=identity)
                projects[identity]['status'] = 'Unreviewed'
            p = projects[identity]
            p['codexProjectId'] = identity
            p['path'] = row.get('path', '')
            if not p['repo']:
                p['repo'] = infer_repo(p['path'])
            imported.add(identity)
        chats = d.get('chats', []) + d.get('pinnedThreads', []) + d.get('threads', [])
        for chat in chats:
            alias=aliases.get(chat.get('id'))
            if alias:chat={**chat,'id':alias['id'],'projectId':alias['projectId'],'title':alias['title']}
            assigned = overrides.get(chat.get('id'), {}).get('targetProjectId', chat.get('projectId'))
            p = projects.get(assigned)
            if not p or chat.get('kind') != 'codex':
                continue
            raw = chat.get('updatedAt')
            if not raw:
                continue
            date = utc_stamp(raw)
            known = next((c for other in projects.values() for c in other['chats'] if c['id'] == chat['id']), None)
            observed = utc_stamp(stamp) if stamp else ''
            if known and (utc_stamp(known['at']) > date or
                          (utc_stamp(known['at']) == date and known.get('observedAt', '') > observed)):
                continue
            title = chat.get('title') or 'Project conversation'
            event(p, date, title, 'Codex chat activity', 'codex:' + chat['id'])
            link = dict(known or {},id=chat['id'], title=title, url='codex://threads/' + chat['id'], at=date, observedAt=observed,
                        hostId=chat.get('hostId') or chat.get('host') or 'local')
            # Remove stale placement before applying the latest source or manual assignment.
            for other in projects.values():
                if other['id'] != p['id']:
                    other['chats'] = [c for c in other['chats'] if c['id'] != link['id']]
                    other['activity'] = [a for a in other['activity'] if a['id'] != 'codex:' + link['id']]
            p['chats'] = sorted([c for c in p['chats'] if c['id'] != link['id']] + [link], key=lambda c:c['at'], reverse=True)
    for p in projects.values():
        order_activity(p)
        if not p['nextAction'] and not p['suggestion'] and not p.get('dismissedSetup') and p['status'] != 'Complete':
            if p['chats']:
                p['suggestion'] = dict(text='Review the latest conversation and choose the next unfinished step.',
                    reason='Based on the chat title: ' + p['chats'][0]['title'] + '. The conversation has not been reviewed for completion.',
                    source='Codex metadata', at=now())
            else:
                p['suggestion'] = dict(text='Define the next concrete milestone for this project.',
                    reason='No next action has been entered yet.', source='Project setup', at=now())
        save(p)
    info = dict(imported=len(imported), checkedAt=now(), sources=[dict(at=s, name=l) for s,l,_ in sources],
                note='Reads saved metadata, not live conversations. Chat activity can include planning; it does not prove completed work.')
    metadata('codex', info)
    return info

def sync_github(p):
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', p['repo']):
        raise ValueError('Enter a GitHub repository as owner/name first.')
    repo = p['repo']
    with ThreadPoolExecutor(max_workers=2) as pool:
        repo_future = pool.submit(gh, 'api', 'repos/' + repo)
        issue_future = pool.submit(gh, 'api', 'repos/' + repo + '/issues?state=open&sort=updated&per_page=20')
        details, issues = repo_future.result(), issue_future.result()
    # Repository metadata changes are not proof of work. Use the latest commit date.
    commits = gh('api', 'repos/' + repo + '/commits?per_page=1')
    return merge_github(p['id'], repo, details, issues, commits)

@serialized
def merge_github(identity, repo, details, issues, commits):
    # Read current local work AFTER network calls, so a refresh cannot overwrite it.
    p = next((p for p in load_projects() if p['id'] == identity), None)
    if not p or p['repo'] != repo:
        raise ValueError('The repository changed during refresh. Refresh the current repository again.')
    p['githubCheckedAt'] = now()
    p['githubUrl'] = details['html_url']
    if commits:
        commit = commits[0]
        event(p, commit['commit']['committer']['date'], commit['commit']['message'].splitlines()[0],
              'GitHub commit', 'github:' + commit['sha'])
    issue = next((i for i in issues if not i.get('pull_request')), None)
    if issue and p['status'] != 'Complete':
        p['suggestion'] = dict(text='Review issue #' + str(issue['number']) + ': ' + issue['title'],
            reason='Most recently updated open issue; priority has not been assessed.', source='GitHub open issue',
            url=issue['html_url'], at=now())
    save(p)
    return p

@serialized
def update(payload):
    if not isinstance(payload, dict):
        raise ValueError('Expected an object.')
    if payload.get('action') == 'complete-action':
        return complete_action(payload)
    identity = payload.get('id')
    p = next((p for p in load_projects() if p['id'] == identity), None) if identity else new_project('New project')
    if not p:
        raise ValueError('Project was not found.')
    for key in ('name','kind','status','nextAction','blocker','repo','agency'):
        if key in payload:
            if not isinstance(payload[key], str) or len(payload[key]) > 3000:
                raise ValueError('Project fields must be text of up to 3,000 characters.')
            p[key] = payload[key].strip()
    if not p['name'] or p['status'] not in STATUSES or p['kind'] not in KINDS:
        raise ValueError('Choose a project name, valid type, and status.')
    if p['kind'] == 'Documents Render' and not p.get('agency'):
        raise ValueError('Choose or enter the local agency for Documents Render.')
    if p['repo'] and not re.fullmatch(r'[\w.-]+/[\w.-]+', p['repo']):
        raise ValueError('Use owner/name for the GitHub repository.')
    action = payload.get('action')
    if action == 'accept' and p['suggestion']:
        p['nextAction'] = p['suggestion']['text']
        p['suggestion'] = None
    elif action == 'dismiss':
        p['suggestion'] = None
        p['dismissedSetup'] = True
    elif action == 'log':
        note = payload.get('note', '').strip()
        if not note or len(note) > 3000:
            raise ValueError('Describe what you worked on in up to 3,000 characters.')
        event(p, now(), note, 'Manual update', str(uuid.uuid4()))
    save(p)
    return p

@serialized
def complete_action(payload):
    request_id = payload.get('requestId')
    try:
        uuid.UUID(request_id)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Reopen the completion form and try again.')
    replacement = payload.get('nextAction', '')
    note = payload.get('note', '')
    if any(not isinstance(value, str) or len(value) > 3000 for value in (replacement, note)):
        raise ValueError('Keep the next action and completion note within 3,000 characters each.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT document FROM projects WHERE id=?', (payload.get('id'),)).fetchone()
        if not row:
            raise ValueError('Project was not found.')
        p = json.loads(row[0])
        completed = p.setdefault('completedActions', [])
        if any(item['id'] == request_id for item in completed):
            return p
        current = p.get('nextAction', '').strip()
        if not current:
            raise ValueError('This project has no next action to complete.')
        if payload.get('expectedAction') != current:
            raise ValueError('The next action changed. Refresh the project and complete its current action.')
        stamp = now()
        completed.insert(0, dict(id=request_id, action=current, at=stamp, note=note.strip()))
        event(p, stamp, 'Completed: ' + current + ('\n' + note.strip() if note.strip() else ''),
              'Completed action', 'completed:' + request_id)
        p['nextAction'] = replacement.strip()
        if p.get('suggestion') and p['suggestion'].get('text', '').strip() == current:
            p['suggestion'] = None
        # Refreshing a metadata snapshot must not fabricate a replacement action.
        p['dismissedSetup'] = True
        db.execute('UPDATE projects SET document=? WHERE id=?', (json.dumps(p), p['id']))
    return p

@serialized
def move_chat(payload):
    thread_id = payload.get('threadId')
    target_id = payload.get('targetProjectId')
    if not isinstance(thread_id, str) or not isinstance(target_id, str):
        raise ValueError('Choose a chat and a destination project.')
    with connect() as db:
        projects = [json.loads(r[0]) for r in db.execute('SELECT document FROM projects')]
        target = next((p for p in projects if p['id'] == target_id), None)
        source = next((p for p in projects if any(c['id'] == thread_id for c in p['chats'])), None)
        if not source or not target:
            raise ValueError('The chat or destination project was not found. Refresh and try again.')
        if source['id'] == target_id:
            raise ValueError('Choose a different destination project.')
        native = payload.get('native', False)
        if not isinstance(native, bool):
            raise ValueError('Invalid Codex move option.')
        if native and not target.get('codexProjectId'):
            raise ValueError('This destination exists only in the tracker. Choose a Codex project for a native move.')
        chat = next(c for c in source['chats'] if c['id'] == thread_id)
        activity = [a for p in projects for a in p['activity'] if a['id'] == 'codex:' + thread_id]
        for p in projects:
            p['chats'] = [c for c in p['chats'] if c['id'] != thread_id]
            p['activity'] = [a for a in p['activity'] if a['id'] != 'codex:' + thread_id]
        target['chats'].append(chat)
        target['chats'].sort(key=lambda c:c['at'], reverse=True)
        for a in activity:
            event(target, a['at'], a['note'], a['source'], a['id'])
        if source.get('suggestion', {}) and source['suggestion'].get('source') == 'Codex metadata':
            source['suggestion'] = None
        row = db.execute('SELECT value FROM metadata WHERE key=?', ('chatAssignments',)).fetchone()
        assignments = json.loads(row[0]) if row else {}
        assignment = dict(threadId=thread_id, title=chat['title'], sourceProjectId=source['id'],
                          targetProjectId=target_id, targetName=target['name'], requestedAt=now(),
                          codexProjectId=target.get('codexProjectId'), nativeStatus='pending' if native else 'tracker-only')
        assignments[thread_id] = assignment
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('chatAssignments', json.dumps(assignments)))
        for p in projects:
            order_activity(p)
            db.execute('INSERT OR REPLACE INTO projects VALUES (?,?)', (p['id'], json.dumps(p)))
    return assignment

class Handler(BaseHTTPRequestHandler):
    def json_response(self, data, status=200):
        encoded = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(encoded)

    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def do_GET(self):
        if not self.valid_host():
            return self.json_response({'error':'Invalid host'}, 403)
        route = urlparse(self.path).path
        if route == '/api/projects':
            return self.json_response(dict(projects=load_projects(), codex=metadata('codex'),
                                           chatAssignments=metadata('chatAssignments') or {},
                                           codexConnections=metadata('codexConnections'),codexMessages=metadata('codexMessages') or {}))
        if route.startswith('/api/codex/jobs/'):
            try:return self.json_response(codex_service().job(route.rsplit('/',1)[1]))
            except ValueError as exc:return self.json_response({'error':str(exc)},404)
        if route == '/api/codex/threads':
            try:return self.json_response(dict(chats=codex_service().native_chats()))
            except (ValueError,OSError,subprocess.TimeoutExpired) as exc:return self.json_response({'error':str(exc)},400)
        files = {'/': ('index.html','text/html'), '/app.js': ('app.js','text/javascript'), '/style.css': ('style.css','text/css'),
                 '/favicon.ico': ('../assets/project-desk.ico','image/x-icon'), '/theme.js': ('theme.js','text/javascript'),
                 '/actions.js': ('actions.js','text/javascript')}
        if route not in files:
            return self.json_response({'error':'Not found'}, 404)
        name, mime = files[route]
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write((ROOT / 'web' / name).read_bytes())

    def do_POST(self):
        origin = self.headers.get('Origin')
        allowed = {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
        if not self.valid_host() or origin not in allowed or self.headers.get('Content-Type') != 'application/json':
            return self.json_response({'error':'This request must come from the tracker.'},403)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 32000:
                raise ValueError('Request is too large or empty.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected an object.')
            if self.path == '/api/projects':
                result = update(body)
            elif self.path == '/api/codex':
                result = sync_codex()
            elif self.path == '/api/move-chat':
                result = move_chat(body)
            elif self.path == '/api/codex/check':
                service=codex_service();result=service.start_job(service.audit)
            elif self.path == '/api/codex/open':
                result=codex_service().open_chat(body)
            elif self.path == '/api/codex/recommend':
                service=codex_service();result=service.start_job(lambda:service.recommendation(body))
            elif self.path == '/api/codex/send':
                result=codex_service().send(body)
            elif self.path == '/api/github':
                p = next((p for p in load_projects() if p['id'] == body.get('id')), None)
                if not p:
                    raise ValueError('Project was not found.')
                result = sync_github(p)
            else:
                return self.json_response({'error':'Not found'},404)
            self.json_response(result)
        except (ValueError, OSError, subprocess.TimeoutExpired, sqlite3.Error) as exc:
            self.json_response({'error': str(exc)},400)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8789)
    args = parser.parse_args()
    initialize()
    if not metadata('codex') and (EXPORT.exists() or INDEX.exists()):
        sync_codex()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    service=codex_service();service.start_job(service.audit)
    threading.Thread(target=service.watch_receipts,daemon=True).start()
    print(f'Project tracker: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()
