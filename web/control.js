// Project work controls. All project and agent text is rendered as text, never HTML.
function workBusy(project) {
  return ['sending','queued','working','operation','attention'].includes(project.workState?.phase);
}
function workMarkup(project) {
  const e=escapeHtml, w=project.workState || {}, busy=workBusy(project);
  const pending=(project.contentQueue || []).filter(item=>['pending','dispatching'].includes(item.state));
  const button=(action,label,disabled=false)=>`<button type="button" class="quiet" data-action="work-${action}"${disabled?' disabled':''}>${e(label)}</button>`;
  const label=({sending:'Sending to Codex',queued:'Waiting for Codex',working:'Working',operation:'Working',attention:'Needs attention',complete:'Work finished',failed:'Work needs attention'})[w.phase] || (project.workPaused?'Paused':'Ready');
  const robot=`<svg class="desk-worker" viewBox="0 0 92 64" aria-hidden="true"><path d="M25 23V13a12 12 0 0 1 24 0v10" fill="none" stroke="currentColor" stroke-width="3"/><rect x="23" y="10" width="28" height="23" rx="9" fill="currentColor" opacity=".2"/><circle cx="32" cy="21" r="2" fill="currentColor"/><circle cx="43" cy="21" r="2" fill="currentColor"/><path d="M31 37q7-5 14 0l5 15H25z" fill="currentColor" opacity=".3"/><path class="typing-hands" d="M25 39l10 9m12-9l-8 9" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"/><path d="M49 30h31l-5 22H44z" fill="currentColor" opacity=".65"/><path d="M15 54h68" stroke="currentColor" stroke-width="3"/><circle cx="62" cy="40" r="2" fill="white"/></svg>`;
  const health=project.websiteHealth;
  const release=project.releaseState;
  return `<section class="work-panel ${busy?'is-working':''}" aria-label="Project work"><div class="work-status">${busy?robot:''}<div><strong>${e(label)}${project.workPaused && busy?' · pause after this turn':''}</strong>${w.detail?`<p>${e(w.detail)}</p>`:''}${w.monitorError?`<p class="hint">${e(w.monitorError)}</p>`:''}${project.wrapRequested?'<p class="hint">Wrap-up will run after the current work.</p>':''}<small>${project.workPaused?'Queued content is held until you resume.':busy?'Add content below. It will be sent after this work finishes.':'Review a next action or start a project check.'}</small></div></div>${pending.length?`<details class="work-queue"><summary>${pending.length} queued addition${pending.length===1?'':'s'}</summary><ol>${pending.map(item=>`<li>${e(item.text)}${item.state==='dispatching'?'<small>Sending…</small>':''}</li>`).join('')}</ol></details>`:''}<div class="work-buttons">${button('add','Add content')}${button(project.workPaused?'resume':'pause',project.workPaused?'Resume queue':'Pause')}${button('wrap','Wrap up work',!!project.wrapRequested)}${button('release','Push to GitHub + release',busy || !project.repo)}${button('assess','Am I done?',busy)}${button('finish-team','Finish agent team',busy)}${project.auditReport?button('report',`Audit report${project.auditReport.grade?' · '+project.auditReport.grade:''}`):''}${['attention','failed'].includes(w.phase)?button('retry-monitor','Check work status'):''}</div>${project.kind==='Website' || project.websiteUrl?`<div class="website-health"><span class="health-dot ${e(health?.state || 'unknown')}"></span><span>Website: ${e(({up:'Up',down:'Down','not-configured':'URL needed',unknown:'Not checked'})[health?.state] || 'Not checked')}${health?.statusCode?' · HTTP '+e(health.statusCode):''}</span>${button('health','Check site')}${health?.checkedAt?`<small>${e(dateText(health.checkedAt))}</small>`:''}${health?.detail?`<small>${e(health.detail)}</small>`:''}</div>`:''}${release?`<p class="release-status">GitHub release: ${e(release.phase || release.state || 'Pending')}${release.version?' · '+e(release.version):''}${release.error?' · '+e(release.error):''}${release.url && /^https:\/\/github\.com\//.test(release.url)?` <a href="${e(release.url)}" target="_blank" rel="noopener noreferrer">View release</a>`:''}</p>`:''}</section>`;
}

let queueProject=null,queueRequestId=null;
function initWorkDialogs(){
  if(document.querySelector('#work-addition'))return;
  const node=document.createElement('div');
  node.innerHTML=`<dialog id="work-addition"><form id="work-addition-form"><div class="dialog-heading"><h2>Add content</h2><button type="button" class="quiet work-close" aria-label="Close dialog">×</button></div><p id="work-addition-project"></p><p class="hint">This addition is saved in the project queue and sent to its Codex chat when current work finishes. Pausing holds the queue.</p><label>What should Codex know?<textarea name="text" required rows="6" maxlength="6000"></textarea></label><p class="hint" id="work-addition-status" role="status"></p><div class="dialog-actions"><button type="button" class="quiet work-close">Cancel</button><button type="submit">Save to queue</button></div></form></dialog><dialog id="work-report"><div class="dialog-heading"><h2>Project audit report</h2><button type="button" class="quiet work-close" aria-label="Close report">×</button></div><div id="work-report-body"></div><label>Follow-up prompt<textarea id="work-fix-prompt" rows="6" readonly></textarea></label><button id="work-copy-prompt" type="button">Copy fix prompt</button><p class="hint" id="work-copy-status" role="status"></p></dialog>`;
  document.body.append(node);
  node.querySelectorAll('.work-close').forEach(button=>button.onclick=()=>button.closest('dialog').close());
  $('#work-addition-form').onsubmit=async event=>{
    event.preventDefault();const form=event.target,button=form.querySelector('[type=submit]');button.disabled=true;
    try{
      await request('/api/project/queue',{projectId:queueProject,requestId:queueRequestId,text:form.elements.text.value});
      form.reset();queueRequestId=crypto.randomUUID();
      $('#work-addition').close();await load();notice('Content saved to the queue.');
    }catch(error){$('#work-addition-status').textContent=error.message;}
    finally{button.disabled=false;}
  };
  $('#work-copy-prompt').onclick=async()=>{
    try{await navigator.clipboard.writeText($('#work-fix-prompt').value);$('#work-copy-status').textContent='Fix prompt copied.';}
    catch{$('#work-fix-prompt').focus();$('#work-fix-prompt').select();$('#work-copy-status').textContent='Select and copy the prompt.';}
  };
}
function reportText(value){
  if(value===null || value===undefined)return '';
  if(typeof value==='string')return value;
  if(Array.isArray(value))return value.map(reportText).filter(Boolean).join('\n\n');
  return Object.entries(value).map(([key,item])=>`${key}: ${reportText(item)}`).join('\n');
}
function openWorkReport(project){
  initWorkDialogs();const report=project.auditReport || {},e=escapeHtml;
  $('#work-report-body').innerHTML=`<p><strong>${e(project.name)}${report.grade?' · Grade '+e(report.grade):''}</strong></p><p class="hint">A — ready to use · B — almost done, usable · C — minor fixes remain · D — not ready for real use · F — not working</p>${report.checkedAt || report.completedAt?`<p class="hint">${e(dateText(report.checkedAt || report.completedAt))}</p>`:''}<pre class="audit-report-text">${e(reportText(Object.fromEntries(Object.entries(report).filter(([key])=>!['fixPrompt','prompt','grade','checkedAt','completedAt'].includes(key)))))}</pre>`;
  $('#work-fix-prompt').value=report.fixPrompt || report.prompt || 'No follow-up prompt was supplied. Review the audit findings above.';
  $('#work-copy-status').textContent='';$('#work-report').showModal();
}
async function handleWorkAction(project,action){
  if(!action.startsWith('work-'))return false;
  const operation=action.slice(5);
  initWorkDialogs();
  if(operation==='report'){openWorkReport(project);return true;}
  if(operation==='add'){
    // Keep unsent content when the same project is reopened after cancel or an error.
    if(queueProject!==project.id){$('#work-addition-form').reset();queueRequestId=crypto.randomUUID();}
    queueProject=project.id;queueRequestId ||= crypto.randomUUID();
    $('#work-addition-project').textContent=project.name;$('#work-addition-status').textContent='';
    $('#work-addition').showModal();return true;
  }
  try{
    const result=await request('/api/project/control',{projectId:project.id,action:operation});
    await load();notice(result.note || ({pause:'Current work can finish; queued content is held.',resume:'Queue resumed.',wrap:'Wrap-up requested.',release:'Commit, push, and published release started.',assess:'Readiness review started.','finish-team':'Finishing team started.',health:'Website check finished.','retry-monitor':'Work status checked.'})[operation] || 'Project updated.');
  }catch(error){notice(error.message);}
  return true;
}
