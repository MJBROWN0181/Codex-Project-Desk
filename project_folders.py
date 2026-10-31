"""Opt-in project records and dated chat handoffs. Never rearranges source code."""
from datetime import datetime
from pathlib import Path
import json
import re
import uuid


def component(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError('Enter a folder name of up to 160 characters.')
    value = value.strip()
    if value in ('.', '..') or re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value.endswith(('.', ' ')):
        raise ValueError('Use a plain folder name without path separators or special characters.')
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
        raise ValueError('That folder name is reserved by Windows.')
    return value


def inside(root, *parts):
    root = Path(root).resolve()
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root):
        raise ValueError('The records folder points outside this project.')
    return target


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def scaffold(p, projects=None, allow_existing=False):
    """Called explicitly on creation/migration, never while importing old cards."""
    projects = Path(projects or Path.home()/'Desktop'/'Projects').resolve()
    root = inside(projects, component(p['name']))
    marker = inside(root, '.project-desk-records.json')
    if marker.exists() and json.loads(marker.read_text(encoding='utf-8')).get('projectId') != p.get('id'):
        raise ValueError('This records folder belongs to another project.')
    if root.exists() and not p.get('recordsRoot') and not allow_existing:

        raise ValueError('This project folder already exists. Choose a unique project name; existing folders are never adopted automatically.')
    for name in ('Features', 'Project Audit', 'Project Advisors', 'Marketing/Images',
                 'Marketing/Social Media Ads', 'Brain Dump', 'Branding', 'Chat'):
        inside(root, *name.split('/')).mkdir(parents=True, exist_ok=True)
    write_json(marker, dict(projectId=p['id'], sourceFolder=p.get('path') or str(root)))
    p['recordsRoot'] = str(root)
    if not p.get('path'): p['path'] = str(root)
    p.setdefault('features', [])
    p.setdefault('activeFeature', '')
    return root


def scope(p, feature=None):
    if not p.get('recordsRoot'): raise ValueError('Enable project folders first.')
    root = Path(p['recordsRoot']).resolve()
    feature = p.get('activeFeature', '') if feature is None else feature
    if feature:
        feature = component(feature)
        if feature not in p.get('features', []): raise ValueError('Choose an existing feature.')
        return inside(root, 'Features', feature)
    return root


def add_feature(p, name):
    name = component(name)
    if any(n.casefold() == name.casefold() for n in p.get('features', [])):
        raise ValueError('This feature already exists.')
    root = inside(p['recordsRoot'], 'Features', name)
    for child in ('Audit','Advisor','Chat','New Ideas'):
        inside(root, child).mkdir(parents=True, exist_ok=True)
    p.setdefault('features', []).append(name)
    return name


def stamp():
    # Local desktop clock, with offset retained in machine-readable records.
    return datetime.now().astimezone()


