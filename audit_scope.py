"""Discover project sources and require an explicit choice for multiple folders."""
from copy import deepcopy
from pathlib import Path
import subprocess
from codex_bridge import creation_flags
from project_ops import ProjectOps,ProjectOperationError


def discover(store,project):
    try:root=ProjectOps(store).folder(project)
    except ProjectOperationError:return []
    found={}
    def add(raw,branch=''):
        try:path=ProjectOps(store).folder(dict(project,path=str(raw)))
        except ProjectOperationError:return
        key=str(path).casefold()
        found[key]=dict(path=str(path),branch=branch,label=path.name,configured=path==root)
    add(root)
    try:
        is_git=any((parent/'.git').exists() for parent in (root,*root.parents))
        result=subprocess.run(['git','worktree','list','--porcelain'],cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=8,creationflags=creation_flags()) if is_git else None
        if result and result.returncode==0:
            for block in result.stdout.split('\n\n'):
                lines=block.splitlines();path=next((v[9:] for v in lines if v.startswith('worktree ')),None)
                branch=next((v[7:].removeprefix('refs/heads/') for v in lines if v.startswith('branch ')),'detached')
                if path:add(path,branch)
    except (OSError,subprocess.TimeoutExpired):pass
    skip={'node_modules','.git','.venv','venv','dist','build','output','data','assets','tests','docs','__pycache__'}
    try:
        for child in root.iterdir():
            if child.name.startswith('.') or child.name.lower() in skip or child.is_symlink() or not child.is_dir():continue
            if any((child/marker).exists() for marker in ('.git','package.json','pyproject.toml','Cargo.toml','go.mod')):add(child)
    except OSError:pass
    return sorted(found.values(),key=lambda row:(not row['configured'],row['path'].casefold()))


def choose(store,project,selection=None):
    options=discover(store,project);available={row['path'] for row in options}
    if selection=='all':return [row['path'] for row in options]
    if selection is None:
        if len(options)>1:raise ValueError('This project has multiple folders. Choose a folder or All folders before starting the audit.')
        return [row['path'] for row in options]
    if not isinstance(selection,list) or not selection or any(not isinstance(p,str) or p not in available for p in selection):
        raise ValueError('The audit folder choice is invalid or changed. Reopen the folder picker.')
    return list(dict.fromkeys(selection))


def run_scoped(project,folders,action,run):
    """Inspect each selected source independently; retain every individual report."""
    reports=[]
    for folder in folders or [None]:
        scoped=dict(project)
        if folder:scoped['path']=folder
        scoped['auditFolders']=folders
        report=run(scoped)
        report['auditedFolders']=[folder] if folder else []
        report['markdown']='## Reviewed source folders\n\n'+(folder or 'No source folder available; context-only review.')+'\n\n'+report.get('markdown','')
        reports.append(report)
    if len(reports)==1:return reports[0]
    if action=='advisors':
        combined=deepcopy(reports[0]);combined['folderReports']=reports;combined['auditedFolders']=folders
        # A multi-folder shelving verdict requires unanimity in every source.
        shelved=all(r.get('decision')=='shelve' for r in reports)
        decisions={r.get('decision') for r in reports}
        combined['decision']='shelve' if shelved else next(iter(decisions)) if len(decisions)==1 else 'inconclusive' if 'inconclusive' in decisions else 'split'
        combined['summary']=f'Reviewed {len(folders)} source folders independently. Read the folder-specific findings below.'
        combined['advisors']=[dict(a,name=a['name']+' — '+folder) for folder,r in zip(folders,reports) for a in r['advisors']]
        combined['votes']={k:sum(r.get('votes',{}).get(k,0) for r in reports) for k in ('continue','pivot','shelve','insufficient-evidence')}
        combined['fixPrompts']=[] if shelved else [dict(p,title=folder+' — '+p['title'],prompt='Work only in '+folder+'.\n'+p['prompt']) for folder,r in zip(folders,reports) for p in r.get('fixPrompts',[])]
        combined['shelveReasons']=[v for r in reports for v in r.get('shelveReasons',[])] if shelved else []
    else:
        combined=deepcopy(max(reports,key=lambda r:'ABCDF'.find(r.get('grade','D'))));combined['folderReports']=reports;combined['auditedFolders']=folders
        combined['summary']=f'Reviewed {len(folders)} source folders independently; the overall grade is the lowest folder grade.'
        combined['ready']=all(r.get('ready',False) for r in reports)
        combined['assessmentComplete']=all(r.get('assessmentComplete',True) for r in reports)
        combined['findings']=[dict(f,title=folder+' — '+f['title']) for folder,r in zip(folders,reports) for f in r.get('findings',[])]
        combined['checks']=[dict(c,name=folder+' — '+c['name']) for folder,r in zip(folders,reports) for c in r.get('checks',[])]
        combined['fixPrompt']='\n\n'.join('Source folder: '+folder+'\n'+r.get('fixPrompt','') for folder,r in zip(folders,reports))
    combined['limitations']=list(dict.fromkeys(v for r in reports for v in r.get('limitations',[])))
    combined['markdown']='\n\n'.join(r.get('markdown','') for r in reports)
    return combined
