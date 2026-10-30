"""Explicit Codex plan evidence only; never estimate from prose, time or tool counts."""
import json

PLAN_TOOLS={'update_plan','functions.update_plan'}

def normalize_plan(value):
    if not isinstance(value,list) or not 1<=len(value)<=100:return None
    steps=[]
    for item in value:
        if not isinstance(item,dict):return None
        step=item.get('step');raw=item.get('status')
        if not isinstance(raw,str):return None
        status={'inProgress':'in_progress'}.get(raw,raw)
        if not isinstance(step,str) or not step.strip() or len(step)>2000 or status not in ('pending','in_progress','completed'):return None
        steps.append(dict(step=step.strip(),status=status))
    if sum(s['status']=='in_progress' for s in steps)>1:return None
    return dict(steps=steps,total=len(steps),completed=sum(s['status']=='completed' for s in steps),
                currentStep=next((s['step'] for s in steps if s['status']=='in_progress'),None))

def plan_arguments(value):
    if isinstance(value,str):
        try:value=json.loads(value)
        except (ValueError,TypeError):return None
    return normalize_plan(value.get('plan')) if isinstance(value,dict) else None

def progress_for_turn(turn):
    if not turn or not turn.get('id'):return None
    saved=turn.get('taskProgress')
    plan=normalize_plan(saved.get('steps')) if isinstance(saved,dict) and saved.get('turnId')==turn['id'] else None
    for item in turn.get('items',[]):
        if item.get('type')=='dynamicToolCall' and item.get('tool') in PLAN_TOOLS and item.get('namespace') in (None,'functions') and item.get('status')=='completed' and item.get('success') is True:
            plan=plan_arguments(item.get('arguments'))
    return dict(plan,turnId=turn['id'],source='Codex plan') if plan else None
