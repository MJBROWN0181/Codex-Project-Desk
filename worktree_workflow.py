"""Read-only Git discovery and routing for project records. Never moves branches."""
import os
from pathlib import Path
import re
import shutil
import subprocess


def git(folder, *args, required=True):
    executable = shutil.which('git')
    if not executable:
        raise ValueError('Git is unavailable. Verify the project checkout before starting code work.')
    result = subprocess.run([executable, '-C', str(folder), *args], capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=15,
                            env={**os.environ, 'GIT_OPTIONAL_LOCKS':'0'},
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode and required:
        raise ValueError('Cannot verify the project checkout: '+result.stderr.strip()[-400:])
    return result.stdout.strip() if result.returncode==0 else None


def has_git(folder):
    folder=Path(folder).resolve()
    return any((p/'.git').exists() for p in (folder,*folder.parents))


def discover(project):
    value=project.get('path') or project.get('recordsRoot')
    if not value:raise ValueError('Configure the application source folder before starting work.')
    source = Path(value).resolve()
    if not source.is_dir(): raise ValueError('The application source folder is missing. Update the project path.')
    # Some existing workspaces point at the container above Trunk.
    if not (source/'.git').exists() and (source/'Trunk'/'.git').exists(): source=source/'Trunk'
    if not has_git(source):
        return dict(source=str(source),worktrees=[],managed=bool(project.get('trunkWorkflow')))
    top = git(source, 'rev-parse', '--show-toplevel', required=False)
    if top is None:
        if (source/'.git').exists(): raise ValueError('The Git metadata could not be verified.')
        return dict(source=str(source), worktrees=[], managed=bool(project.get('trunkWorkflow')))
    source=Path(top).resolve()
    rows=[]
    for block in git(source, '-c', 'core.quotePath=false', 'worktree', 'list', '--porcelain').split('\n\n'):
        fields=dict(line.partition(' ')[::2] for line in block.splitlines())
        if 'worktree' not in fields:continue
        folder=Path(fields['worktree']).resolve()
        rows.append(dict(path=str(folder),branch=fields.get('branch','').removeprefix('refs/heads/'),
                         head=fields.get('HEAD'),available=folder.is_dir() and 'prunable' not in fields,
                         locked='locked' in fields))
    managed=bool(project.get('trunkWorkflow')) or len(rows)>1 or any(
        (folder/name).exists() for folder in (source,source.parent)
        for name in ('docs/TRUNK-WORKFLOW.md','.config/trunk.json'))
    return dict(source=str(source),worktrees=rows,managed=managed)


def snapshot(folder):
    folder=Path(folder).resolve()
    if not has_git(folder):return dict(path=str(folder),branch=None,head=None,status=[],git=False)
    head=git(folder,'rev-parse','HEAD',required=False)
    if head is None:return dict(path=str(folder),branch=None,head=None,status=[],git=False)
    branch=git(folder,'symbolic-ref','--quiet','--short','HEAD',required=False)
    return dict(path=str(folder),branch=branch,head=head,
                status=git(folder,'status','--porcelain=v1').splitlines(),git=True)


def resolve(project, *, feature=None):
    info=discover(project)
    feature=project.get('activeFeature','') if feature is None else feature
    binding=project.get('featureWorktrees',{}).get(feature)
    rows=[r for r in info['worktrees'] if r['available']]
    if binding:
        matches=[r for r in rows if r['path']==str(Path(binding['path']).resolve()) and r['branch']==binding['branch']]
        if len(matches)!=1:raise ValueError('The feature worktree or branch changed. Rebind it before starting work.')
        target=matches[0]
    elif info['managed']:
        slug=re.sub(r'[^a-z0-9]+','-',feature.lower()).strip('-')
        matches=[r for r in rows if r['branch']=='work/'+slug] if slug else []
        if len(matches)!=1:
            raise ValueError('Choose a feature and bind its work/<feature> checkout in Project folders. Trunk is never the fallback.')
        target=matches[0]
    else:target=dict(path=info['source'],branch=None)
    state=snapshot(target['path'])
    if info['managed'] and (not state['git'] or not state['branch'] or state['branch'] in ('main','master','trunk')):
        raise ValueError('Feature work cannot run on trunk or a detached checkout. Bind a feature branch first.')
    return state


def bind(project, feature, path):
    if not feature or feature not in project.get('features',[]):raise ValueError('Choose a feature before binding a checkout.')
    info=discover(project)
    matches=[r for r in info['worktrees'] if r['available'] and r['path']==str(Path(path).resolve())]
    if len(matches)!=1 or not matches[0]['branch'] or matches[0]['branch'] in ('main','master','trunk'):
        raise ValueError('Choose an existing feature worktree from this repository, not trunk or a detached checkout.')
    project.setdefault('featureWorktrees',{})[feature]={k:matches[0][k] for k in ('path','branch')}


def verify_receipt(project, receipt):
    expected=receipt.get('sourceCheckout')
    if not expected:return
    actual=snapshot(expected['path'])
    if actual['branch']!=expected['branch'] or actual['head']!=expected['head']:
        raise ValueError('The checkout branch or commit changed before delivery. Review the task again; nothing was sent.')
    info=discover(project)
    if expected['git'] and not any(r['available'] and r['path']==actual['path'] and r['branch']==actual['branch'] for r in info['worktrees']):
        raise ValueError('The source worktree no longer belongs to this project.')


def continuation(project, expected):
    """Refresh HEAD for a new turn after authorized commits, never branch-hop."""
    actual=snapshot(expected['path'])
    if expected['git'] and actual['branch']!=expected['branch']:
        raise ValueError('This chat changed branches. Verify the checkout and start a fresh feature chat.')
    verify_receipt(project,dict(sourceCheckout=actual))
    return actual


def guard_release(project, folder):
    if discover(dict(project,path=str(folder)))['managed']:
        raise ValueError('This project uses trunk/work. Use its documented exact-commit compatibility gate and obtain release approval. The generic release button cannot promote or publish it.')


def safe_audit_fixes(project, folders):
    info=discover(project)
    if not info['managed']:return
    target=resolve(project)
    if len(folders)!=1 or str(Path(folders[0]).resolve())!=target['path']:
        raise ValueError('Audit fixes must target the selected feature worktree only. Run a feature-scoped audit first; whole-project reviews remain read-only.')


def audit_is_read_only(project, folders):
    if not discover(project)['managed']:return False
    try:safe_audit_fixes(project,folders)
    except ValueError:return True
    return False
