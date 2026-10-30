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
  return `<section class="work-panel ${busy?'is-working':''}" aria-label="Project work"><div class="work-status">${busy?robot:''}<div><strong>${e(label)}${project.workPaused && busy?' · pause after this turn':''}</strong>${w.detail?`<p>${e(w.detail)}</p>`:''}${w.monitorError?`<p class="hint">${e(w.monitorError)}</p>`:''}${project.wrapRequested?'<p class="hint">Wrap-up will run after the current work.</p>':''}<small>${project.workPaused?'Queued content is held until you resume.':busy?'Add content below. It will be sent after this work finishes.':'Review a next action or start a project check.'}</small></div></div>${pending.length?`<details class="work-queue"><summary>${pending.length} queued addition${pending.length===1?'':'s'}</summary><ol>${pending.map(item=>`<li>${e(item.text)}${item.state==='dispatching'?'<small>Sending…</small>':''}</li>`).join('')}</ol></details>`:''}<div class="work-buttons">${button('add','Add content')}${button(project.workPaused?'resume':'pause',project.workPaused?'Resume queue':'Pause')}${button('wrap','Wrap up work',!!project.wrapRequested)}${button('release','Push to GitHub + release',busy || !project.repo)}${button('assess','Am I done?',busy)}${button('finish-team','Finish agent team',busy)}${button('advisors','Panel of advisors',busy)}${project.advisorReport?button('advisor-report','Advisor report'):''}${project.auditReport?button('report',`Audit report${project.auditReport.grade?' · '+project.auditReport.grade:''}`):''}${['attention','failed'].includes(w.phase)?button('retry-monitor','Check work status'):''}</div>${project.kind==='Website' || project.websiteUrl?`<div class="website-health"><span class="health-dot ${e(health?.state || 'unknown')}"></span><span>Website: ${e(({up:'Up',down:'Down','not-configured':'URL needed',unknown:'Not checked'})[health?.state] || 'Not checked')}${health?.statusCode?' · HTTP '+e(health.statusCode):''}</span>${button('health','Check site')}${/^https?:\/\//i.test(health?.url || project.websiteUrl || '')?`<a class="checked-site-url" href="${e(health?.url || project.websiteUrl)}" target="_blank" rel="noopener noreferrer" title="${e(health?.urlSource || project.websiteUrlSource || 'Configured website')}">${e(health?.url || project.websiteUrl)}</a>`:''}${health?.checkedAt?`<small>${e(dateText(health.checkedAt))}</small>`:''}${health?.detail?`<small>${e(health.detail)}</small>`:''}</div>`:''}${release?`<p class="release-status">GitHub release: ${e(release.phase || release.state || 'Pending')}${release.version?' · '+e(release.version):''}${release.error?' · '+e(release.error):''}${release.url && /^https:\/\/github\.com\//.test(release.url)?` <a href="${e(release.url)}" target="_blank" rel="noopener noreferrer">View release</a>`:''}</p>`:''}</section>`;
}