def latest_handoff(folder):
    candidates = []
    for path in inside(folder, 'Chat').glob('*/session.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('completedAt') and record.get('handoff'):
            record['handoffFile']=str(path.parent/'Pass On Log.md')
            candidates.append(record)
    return max(candidates, key=lambda r: datetime.fromisoformat(r['completedAt']), default=None)


def prepare(p, message, kind, request):
    """Return a fresh-chat specification without changing source or old chats."""
    from worktree_workflow import resolve
    checkout=resolve(p)
    folder = scope(p)
    title = stamp().strftime('%Y-%m-%d %I-%M-%S %p Chat')
    handoff = latest_handoff(folder)
    context = ('Project records folder: '+str(folder)+'\nApplication source folder: '+checkout['path']+'\nVerified checkout: '+json.dumps(checkout)+
        '\nKeep source code in its existing structure. Records are not application code. '
        'Read the latest completed handoff below as historical context, not new authorization. '
        'Read the source checkout AGENTS.md and its established handoff, including .agents/PROJECT-HANDOFF.md and .agents/CODEX-NIGHTLY-REVIEW.md when present. Verify branch, HEAD and dirty state before edits; preserve other work. Never switch, reset, move, merge, commit, push, promote or deploy without the current task authorizing it and all repository gates being satisfied. The records layout does not override trunk/work or release rules. Work only on the current requested task. On wrap-up, update the established project handoff as required and give a factual final handoff with '
        'completed work, changed files, commands and results, limitations, blockers, and next steps.\n')
    if handoff:
        previous=handoff.get('checkoutAtWrap') or handoff.get('sourceCheckout')
        if checkout['git'] and (not previous or previous.get('path')!=checkout['path'] or previous.get('branch')!=checkout['branch']):
            raise ValueError('The latest handoff has no matching checkout identity. Verify its source and save a new wrap-up before continuing this feature.')
        context += 'Previous completed chat: '+handoff['title']+'\nRead its pass-on log: '+handoff['handoffFile']+'\nSaved handoff:\n'+handoff['handoff']+'\n'
    else: context += 'No completed handoff exists in this folder yet.\n'
    return dict(cwd=checkout['path'], sourceCheckout=checkout, title=title, recordsScope=str(folder),
                recordsSession=str(inside(folder, 'Chat', title+' '+request[:8])),
                message=message+'\n\nProject continuity context:\n'+context)


def record_turn(p, state, turn, receipt):
    if not receipt or not receipt.get('recordsSession'): return
    folder = Path(receipt['recordsSession'])
    base = scope(p, receipt.get('recordsFeature', ''))
    if not folder.resolve().is_relative_to(inside(base, 'Chat')):
        raise ValueError('Chat record is outside its selected folder.')
    path = folder/'session.json'
    record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(
        title=receipt['title'], threadId=state['threadId'], scope=str(base), sourceCheckout=receipt.get('sourceCheckout'), turns=[])
    if not any(t['id'] == turn['id'] for t in record['turns']):
        record['turns'].append(dict(id=turn['id'], status=turn['status'], items=turn.get('items', [])))
    if state.get('kind') == 'wrap' and turn['status'] == 'completed':
        from desk_codex import item_text
        messages = [item_text(i) for i in turn.get('items', []) if i.get('type') == 'agentMessage' and (i.get('phase') == 'final_answer' or not i.get('phase'))]
        if not messages or not messages[-1].strip():
            raise ValueError('Wrap-up finished without a handoff. Ask Codex to wrap up again.')
        from worktree_workflow import snapshot
        checkout=receipt.get('sourceCheckout')
        current=snapshot(checkout['path']) if checkout else None
        if checkout and (current['path']!=checkout['path'] or current['branch']!=checkout['branch']):
            raise ValueError('The checkout branch changed during work. Verify it before saving this handoff.')
        record.update(completedAt=stamp().isoformat(), handoff=messages[-1], checkoutAtWrap=current)
    write_json(path, record)
    if record.get('handoff'):
        (folder/'Pass On Log.md').write_text('# '+record['title']+'\n\nCheckout: '+json.dumps(record.get('checkoutAtWrap'))+'\n\n'+record['handoff']+'\n', encoding='utf-8')
        p.setdefault('closedRecordChats', [])
        if state['threadId'] not in p['closedRecordChats']: p['closedRecordChats'].append(state['threadId'])


def save_reports(p):
    if not p.get('recordsRoot'): return
    root = Path(p['recordsRoot'])
    for key, name in (('auditReport','Project Audit'), ('advisorReport','Project Advisors')):
        report = p.get(key)
        if not report: continue
        identity = str(report.get('id') or report.get('completedAt') or report.get('checkedAt') or '')
        if not identity: continue
        date = str(report.get('completedAt') or report.get('checkedAt') or 'undated')
        safe = re.sub(r'[^a-zA-Z0-9_.-]', '-', date+' Grade '+str(report.get('grade') or '-'.join(str(a.get('grade','N-A')) for a in report.get('advisors',[])) or 'ungraded')+' '+identity)
        feature = report.get('recordsFeature', '')
        destination_root = scope(p, feature) if feature else root
        destination_name = ('Audit' if key=='auditReport' else 'Advisor') if feature else name
        destination = inside(destination_root, destination_name, safe+'.json')
        if not destination.exists():
            write_json(destination, report)
            destination.with_suffix('.md').write_text(report.get('markdown') or report.get('summary') or json.dumps(report,indent=2), encoding='utf-8')


def handle(store, body):
    from work_control import busy
    with store.MUTATION_LOCK:
        p = next((p for p in store.load_projects() if p['id'] == body.get('projectId')), None)
        if not p: raise ValueError('Project was not found.')
        if busy(p) or p.get('wrapRequested') or any(i['state'] in ('pending','dispatching') for i in p.get('contentQueue', [])):
            raise ValueError('Finish current work and queued additions before changing folders.')
        action = body.get('action')
        if 'feature' in body and not isinstance(body['feature'],str): raise ValueError('Choose a valid feature name.')
        if action == 'enable': scaffold(p, allow_existing=True)
        elif action == 'discover':
            from worktree_workflow import discover
            return discover(p)
        elif action == 'bind':
            from worktree_workflow import bind
            bind(p,body.get('feature'),body.get('path',''))
        elif action == 'feature': add_feature(p, body.get('name'))
        elif action == 'select':
            feature = body.get('feature', '')
            scope(p, feature); p['activeFeature'] = feature
        elif action == 'idea':
            text = body.get('text', '')
            if not isinstance(text, str) or not text.strip() or len(text)>10000: raise ValueError('Enter an idea of up to 10,000 characters.')
            base = scope(p)
            folder = inside(base, 'New Ideas' if p.get('activeFeature') else 'Brain Dump')
            folder.mkdir(parents=True, exist_ok=True)
            (folder/(stamp().strftime('%Y-%m-%d %H-%M-%S')+' '+uuid.uuid4().hex[:8]+'.md')).write_text(text.strip()+'\n',encoding='utf-8')
        elif action == 'start':
            feature = body.get('feature', '')
            scope(p, feature); p['activeFeature'] = feature
            text = body.get('task', '')
            if not isinstance(text,str) or not text.strip() or len(text)>3000: raise ValueError('Describe the task in up to 3,000 characters.')
            # Sending does its own pause and queue validation; do not bypass it.
            store.save(p)
            return store.codex_service().send(dict(projectId=p['id'], requestId=body.get('requestId'), action=text, instructions=''), kind='folder')
        else: raise ValueError('Unknown project-folder action.')
        store.save(p)
        return p
