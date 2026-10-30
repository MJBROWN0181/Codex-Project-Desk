"""Idempotently register a verified current Codex chat with Project Desk."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

from codex_bridge import Client, creation_flags
from project_ops import ProjectOps, ProjectOperationError, _site_url


def identity(value, label):
    try:return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):raise ValueError('A valid '+label+' is required.')

def path_key(value):
    return os.path.normcase(str(Path(value).resolve())).rstrip('\\/') if value else ''

def text(body,key,limit=3000):
    value=body.get(key,'')
    if not isinstance(value,str) or len(value)>limit:raise ValueError(key+' must be bounded text.')
    return value.strip()

def verify_chat(body):
    thread=identity(body.get('threadId') or os.environ.get('CODEX_THREAD_ID'),'current chat ID')
    with Client() as client:chat=client.read_thread(thread)
    if chat['id']!=thread:raise ValueError('Codex returned a different chat.')
    return chat

def register(store,body,chat=None):
    """Atomic shared-database merge; no chat sends, work execution or native moves."""
    if not isinstance(body,dict):raise ValueError('Expected project registration details.')
    chat=chat or verify_chat(body)
    thread=identity(chat.get('id'),'current chat ID')
    if body.get('threadId') and thread!=identity(body['threadId'],'current chat ID'):
        raise ValueError('Current chat identity did not match.')
    native=identity(body['nativeProjectId'],'native project ID') if body.get('nativeProjectId') else None
    target=identity(body['projectId'],'Project Desk project ID') if body.get('projectId') else None
    name=text(body,'name',160);kind=text(body,'kind',100)
    if kind and kind not in store.KINDS:raise ValueError('Choose a valid Project Desk type.')
    folder=text(body,'path');repo=text(body,'repo',300)
    if repo and not re.fullmatch(r'[\w.-]+/[\w.-]+',repo):raise ValueError('Repository must be owner/name.')
    website=text(body,'websiteUrl')
    if website and not _site_url(website):raise ValueError('Use a complete HTTP(S) website URL without credentials.')
    action=text(body,'nextAction');reason=text(body,'nextActionReason');agency=text(body,'agency',200)
    if folder:
        folder=str(ProjectOps(store).folder(dict(path=folder,repo=repo)))
    stamp=store.utc_stamp(chat['updatedAt']) if chat.get('updatedAt') else None
    title=' '.join(str(chat.get('name') or chat.get('title') or chat.get('preview') or 'Codex chat').split())
    title=title[:157]+'…' if len(title)>160 else title
    with store.MUTATION_LOCK,store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        projects=[json.loads(row[0]) for row in db.execute('SELECT document FROM projects')]
        def metadata(key):
            row=db.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else {}
        assignments=metadata('chatAssignments');overrides=metadata('projectPathOverrides');cards=metadata('nativeProjectCards')
        selected=next((p for p in projects if p['id']==target),None) if target else None
        if target and not selected:raise ValueError('The selected Project Desk project does not exist.')
        candidates=[];matched='new project'
        if selected:matched='selected existing card'
        else:
            assigned=assignments.get(thread,{}).get('targetProjectId')
            candidates=[p for p in projects if p['id']==assigned] if assigned else []
            if candidates:matched='saved chat assignment'
            if not candidates:
                candidates=[p for p in projects if any(c['id']==thread for c in p['chats'])]
                if candidates:matched='existing chat link'
            if not candidates and native:
                candidates=[p for p in projects if p['id']==native or p.get('codexProjectId')==native]
                if candidates:matched='native project ID'
            if not candidates and folder:
                candidates=[p for p in projects if path_key(p.get('path'))==path_key(folder)]
                if candidates:matched='project folder'
            if not candidates and repo:
                candidates=[p for p in projects if p.get('repo','').lower()==repo.lower()]
                if candidates:matched='repository'
            if len(candidates)>1:raise ValueError('Multiple cards match. Choose the existing Project Desk project ID before registering.')
            selected=candidates[0] if candidates else None
        # A mistaken explicit destination must not silently steal an existing link.
        owners=[p for p in projects if any(c['id']==thread for c in p['chats'])]
        if selected and any(p['id']!=selected['id'] for p in owners):
            raise ValueError('This chat is already linked to another card. Use Move chat to reassign it.')
        created=selected is None
        p=selected or store.new_project(name or (Path(folder).name if folder else title),kind or 'Mixed',native)
        if native and not p.get('codexProjectId'):p['codexProjectId']=native
        canonical=overrides.get(p.get('codexProjectId') or p['id'])
        if canonical:p['path']=canonical
        elif folder and (not p.get('path') or not Path(p['path']).is_dir()):p['path']=folder
        if not p.get('path') and chat.get('cwd'):
            try:p['path']=str(ProjectOps(store).folder(dict(path=chat['cwd'])))
            except ProjectOperationError:pass
        if not p.get('repo'):p['repo']=repo or store.infer_repo(p.get('path',''))
        if created and kind:p['kind']=kind
        if not p.get('agency') and agency:p['agency']=agency
        if p['kind']=='Documents Render' and not p.get('agency'):
            raise ValueError('The local agency is required for Documents Render.')
        if not p.get('websiteUrl'):
            if website:p['websiteUrl']=website
            elif p['kind']=='Website':
                resolved=ProjectOps(store).website(p)
                if resolved.get('url'):p['websiteUrl']=resolved['url'];p['websiteUrlSource']=resolved.get('urlSource')
        from work_control import busy
        if not busy(p) and not p.get('nextAction') and action:
            p['nextAction']=action;p['nextActionReason']=reason;p['suggestion']=None
        store.mark_reviewed(p)
        # Explicit SPD means show this project again, including older browser-only
        # archive choices. It does not change paused/complete/work states.
        restored=bool(p.get('archived'));p['archived']=False;p['archivedAt']=None;p['archiveUpdatedAt']=store.now()
        known=next((c for c in p['chats'] if c['id']==thread),{})
        link=dict(known,id=thread,title=title,url='codex://threads/'+thread,hostId='local',connectionStatus='verified')
        if stamp:link['at']=max(stamp,store.utc_stamp(known['at'])) if known.get('at') else stamp
        else:link['at']=known.get('at') or store.now()
        p['chats']=[c for c in p['chats'] if c['id']!=thread]+[link]
        p['chats'].sort(key=lambda c:store.utc_stamp(c['at']),reverse=True)
        if not busy(p) or not p.get('preferredChatId'):p['preferredChatId']=thread
        if stamp:store.event(p,stamp,title,'Codex chat activity','codex:'+thread)
        p['deskRegisteredAt']=store.now();store.order_activity(p)
        old=assignments.get(thread,{})
        assignments[thread]=dict(old,threadId=thread,title=title,targetProjectId=p['id'],targetName=p['name'],
            sourceProjectId=old.get('sourceProjectId') or p['id'],nativeStatus=old.get('nativeStatus') or 'tracker-only')
        if p.get('codexProjectId') and p.get('path'):overrides[p['codexProjectId']]=p['path']
        if native:
            cards[native]=p['id']
            if p.get('path'):overrides[native]=p['path']
        db.execute('INSERT OR REPLACE INTO projects VALUES (?,?)',(p['id'],json.dumps(p)))
        for key,value in [('chatAssignments',assignments),('projectPathOverrides',overrides),('nativeProjectCards',cards)]:
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,json.dumps(value)))
    return dict(projectId=p['id'],name=p['name'],path=p.get('path',''),kind=p['kind'],repo=p.get('repo',''),
                threadId=thread,chatTitle=title,created=created,restored=restored,matchedBy=matched,
                deskUrl='http://127.0.0.1:8789/',registered=True)

def run(body):
    import server
    server.initialize()
    base='http://127.0.0.1:8789'
    try:
        with urlopen(base+'/api/projects',timeout=3) as response:state=json.load(response)
    except (OSError,URLError):
        subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(server.ROOT/'Start-ProjectDesk.ps1')],
            cwd=str(server.ROOT),capture_output=True,text=True,timeout=30,creationflags=creation_flags(),check=True)
        with urlopen(base+'/api/projects',timeout=3) as response:state=json.load(response)
    if state.get('features',{}).get('projectRegister'):
        request=Request(base+'/api/project/register',data=json.dumps(body).encode(),headers={'Origin':base,'Content-Type':'application/json'})
        with urlopen(request,timeout=40) as response:result=json.load(response)
    else:
        # Compatibility with a server finishing old jobs: one atomic SQLite merge
        # makes the card immediately visible without restarting those jobs.
        chat=verify_chat(body)
        for attempt in range(3):
            result=register(server,body,chat)
            time.sleep(.25)
            current=next((p for p in server.load_projects() if p['id']==result['projectId']),None)
            if current and any(c['id']==result['threadId'] for c in current['chats']):break
        else:raise ValueError('Registration could not be retained. Refresh and retry SPD; no work was sent.')
    with urlopen(base+'/api/projects',timeout=5) as response:fresh=json.load(response)
    if not any(p['id']==result['projectId'] and any(c['id']==result['threadId'] for c in p['chats']) for p in fresh['projects']):
        raise ValueError('Project Desk did not confirm the registered project and chat.')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input-file',required=True)
    args=parser.parse_args()
    try:
        source=Path(args.input_file)
        if source.stat().st_size>32000:raise ValueError('Registration input is too large.')
        body=json.loads(source.read_text(encoding='utf-8-sig'))
        if not body.get('threadId'):body['threadId']=os.environ.get('CODEX_THREAD_ID')
        print(json.dumps(run(body),ensure_ascii=True))
    except Exception as exc:
        print(json.dumps(dict(registered=False,error=str(exc)),ensure_ascii=True));sys.exit(1)