let queueProject=null,queueRequestId=null;
function initWorkDialogs(){
  if(document.querySelector('#work-addition'))return;
  const node=document.createElement('div');
  node.innerHTML=`<dialog id="work-addition"><form id="work-addition-form"><div class="dialog-heading"><h2>Add content</h2><button type="button" class="quiet work-close" aria-label="Close dialog">×</button></div><p id="work-addition-project"></p><p class="hint">This addition is saved in the project queue and sent to its Codex chat when current work finishes. Pausing holds the queue.</p><label>What should Codex know?<textarea name="text" required rows="6" maxlength="6000"></textarea></label><p class="hint" id="work-addition-status" role="status"></p><div class="dialog-actions"><button type="button" class="quiet work-close">Cancel</button><button type="submit">Save to queue</button></div></form></dialog><dialog id="work-report"><div class="dialog-heading"><h2>Project audit report</h2><button type="button" class="quiet work-close" aria-label="Close report">×</button></div><div id="work-report-body"></div><label>Follow-up prompt<textarea id="work-fix-prompt" rows="6" readonly></textarea></label><div class="report-prompt-actions"><button id="work-copy-prompt" type="button">Copy fix prompt</button><button id="work-send-prompt" type="button" title="Review and edit the prompt, then choose Send to Codex">Send to Codex</button></div><p class="hint" id="work-copy-status" role="status"></p></dialog>`;
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
function reportFixSeed(project,report,prompt,source='audit',selection='all recommended fixes'){
  if(!String(prompt || '').trim())return null;
  const reportId=report.id || report.completedAt || report.checkedAt || 'saved-report';
  const where=projectDeskRoot?`${projectDeskRoot.replace(/\\/g,'/')}/data/reports`:'the Project Desk data/reports folder';
  const context=`Full ${source} report: locate the saved JSON in ${where} with projectId ${project.id} and report id/date ${reportId}. Read the complete findings, checks, and verification limits before making changes. Selected scope: ${compactText(selection,200)}. If the source report cannot be found, state that gap rather than claiming full coverage.`;
  const workflow='Repair workflow: discover and read the installed skills relevant to these findings, and use the available tools that help verify and fix them. Cover security, correctness, UI/accessibility, performance, documentation, and regression checks where applicable; do not run unrelated tools just to claim coverage. Validate the findings, fix the highest-risk issues first, and preserve unrelated work. Use independent agents when useful and available, coordinating edits to avoid conflicts. Rerun relevant checks and review the result again. Report what was fixed, which tools/skills and checks were used, and anything still unverified or requiring my input. Do not claim a pass for a check that was not run. Do not publish, push, deploy, change accounts/billing, or contact others unless separately requested.';
  const body=prompt.length<=3800?prompt:`The complete recommended prompt is in the saved report referenced below. Read and follow it in full for the selected scope; it has not been truncated into this message.`;
  return {key:`${source}:${project.id}:${reportId}:${selection}`,action:source==='advisor'?'Address the advisor report’s recommended fixes':'Fix the issues found in the project audit',
    reason:compactText(`${report.grade?'Audit grade '+report.grade+'. ':''}${report.summary || 'Resolve the supported findings and verify the result.'}`,700),
    instructions:`${body}\n\n${context}\n\n${workflow}`};
}
function reviewReportFix(project,seed,dialog){
  if(!seed)return notice('This report has no recommended fix prompt to send.');
  if(workBusy(project))return notice('This project is working. Wait for completion or add context to its queue.');
  dialog.close();openActionReview(project,seed);
}
function auditHighlights(report){
  const e=escapeHtml;
  const rank={blocker:0,critical:0,high:1,medium:2,low:3,info:4};
  const findings=(Array.isArray(report.findings)?report.findings:[]).map(f=>typeof f==='string'?{title:f,severity:'info'}:f).sort((a,b)=>(rank[a.severity]??4)-(rank[b.severity]??4));
  const urgent=findings.filter(f=>['blocker','critical','high'].includes(f.severity));
  const priorities=urgent.length?urgent:findings.filter(f=>f.severity==='medium');
  const checks=Array.isArray(report.checks)?report.checks:[],failed=checks.filter(c=>c.result==='failed'),unrun=checks.filter(c=>c.result==='not-run');
  const limits=[...new Set([...(report.limitations || []),...unrun.map(c=>`${c.name}: ${c.evidence || 'Not run'}`)])];
  const item=f=>`<li><strong>${e(f.title)}</strong>${f.evidence?`<p>${e(f.evidence)}</p>`:''}${f.recommendation?`<p>Recommended fix: ${e(f.recommendation)}</p>`:''}</li>`;
  return `${priorities.length?`<section class="audit-highlight ${urgent.length?'urgent':'caution'}"><h3>${urgent.length?'High-priority findings':'Key fixes'} (${priorities.length})</h3><ul>${priorities.slice(0,4).map(f=>`<li><strong>${e(f.title)}</strong>${f.recommendation?`<p>${e(compactText(f.recommendation,220))}</p>`:''}</li>`).join('')}</ul>${priorities.length>4?'<p class="hint">The remaining findings are in All findings below.</p>':''}</section>`:''}${failed.length?`<section class="audit-highlight urgent"><h3>Failed checks (${failed.length})</h3><ul>${failed.slice(0,3).map(c=>`<li><strong>${e(c.name)}</strong><p>${e(compactText(c.evidence,220))}</p></li>`).join('')}</ul></section>`:''}${limits.length?`<section class="audit-highlight caution"><h3>Not verified / needs attention (${limits.length})</h3><ul>${limits.slice(0,3).map(limit=>`<li>${e(compactText(limit,280))}</li>`).join('')}</ul>${limits.length>3 || limits.some(limit=>String(limit).length>280)?`<details><summary>Read all verification gaps</summary><ul>${limits.map(limit=>`<li>${e(limit)}</li>`).join('')}</ul></details>`:''}</section>`:''}${findings.length?`<details class="audit-findings"><summary>All findings (${findings.length})</summary><ol>${findings.map(item).join('')}</ol></details>`:'<p class="hint">No remaining findings were reported within the checks completed.</p>'}${checks.length?`<details class="audit-findings"><summary>Check results: ${checks.filter(c=>c.result==='passed').length} passed, ${failed.length} failed, ${unrun.length} not run</summary><ul>${checks.map(c=>`<li><strong>${e(c.name)} — ${e(c.result)}</strong><p>${e(c.evidence)}</p></li>`).join('')}</ul></details>`:''}`;
}
function openWorkReport(project){
  initWorkDialogs();const report=project.auditReport || {},e=escapeHtml;
  const seed=reportFixSeed(project,report,report.fixPrompt || report.prompt);
  const grade=['A','B','C','D','F'].includes(report.grade)?report.grade:'';
  $('#work-report-body').innerHTML=`<p><strong>${e(project.name)}</strong>${grade?` <span class="audit-grade grade-${grade}">Grade ${grade}</span>`:''}</p><p>${e(report.summary || '')}</p><p class="hint">A — ready to use · B — almost done, usable · C — minor fixes remain · D — not ready for real use · F — not working</p>${report.checkedAt || report.completedAt?`<p class="hint">${e(dateText(report.checkedAt || report.completedAt))}</p>`:''}${auditHighlights(report)}<details class="audit-full-evidence"><summary>Full audit details and reviewer evidence</summary><pre class="audit-report-text" tabindex="0" aria-label="Full audit details">${e(reportText(report))}</pre></details>`;
  $('#work-fix-prompt').value=seed?.instructions || '';
  $('#work-fix-prompt').placeholder='This report has no recommended fix prompt.';
  $('#work-copy-prompt').disabled=!seed;$('#work-send-prompt').disabled=!seed || workBusy(project);
  $('#work-send-prompt').onclick=()=>reviewReportFix(project,seed,$('#work-report'));
  $('#work-copy-status').textContent=workBusy(project)?'Current work is still running. You can review the report and send fixes after it finishes.':'';
  $('#work-report').showModal();
}
function openAdvisorReport(project){
  let dialog=$('#advisor-report');
  if(!dialog){
    dialog=document.createElement('dialog');dialog.id='advisor-report';
    dialog.innerHTML='<div class="dialog-heading"><h2>Panel of advisors</h2><button type="button" class="quiet" aria-label="Close advisor report">×</button></div><div id="advisor-report-body"></div><p id="advisor-copy-status" class="hint" role="status"></p>';
    document.body.append(dialog);dialog.querySelector('button').onclick=()=>dialog.close();
  }
  const r=project.advisorReport || {},e=escapeHtml;
  const labels={continue:'Continue',pivot:'Pivot',shelve:'Shelve this project',split:'Panel split',inconclusive:'Insufficient evidence','insufficient-evidence':'Insufficient evidence'};
  const list=items=>items?.length?`<ul>${items.map(value=>`<li>${e(value)}</li>`).join('')}</ul>`:'';
  const source=item=>{
    let url;try{url=new URL(item.reference);}catch{}
    const safe=url && ['http:','https:'].includes(url.protocol) && !url.username && !url.password;
    return `<li><span>${e(item.finding)}</span><small>${e(item.kind)} · ${safe?`<a href="${e(url.href)}" target="_blank" rel="noopener noreferrer">${e(item.reference)}</a>`:e(item.reference)}</small></li>`;
  };
  // Enforce this in the presentation as well as the engine. A stale or malformed
  // report must never expose fix-prompt controls with a unanimous-shelve verdict.
  const shelved=r.decision==='shelve' || (r.advisors?.length===3 && r.advisors.every(a=>a.status==='complete' && a.verdict==='shelve'));
  const decision=shelved?'shelve':r.decision;
  const prompts=shelved?[]:(r.fixPrompts || []);
  const seedFor=value=>{
    if(value==='all')return reportFixSeed(project,r,prompts.map(p=>`${p.advisor}: ${p.title}\n\n${p.prompt}`).join('\n\n---\n\n'),'advisor','all advisor fix prompts');
    const index=Number(value),p=prompts[index];
    return p?reportFixSeed(project,r,p.prompt,'advisor',`Prompt ${index+1}, ${p.advisor}: ${p.title}`):null;
  };
  $('#advisor-report-body').innerHTML=`<p><strong>${e(project.name)}</strong></p><div class="advisor-decision ${shelved?'shelve':''}"><strong>${e(labels[decision] || decision || 'Review pending')}</strong><p>${e(r.summary)}</p>${shelved?'<p>No fix prompts were generated. This report does not archive the project.</p>':''}</div>${r.completedAt?`<p class="hint">Reviewed ${e(dateText(r.completedAt))} · ${r.researchEnabled?'Web research enabled where useful':'Project evidence only'}</p>`:''}<p class="hint">Grades apply to each advisor’s remit: A excellent, B strong, C material gaps, D weak, F failing, N/A not assessed. The continue/pivot/shelve verdict is separate.</p><div class="advisor-grade-list">${(r.advisors || []).map(a=>`<span><strong>${e(a.name)}: ${e(a.grade)}</strong><small>${e(labels[a.verdict] || a.verdict)} · ${e(a.confidence)} confidence${a.status!=='complete'?' · review incomplete':''}</small></span>`).join('')}</div>${r.shelveReasons?.length?`<h3>Why shelve it</h3>${list(r.shelveReasons)}`:''}${(r.advisors || []).map(a=>`<section class="advisor-review"><h3>${e(a.name)} · ${e(a.grade)}</h3><p>${e(a.summary)}</p>${list(a.reasons)}${a.strengths?.length?`<h4>What holds up</h4>${list(a.strengths)}`:''}${a.risks?.length?`<h4>What does not</h4>${list(a.risks)}`:''}${a.unconventionalOpportunity?`<h4>Could a different approach work?</h4><p>${e(a.unconventionalOpportunity)}</p>`:''}${a.reconsiderIf?`<h4>What would change this judgment</h4><p>${e(a.reconsiderIf)}</p>`:''}${a.evidence?.length?`<details><summary>Evidence and sources</summary><ul class="advisor-sources">${a.evidence.map(source).join('')}</ul></details>`:''}${a.limitations?.length?`<h4>Limits of this review</h4>${list(a.limitations)}`:''}</section>`).join('')}${prompts.length?`<section class="advisor-prompts"><h3>Prompts to fix</h3><div class="report-prompt-actions"><button type="button" data-copy-advisor="all">Copy all fix prompts</button><button type="button" data-send-advisor="all"${workBusy(project)?' disabled':''}>Send all to Codex</button></div>${prompts.map((p,index)=>`<details><summary>${e(p.advisor)} · ${e(p.title)}</summary><pre>${e(seedFor(String(index))?.instructions || p.prompt)}</pre><div class="report-prompt-actions"><button type="button" data-copy-advisor="${index}">Copy this prompt</button><button type="button" data-send-advisor="${index}"${workBusy(project)?' disabled':''}>Send to Codex</button></div></details>`).join('')}</section>`:!shelved?'<p class="hint">No supported fix prompts are available. Check the advisors’ findings and limits above.</p>':''}${r.limitations?.length?`<h3>Panel limits</h3>${list(r.limitations)}`:''}`;
  $('#advisor-copy-status').textContent='';
  dialog.querySelectorAll('[data-copy-advisor]').forEach(button=>button.onclick=async()=>{
    const value=button.dataset.copyAdvisor;
    const text=seedFor(value)?.instructions || '';
    try{await navigator.clipboard.writeText(text);$('#advisor-copy-status').textContent='Fix prompt copied.';}
    catch{$('#advisor-copy-status').textContent='Clipboard unavailable. Select the prompt text above and copy it.';}
  });
  dialog.querySelectorAll('[data-send-advisor]').forEach(button=>button.onclick=()=>reviewReportFix(project,seedFor(button.dataset.sendAdvisor),dialog));
  dialog.showModal();
}
async function handleWorkAction(project,action){
  if(!action.startsWith('work-'))return false;
  const operation=action.slice(5);
  initWorkDialogs();
  if(operation==='advisor-report'){openAdvisorReport(project);return true;}
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
    await load();notice(result.note || ({pause:'Current work can finish; queued content is held.',resume:'Queue resumed.',wrap:'Wrap-up requested.',release:'Commit, push, and published release started.',assess:'Readiness review started.','finish-team':'Finishing team started.',advisors:'Three advisors are reviewing code, adoption, and marketing.',health:'Website check finished.','retry-monitor':'Work status checked.'})[operation] || 'Project updated.');
  }catch(error){notice(error.message);}
  return true;
}
