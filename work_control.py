"""Durable, completion-driven project work and queued additions."""
import json
import threading
import time
import uuid

from codex_bridge import Client
from turn_evidence import monitor_turns
from task_progress import progress_for_turn

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
                    if p.get('auditFollowUp',{}).get('status')=='running':
                        p['auditFollowUp'].update(status='attention',detail='Verification was interrupted by a restart. The previous grade is retained; rerun the audit explicitly after checking its saved progress.')
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
                p['pauseReason'] = 'user'
                if not busy(p): p['status'] = 'Paused'
            elif action == 'resume':
                if p.get('workState', {}).get('phase') == 'attention':
                    raise ValueError('Work needs attention. Check the saved result and use Check status first.')
                p['workPaused'] = False
                p.pop('pauseReason',None)
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
            elif action in ('release', 'assess', 'finish-team', 'advisors', 'health'):
                if action != 'health' and (busy(p) or p.get('wrapRequested') or any(i['state'] in ('pending','dispatching') for i in p.get('contentQueue', []))):
                    raise ValueError('Finish current work and queued additions before starting this operation.')
                if action == 'health':
                    from project_ops import ProjectOps
                    # Network check runs outside the mutation lock below.
                else:
                    from project_ops import ProjectOps
                    audit_folders=None
                    if action in ('assess','finish-team','advisors'):
                        from audit_scope import choose
                        audit_folders=choose(self.store,p,body.get('auditFolders'))
                    if action!='advisors':ProjectOps(self.store).folder(p)
                    p['workState'] = dict(phase='operation', operation=action, id=str(uuid.uuid4()), startedAt=self.store.now(), detail='Starting '+action)
                    if audit_folders is not None:p['workState']['auditFolders']=audit_folders
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
        elif action in ('release', 'assess', 'finish-team', 'advisors'):
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
            follow_up=p.get('auditFollowUp') or {}
            verifying=follow_up.get('status')=='running' and follow_up.get('operationId')==operation_id
            if action == 'release':
                from project_ops import ProjectOps
                result = ProjectOps(self.store).release(p, progress)
            elif action=='advisors':
                from advisor_panel import AdvisorPanel
                from audit_scope import run_scoped
                result=run_scoped(p,p['workState'].get('auditFolders',[]),action,lambda scoped:AdvisorPanel(self.store).run(scoped,progress=progress,research=True))
            else:
                from finish_agents import AuditEngine
                from audit_scope import run_scoped
                folders=p['workState'].get('auditFolders')
                if folders is None and verifying:folders=(p.get('auditReport') or {}).get('auditedFolders',[])
                result=run_scoped(p,folders or [],action,lambda scoped:AuditEngine(self.store).run(scoped,team=action=='finish-team',progress=progress,**({'verify_only':True} if verifying else {})))
            with self.store.MUTATION_LOCK:
                p = self.project(identity)
                if p.get('workState',{}).get('id')!=operation_id:return
                if verifying:
                    current=p.get('auditFollowUp') or {}
                    source=p.get('auditReport') or {}
                    if current.get('operationId')!=operation_id or (source.get('id') or source.get('completedAt') or source.get('checkedAt'))!=follow_up['sourceReportKey']:
                        raise ValueError('The source audit changed during verification. The newer report was preserved.')
                    from finish_agents import markdown
                    result.update(followUpOf=follow_up['sourceReportKey'],previousGrade=follow_up.get('previousGrade'),verificationOnly=True)
                    result['markdown']=markdown(result)
                    if result.get('assessmentComplete') is False:
                        directory=self.store.DATA/'reports';directory.mkdir(parents=True,exist_ok=True)
                        (directory/(operation_id+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                        (directory/(operation_id+'.md')).write_text(result['markdown'],encoding='utf-8')
                        current['failedReportId']=result.get('id');self.store.save(p)
                        raise ValueError('Verification grading did not complete. Its evidence was saved; the previous audit grade is retained.')
                    current.update(status='completed',completedAt=self.store.now(),resultReportId=result.get('id'),newGrade=result.get('grade'),detail='One verification audit completed. Review the updated grade and remaining issues; no further fixes or audits start automatically.')
                    p.setdefault('auditHistory',[]).append(dict(reportId=follow_up['sourceReportKey'],grade=follow_up.get('previousGrade'),completedAt=source.get('completedAt'),mode=source.get('mode')))
                p['releaseState' if action == 'release' else 'advisorReport' if action=='advisors' else 'auditReport'] = result
                if action != 'release':
                    directory = self.store.DATA / 'reports'; directory.mkdir(parents=True, exist_ok=True)
                    (directory/(operation_id+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                    (directory/(operation_id+'.md')).write_text(result.get('markdown', result.get('summary','')), encoding='utf-8')
                p['workState'] = dict(phase='idle', operation=action, completedAt=self.store.now(), detail='Verification audit finished. See the updated grade and remaining issues.' if verifying else 'GitHub release published.' if action=='release' else 'Advisor panel finished. See the advisor report.' if action=='advisors' else 'Review finished. See the audit report.')
                self.store.event(p, self.store.now(), p['workState']['detail'], 'Project Desk', operation_id)
                if p.get('workPaused'): p['status']='Paused'
                self.store.save(p)
        except Exception as exc:
            with self.store.MUTATION_LOCK:
                p=self.project(identity)
                if p.get('workState',{}).get('id')!=operation_id:return
                if p.get('auditFollowUp',{}).get('operationId')==operation_id:
                    p['auditFollowUp'].update(status='attention',detail='Verification did not complete: '+str(exc))
                if hasattr(exc,'result'):p['releaseState']=exc.result
                p['workState']=dict(phase='attention', operation=action, detail=str(exc), interruptedOperation=True)
                p['workPaused']=True; self.store.save(p)

    def _start_audit_follow_up(self,p):
        follow_up=p.get('auditFollowUp') or {}
        if follow_up.get('status')!='queued' or busy(p) or p.get('workPaused'):return
        report=p.get('auditReport') or {}
        if (report.get('id') or report.get('completedAt') or report.get('checkedAt'))!=follow_up['sourceReportKey']:
            follow_up.update(status='superseded',detail='A newer audit already replaced the source report; automatic verification was skipped.')
            self.store.save(p);return
        operation=str(uuid.uuid4());action='finish-team' if follow_up['sourceMode']=='finish-team' else 'assess'
        follow_up.update(status='running',operationId=operation,startedAt=self.store.now(),detail='The same audit team is verifying the completed fixes once, without another repair pass.')
        p['workState']=dict(phase='operation',operation=action,id=operation,startedAt=self.store.now(),detail='Re-auditing completed fixes to update the grade.')
        p['suggestion']=None;p['needsRecommendation']=False
        self.store.save(p)
        threading.Thread(target=self._operation,args=(p['id'],action,operation),daemon=True).start()

    def tick(self, client=None, scan_idle=False):
        if not self.store.load_projects():return
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
                if state.get('kind')=='audit' and not state.get('threadId'):
                    receipt=(self.store.metadata('codexMessages') or {}).get(state.get('requestId')) or {}
                    if receipt.get('status') in ('failed','unknown'):
                        with self.store.MUTATION_LOCK:
                            p=self.project(original['id'])
                            if p.get('workState',{}).get('requestId')==state.get('requestId'):
                                p['workState'].update(phase='attention',detail=receipt.get('error') or 'Audit chat creation was interrupted. Check Codex before trying again.')
                                self.store.save(p)
                    continue
                target=state.get('threadId') or original.get('preferredChatId')
                if not target:continue
                linked=next((c for c in original['chats'] if c['id']==target), None)
                if linked and linked.get('hostId','local')!='local':continue
                if not busy(original) and not scan_idle and not original.get('wrapRequested') and original.get('auditFollowUp',{}).get('status')!='queued' and not any(i['state']=='pending' for i in original.get('contentQueue',[])):continue
                page=monitor_turns(client, dict(threadId=target, limit=100, itemsView='full', sortDirection='desc'))
                turns=page.get('data',[])
                saved_receipt=(self.store.metadata('codexMessages') or {}).get(state.get('requestId')) or {}
                tracked=state.get('turnId') or saved_receipt.get('turnId')
                # Follow the exact turn even after a busy chat accumulates newer
                # turns. Never infer completion from a different final answer.
                for _ in range(20):
                    if not tracked or any(t['id']==tracked for t in turns) or not page.get('nextCursor'):break
                    page=monitor_turns(client,dict(threadId=target,limit=100,itemsView='full',sortDirection='desc',cursor=page['nextCursor']))
                    turns.extend(page.get('data',[]))
                active=next((t for t in turns if t.get('status')=='inProgress'),None)
                with self.store.MUTATION_LOCK:
                    p=self.project(original['id']); current=p.get('workState',{})
                    if current.get('requestId') != state.get('requestId') or current.get('id') != state.get('id'):continue
                    receipt=(self.store.metadata('codexMessages') or {}).get(current.get('requestId'))
                    turn_id=current.get('turnId') or (receipt or {}).get('turnId')
                    turn=next((t for t in turns if t['id']==turn_id),None)
                    if current.get('outcome') in ('failed','interrupted') and not p.get('pauseReason') and current.get('detail','').startswith('Codex work '):
                        p['pauseReason']='turn-failure';current['pausedBeforeFailure']=False
                    if turn and turn.get('status')=='monitorUnknown':
                        current.pop('taskProgress',None)
                        current.update(phase='working',detail='Checking Codex status. No confirmed interruption; queued additions are held until completion is verified.')
                        p['workState']=current;self.store.save(p);continue
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
                            if current.get('outcome') in ('failed','interrupted'):
                                self._clear_failure_pause(p,current)
                                current.pop('outcome',None);current.pop('pausedBeforeFailure',None)
                            current.pop('monitorError',None)
                            current.update(phase='working',threadId=target,turnId=active['id'],detail='Codex is working on this project.')
                            progress=progress_for_turn(active)
                            if progress:current['taskProgress']=progress
                            else:current.pop('taskProgress',None)
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
                        elif p.get('auditFollowUp',{}).get('status')=='queued':self._start_audit_follow_up(p)
                        elif p.pop('needsRecommendation',False):
                            self.store.save(p)
                            threading.Thread(target=self._recommend,args=(p['id'],target),daemon=True).start()
            except Exception as exc:
                with self.store.MUTATION_LOCK:
                    p=self.project(original['id'])
                    p.setdefault('workState',{})['monitorError']='Could not check Codex completion: '+str(exc)[:400]
                    self.store.save(p)

    def _clear_failure_pause(self,p,state):
        if p.get('pauseReason')=='turn-failure' and not state.get('pausedBeforeFailure'):
            p['workPaused']=False;p.pop('pauseReason',None)
            if p.get('status')=='Paused':p['status']='Active'

    def _finish_turn(self, p, turn):
        from desk_codex import item_text
        state=p['workState']; outcome=turn['status']; stamp=self.store.now()
        follow_up=p.get('auditFollowUp') or {}
        if follow_up.get('status') in ('waiting-fixes','fixes-failed') and follow_up.get('requestId')==state.get('requestId'):
            follow_up.update(status='queued' if outcome=='completed' else 'fixes-failed',fixTurnId=turn['id'],fixCompletedAt=stamp,
                detail='Fixes finished. One verification audit will run after queued additions finish; Pause holds it.' if outcome=='completed' else 'The fix turn did not complete successfully. Automatic verification is held; the old grade is retained.')
        messages=[item_text(i) for i in turn.get('items',[]) if i.get('type')=='agentMessage' and (i.get('phase')=='final_answer' or not i.get('phase'))]
        if messages:
            p['latestReply']=dict(threadId=state['threadId'],title=next((c['title'] for c in p['chats'] if c['id']==state['threadId']),'Codex chat'),text=messages[-1][:20000],at=self.store.utc_stamp(turn.get('completedAt') or stamp),turnId=turn['id'],checkedAt=stamp)
        if outcome=='completed':
            self._clear_failure_pause(p,state)
            if state.get('kind')=='wrap':
                p['workPaused']=True;p['wrapRequested']=False;p.pop('wrapRequestId',None)
            p['workState']=dict(phase='idle',threadId=state['threadId'],completedAt=stamp,outcome=outcome,detail='Codex finished this work.' if state.get('kind')!='wrap' else 'Work wrapped up. Queued additions are paused.')
            p['nextAction']='';p.pop('nextActionReason',None);p['suggestion']=None;p['dismissedSetup']=True
            p['needsRecommendation']=state.get('kind')!='wrap'
        else:
            if state.get('outcome')!=outcome:
                state['pausedBeforeFailure']=bool(p.get('workPaused'))
            if not p.get('workPaused'):p['pauseReason']='turn-failure'
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
