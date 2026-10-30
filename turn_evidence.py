"""Read-only evidence for turns owned by another Codex app-server process.

A standalone history reader can synthesize interrupted for an open desktop turn.
Only an explicit terminal event proves interruption; lack of one is uncertainty.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
from task_progress import PLAN_TOOLS,plan_arguments

SESSION_ROOT = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))/'sessions'
_cache = {}
_lock = threading.Lock()


def session_evidence(path, thread_id):
    path=Path(path).resolve()
    if not path.is_relative_to(SESSION_ROOT.resolve()):return {}
    with _lock:
        stat=path.stat();key=str(path)
        old=_cache.get(key)
        if not old or stat.st_size<old['offset'] or (stat.st_size==old['offset'] and stat.st_mtime_ns!=old['mtime']):
            old=dict(offset=0,mtime=0,identity=None,active=None,turns={},pendingPlans={})
        with path.open('rb') as stream:
            stream.seek(old['offset'])
            while True:
                start=stream.tell();line=stream.readline()
                if not line or not line.endswith(b'\n'):
                    stream.seek(start);break
                try:row=json.loads(line)
                except (ValueError,UnicodeDecodeError):continue
                body=row.get('payload') or {};kind=row.get('type')
                if kind=='session_meta':old['identity']=body.get('id')
                if kind=='event_msg' and body.get('type')=='task_started':
                    old['active']=body.get('turn_id')
                    if old['active']:old['turns'][old['active']]=dict(status='inProgress',at=0)
                if kind=='turn_context' and body.get('turn_id'):old['active']=body['turn_id']
                identity=body.get('turn_id') or old['active']
                evidence=old['turns'].get(identity)
                if not evidence:continue
                try:evidence['at']=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')).timestamp()
                except (KeyError,ValueError,TypeError):pass
                if kind=='event_msg' and body.get('type') in ('task_complete','turn_aborted'):
                    evidence['status']='completed' if body['type']=='task_complete' else 'interrupted'
                if kind=='response_item' and body.get('type')=='function_call' and body.get('name') in PLAN_TOOLS and body.get('namespace') in (None,'functions') and body.get('call_id'):
                    old['pendingPlans'][body['call_id']]=(identity,plan_arguments(body.get('arguments')))
                    if len(old['pendingPlans'])>100:old['pendingPlans'].pop(next(iter(old['pendingPlans'])))
                if kind=='response_item' and body.get('type')=='function_call_output':
                    pending=old['pendingPlans'].pop(body.get('call_id'),None)
                    if pending and isinstance(body.get('output'),str) and body['output'].strip()=='Plan updated':
                        turn_id,plan=pending
                        if turn_id in old['turns']:
                            if plan:old['turns'][turn_id]['plan']=plan
                            else:old['turns'][turn_id].pop('plan',None)
            old['offset']=stream.tell();old['mtime']=stat.st_mtime_ns
        if len(_cache)>128:_cache.clear()
        _cache[key]=old
        return {key:dict(value) for key,value in old['turns'].items()} if old['identity']==thread_id else {}


def monitor_turns(client, params):
    page=client.call('thread/turns/list',params)
    uncertain=[t for t in page.get('data',[]) if t.get('status')=='interrupted' and not t.get('completedAt')]
    if not uncertain and not any(t.get('status')=='inProgress' for t in page.get('data',[])):return page
    try:
        thread=client.read_thread(params['threadId'])
        evidence=session_evidence(thread['path'],params['threadId'])
    except (OSError,ValueError,KeyError,TypeError):evidence={}
    turns=[]
    for source in page.get('data',[]):
        turn=dict(source)
        observed=evidence.get(turn['id'],{})
        if observed.get('plan'):turn['taskProgress']=dict(observed['plan'],turnId=turn['id'],source='Codex plan')
        if source in uncertain:
            status=observed.get('status')
            if status=='interrupted':turn['status']='interrupted'
            elif status=='completed':turn['status']='completed'
            else:turn['status']='inProgress' if status=='inProgress' and time.time()-observed.get('at',0)<300 else 'monitorUnknown'
            turn['monitorEvidence']='session-events' if observed else 'unavailable'
        turns.append(turn)
    return dict(page,data=turns)
