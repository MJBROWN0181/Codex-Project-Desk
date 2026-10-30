"""Durable, completion-driven project work and queued additions."""
import json
import threading
import time
import uuid

from codex_bridge import Client

BUSY = {'sending', 'queued', 'working', 'operation', 'attention'}

def busy(project):
    return project.get('workState', {}).get('phase') in BUSY


class WorkControl:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.tick_lock = threading.Lock()
        # Never replay a release or file-writing audit after a process restart.
        with self.store.MUTATION_LOCK:
            for p in self.store.load_projects():
                if p.get('workState', {}).get('phase') == 'operation':
                    p['workState'].update(phase='attention', detail='Project Desk restarted during this operation. Review its saved progress before starting another operation.', interruptedOperation=True)
                    self.store.save(p)

    def project(self, identity):
        return self.service.project(identity)

    def queue(self, body):
        from desk_codex import text_field, thread_id
        text = text_field(body, 'text', 6000, True)
        identity = thread_id(body.get('requestId'))
        with self.store.MUTATION_LOCK:
            p = self.project(body.get('projectId'))
            if not (p.get('workState', {}).get('threadId') or p.get('preferredChatId')):
                raise ValueError('Send a reviewed next action to a local Codex chat first.')
            items = p.setdefault('contentQueue', [])
            old = next((i for i in items if i['id'] == identity), None)
            if old:
                if old['text'] != text: raise ValueError('This queue request already contains different content.')
                return p
            if sum(i['state'] in ('pending', 'dispatching') for i in items) >= 100:
                raise ValueError('This project already has 100 queued additions.')
            items.append(dict(id=identity, text=text, state='pending', at=self.store.now()))
            self.store.mark_reviewed(p)
            self.store.save(p)
        return p

    def control(self, body):
        action = body.get('action')
        identity = body.get('projectId')
        with self.store.MUTATION_LOCK:
            p = self.project(identity)
            if action == 'pause':
                p['workPaused'] = True
                if not busy(p): p['status'] = 'Paused'
            elif action == 'resume':
                if p.get('workState', {}).get('phase') == 'attention':
                    raise ValueError('Work needs attention. Check the saved result and use Check status first.')
                p['workPaused'] = False
                if p['status'] == 'Paused': p['status'] = 'Active'
            elif action == 'wrap':
                if not (p.get('workState', {}).get('threadId') or p.get('preferredChatId')):
                    raise ValueError('Choose a local chat by sending a reviewed next action first.')
                p['wrapRequested'] = True
            elif action == 'retry-monitor':
                receipt=(self.store.metadata('codexMessages') or {}).get(p.get('workState',{}).get('requestId'))
                if p.get('workState', {}).get('interruptedOperation'):
                    # This explicitly acknowledges interrupted work; no automatic replay.
                    p['workState'] = dict(phase='idle', detail='Interrupted operation acknowledged. Saved reports and release progress remain available.')
                    p['workPaused'] = True
                elif receipt and receipt['status']=='failed':
                    for item in p.get('contentQueue',[]):
                        if item['id']==receipt['id']:item['state']='failed'
                    p['workState']=dict(phase='idle',threadId=receipt['threadId'],detail='Failed delivery acknowledged. Review the message before sending it again; queued content is paused.')
                    p['workPaused']=True
                elif p.get('workState', {}).get('phase') == 'attention' and p['workState'].get('outcome') in ('failed', 'interrupted'):
                    p['workState']['phase'] = 'idle'
                    p['workPaused'] = True
            elif action in ('release', 'assess', 'finish-team', 'health'):
                if action != 'health' and (busy(p) or p.get('wrapRequested') or any(i['state'] in ('pending','dispatching') for i in p.get('contentQueue', []))):
                    raise ValueError('Finish current work and queued additions before starting this operation.')
                if action == 'health':
                    from project_ops import ProjectOps
                    # Network check runs outside the mutation lock below.
                else:
                    from project_ops import ProjectOps
                    ProjectOps(self.store).folder(p)
                    p['workState'] = dict(phase='operation', operation=action, id=str(uuid.uuid4()), startedAt=self.store.now(), detail='Starting '+action)
                    p['suggestion'] = None
                    self.store.mark_reviewed(p)
            else: raise ValueError('Unknown project control.')
            self.store.save(p)
        if action == 'health':
            from project_ops import ProjectOps
            result = ProjectOps(self.store).health(p)
            with self.store.MUTATION_LOCK:
                p = self.project(identity)
                self._save_health(p,result)
        elif action in ('release', 'assess', 'finish-team'):
            threading.Thread(target=self._operation, args=(identity, action, p['workState']['id']), daemon=True).start()
        return p

    def _operation(self, identity, action, operation_id):
        def progress(result):
            with self.store.MUTATION_LOCK:
                p = self.project(identity)
                if p.get('workState', {}).get('id') != operation_id: return
                p['workState']['detail'] = result if isinstance(result, str) else result.get('detail') or result.get('phase') or json.dumps(result)[:500]
                if action == 'release' and isinstance(result, dict): p['releaseState'] = result
                self.store.save(p)
        try:
            p = self.project(identity)
            if action == 'release':
                from project_ops import ProjectOps
                result = ProjectOps(self.store).release(p, progress)
            else:
                from finish_agents import AuditEngine
                result = AuditEngine(self.store).run(p, team=action=='finish-team', progress=progress)
            with self.store.MUTATION_LOCK:
                p = self.project(identity)
                p['releaseState' if action == 'release' else 'auditReport'] = result
                if action != 'release':
                    directory = self.store.DATA / 'reports'; directory.mkdir(parents=True, exist_ok=True)
                    (directory/(operation_id+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                    (directory/(operation_id+'.md')).write_text(result.get('markdown', result.get('summary','')), encoding='utf-8')
                p['workState'] = dict(phase='idle', operation=action, completedAt=self.store.now(), detail='GitHub release published.' if action=='release' else 'Review finished. See the audit report.')
                self.store.event(p, self.store.now(), p['workState']['detail'], 'Project Desk', operation_id)
                if p.get('workPaused'): p['status']='Paused'
                self.store.save(p)
        except Exception as exc:
            with self.store.MUTATION_LOCK:
                p=self.project(identity)
                if hasattr(exc,'result'):p['releaseState']=exc.result
                p['workState']=dict(phase='attention', operation=action, detail=str(exc), interruptedOperation=True)
                p['workPaused']=True; self.store.save(p)

    def tick(self, client=None, scan_idle=False):
        if not self.tick_lock.acquire(blocking=False): return
        try:
            if client is None:
                with Client() as native: return self._tick(native, scan_idle)
            return self._tick(client, scan_idle)
        finally: self.tick_lock.release()

    def _tick(self, client, scan_idle):
        for original in self.store.load_projects():
            try:
                state=original.get('workState', {})
                if state.get('phase')=='operation' or state.get('interruptedOperation'): continue
                target=state.get('threadId') or original.get('preferredChatId')
                if not target:continue
                linked=next((c for c in original['chats'] if c['id']==target), None)
                if linked and linked.get('hostId','local')!='local':continue
                if not busy(original) and not scan_idle and not original.get('wrapRequested') and not any(i['state']=='pending' for i in original.get('contentQueue',[])):continue
                page=client.call('thread/turns/list', dict(threadId=target, limit=100, itemsView='full', sortDirection='desc'))
                turns=page.get('data',[])
                saved_receipt=(self.store.metadata('codexMessages') or {}).get(state.get('requestId')) or {}
                tracked=state.get('turnId') or saved_receipt.get('turnId')
                # Follow the exact turn even after a busy chat accumulates newer
                # turns. Never infer completion from a different final answer.
                for _ in range(20):
                    if not tracked or any(t['id']==tracked for t in turns) or not page.get('nextCursor'):break
                    page=client.call('thread/turns/list',dict(threadId=target,limit=100,itemsView='full',sortDirection='desc',cursor=page['nextCursor']))
                    turns.extend(page.get('data',[]))
                active=next((t for t in turns if t.get('status')=='inProgress'),None)
                with self.store.MUTATION_LOCK:
                    p=self.project(original['id']); current=p.get('workState',{})
                    if current.get('requestId') != state.get('requestId') or current.get('id') != state.get('id'):continue
                    receipt=(self.store.metadata('codexMessages') or {}).get(current.get('requestId'))
                    turn_id=current.get('turnId') or (receipt or {}).get('turnId')
                    turn=next((t for t in turns if t['id']==turn_id),None)
                    if turn_id and not turn:
                        current.update(phase='attention',detail='The exact work turn could not be found in Codex history. Queued additions are held; open the chat to check its status.')
                        p['workState']=current;self.store.save(p);continue
                    if receipt and receipt['status'] in ('failed','unknown') and not turn:
                        current.update(phase='attention',detail=receipt.get('error') or receipt.get('note') or 'Delivery needs checking. This message will not be resent automatically.')
                        p['workState']=current;self.store.save(p);continue
                    if turn and turn.get('status') in ('completed','failed','interrupted') and current.get('phase') in BUSY:
                        self._finish_turn(p, turn)
                        p=self.project(p['id']);current=p.get('workState',{})
                    elif active:
                        if current.get('phase') not in ('sending','queued') or (turn and turn['id']==active['id']):
                            current.update(phase='working',threadId=target,turnId=active['id'],detail='Codex is working on this project.')
                            self.store.mark_reviewed(p)
                            p['workState']=current;p['suggestion']=None;self.store.save(p)
                        continue
                    elif receipt and not turn:
                        current.update(phase='queued' if receipt['status']=='queued' else 'sending',detail='Waiting for Codex to start the sent message.')
                        p['workState']=current;self.store.save(p);continue
                    if active or busy(p):continue
                    if p.get('workState',{}).get('monitorError'):
                        p['workState'].pop('monitorError',None);self.store.save(p)
                    if p.get('wrapRequested'):
                        self._dispatch(p, target, wrap=True)
                    elif not p.get('workPaused'):
                        item=next((i for i in p.get('contentQueue',[]) if i['state']=='pending'),None)
                        if item:self._dispatch(p,target,item=item)
                        elif p.pop('needsRecommendation',False):
                            self.store.save(p)
                            threading.Thread(target=self._recommend,args=(p['id'],target),daemon=True).start()
            except Exception as exc:
                with self.store.MUTATION_LOCK:
                    p=self.project(original['id'])
                    p.setdefault('workState',{})['monitorError']='Could not check Codex completion: '+str(exc)[:400]
                    self.store.save(p)

    def _finish_turn(self, p, turn):
        from desk_codex import item_text
        state=p['workState']; outcome=turn['status']; stamp=self.store.now()
        messages=[item_text(i) for i in turn.get('items',[]) if i.get('type')=='agentMessage' and (i.get('phase')=='final_answer' or not i.get('phase'))]
        if messages:
            p['latestReply']=dict(threadId=state['threadId'],title=next((c['title'] for c in p['chats'] if c['id']==state['threadId']),'Codex chat'),text=messages[-1][:20000],at=self.store.utc_stamp(turn.get('completedAt') or stamp),turnId=turn['id'],checkedAt=stamp)
        if outcome=='completed':
            if state.get('kind')=='wrap':
                p['workPaused']=True;p['wrapRequested']=False;p.pop('wrapRequestId',None)
            p['workState']=dict(phase='idle',threadId=state['threadId'],completedAt=stamp,outcome=outcome,detail='Codex finished this work.' if state.get('kind')!='wrap' else 'Work wrapped up. Queued additions are paused.')
            p['nextAction']='';p.pop('nextActionReason',None);p['suggestion']=None;p['dismissedSetup']=True
            p['needsRecommendation']=state.get('kind')!='wrap'
        else:
            state.update(phase='attention',outcome=outcome,detail='Codex work '+outcome+'. Queued additions are held. Check the chat before resuming.')
            p['workPaused']=True
        if p.get('workPaused'):p['status']='Paused'
        self.store.event(p,stamp,'Codex work '+outcome,'Codex completion','turn:'+turn['id'])
        self.store.save(p)

    def _dispatch(self,p,target,item=None,wrap=False):
        if wrap:
            identity=p.setdefault('wrapRequestId',str(uuid.uuid4()))
            action='Wrap up this work'
            instructions='Use the wrap-up-work skill. Save a factual handoff with completed work, checks, limitations, and next steps in this project. Do not commit, push, publish, deploy, archive, or start new feature work. Finish this turn after saving the handoff.'
        else:
            identity=item['id'];action='Continue with this queued addition';instructions=item['text']
        self.service.send(dict(projectId=p['id'],threadId=target,requestId=identity,action=action,instructions=instructions),internal=True,kind='wrap' if wrap else 'addition')

    def _recommend(self,identity,target):
        try:
            answer=self.service.recommendation(dict(projectId=identity,threadId=target))
            with self.store.MUTATION_LOCK:
                p=self.project(identity)
                if busy(p) or p.get('workPaused') or p.get('nextAction') or any(i['state']=='pending' for i in p.get('contentQueue',[])):return
                p['suggestion']=dict(text=answer['action'],reason=answer['reason'],source='Codex agent',at=self.store.now());self.store.save(p)
        except Exception as exc:
            with self.store.MUTATION_LOCK:
                p=self.project(identity);p['recommendationError']=str(exc)[:500];self.store.save(p)

    def watch(self):
        cycles=0
        while True:
            time.sleep(5);cycles+=1
            try:self.tick(scan_idle=cycles%6==1)
            except Exception:pass
            if cycles%12==1 and not getattr(self,'health_running',False):
                self.health_running=True
                threading.Thread(target=self._health_cycle,daemon=True).start()

    def _health_cycle(self):
        from project_ops import ProjectOps
        try:
            for p in self.store.load_projects():
                if p.get('kind')=='Website' or p.get('websiteUrl'):
                    try:
                        result=ProjectOps(self.store).health(p)
                        with self.store.MUTATION_LOCK:
                            latest=self.project(p['id']);self._save_health(latest,result)
                    except Exception:pass
        finally:self.health_running=False

    def _save_health(self,p,result):
        if result.get('detected') and result.get('url') and not p.get('websiteUrl'):
            p['websiteUrl']=result['url'];p['websiteUrlSource']=result.get('urlSource')
        # Do not let a slow check overwrite a different URL saved in another window.
        if p.get('websiteUrl') and result.get('url')!=p['websiteUrl']:return
        p['websiteHealth']=result;self.store.save(p)
