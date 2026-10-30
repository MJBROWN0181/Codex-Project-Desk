let projects = [], editing = null, logging = null, moving = null, chatAssignments = {}, completing = null, codexMessages = {}, projectDeskRoot = '';
const $ = s => document.querySelector(s);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateText = value => value ? new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)) : 'No activity recorded';
function deliveryLabel(receipt){
  return ({working:'Sending to Codex…',queued:'Queued in Codex',received:'Received by Codex',failed:'Send failed',unknown:'Delivery needs checking'})[receipt.status] || receipt.status;
}
let noticeTimer,projectLoadSequence=0;
let focusOnly=false;
try{focusOnly=localStorage.getItem('project-desk-focus')==='true';}catch{}
let archivedView=false,archiveBackend=false,archivePending={};
const archiveKey='project-desk-archive-pending';
function readArchivePending(){
  try{const saved=JSON.parse(localStorage.getItem(archiveKey) || '{}');return Object.fromEntries(Object.entries(saved).filter(([id,v])=>id && typeof v?.archived==='boolean' && Number.isFinite(v.at)));}catch{return {};}
}
archivePending=readArchivePending();
function isArchived(p){
  const pending=archivePending[p.id];
  if(pending && p.archiveUpdatedAt && Date.parse(p.archiveUpdatedAt)>=pending.at)return !!p.archived;
  return pending?.archived ?? !!p.archived;
}
function storeArchivePending(value){localStorage.setItem(archiveKey,JSON.stringify(value));archivePending=value;}
async function syncArchivePending(data){
  if(!data.features?.projectArchive)return;
  for(const [id,entry] of Object.entries(archivePending)){
    const index=data.projects.findIndex(p=>p.id===id);if(index<0)continue;
    try{
      const p=data.projects[index];
      if(!(p.archiveUpdatedAt && Date.parse(p.archiveUpdatedAt)>=entry.at))data.projects[index]=await request('/api/projects',{id,archived:entry.archived});
      const pending=readArchivePending();
      if(pending[id]?.at===entry.at){delete pending[id];storeArchivePending(pending);}
    }catch{/* Keep the saved choice until a later refresh can synchronize it. */}
  }
}
async function setProjectArchived(project,archived){
  const pending=readArchivePending();pending[project.id]={archived,at:Date.now()};storeArchivePending(pending);
  render();
  if(archiveBackend)await load();
  notice((archived?'Project archived. Files and chats are kept.':'Project restored to the desk.')+(archivePending[project.id]?' Saved in this browser; desk-wide sync is pending.':''));
}
window.addEventListener('storage',event=>{if(event.key===archiveKey){archivePending=readArchivePending();render();}});
function notice(text) { $('#notice').textContent = text; clearTimeout(noticeTimer); noticeTimer = setTimeout(()=>$('#notice').textContent='',6500); }
async function request(url, body) {
  const response = await fetch(url, body === undefined ? {cache:'no-store'} : {method:'POST',keepalive:url==='/api/drafts',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Could not save changes.'); return data;
}
// Card appearance comes from saved work state; grades and activity are independent.
const observedCardCompletions=new Map(),pendingCardCelebrations=new Map();
function cardWorkState(p){
  const w=p.workState || {};
  if(w.phase==='failed' || (w.phase==='attention' && ['failed','interrupted'].includes(w.outcome)))return {key:'blocked',label:'Work stopped'};
  if(w.phase==='attention' || w.monitorError)return {key:'attention',label:'Needs attention'};
  if(w.phase==='working')return {key:'working',label:'Working'};
  if(w.phase==='operation')return {key:'working',label:['assess','finish-team','advisors'].includes(w.operation)?'Reviewing':'Working'};
  if(['sending','queued'].includes(w.phase))return {key:'waiting',label:w.phase==='sending'?'Sending to Codex':'Waiting for Codex'};
  if(p.workPaused || p.status==='Paused')return {key:'paused',label:'Paused'};
  if(p.blocker || p.websiteHealth?.state==='down')return {key:'blocked',label:p.blocker?'Blocked':'Site needs attention'};
  if(p.status==='Complete')return {key:'complete',label:'Project marked complete'};
  if(w.outcome==='completed' || w.phase==='complete')return {key:'finished',label:'Task finished'};
  if(p.status==='Waiting')return {key:'attention',label:'Waiting on something'};
  return {key:'ready',label:'Ready'};
}
function cardShortDate(value){
  const at=Date.parse(value);
  return Number.isFinite(at)?new Intl.DateTimeFormat(undefined,{dateStyle:'medium'}).format(at):'Date unavailable';
}
function cardActivity(p,now=Date.now()){
  const dates=(p.activity || []).map(a=>Date.parse(a.at)).filter(Number.isFinite);
  if(!dates.length)return {quiet:false,text:'No activity yet',title:'No work activity has been recorded for this project.'};
  const at=Math.max(...dates);
  if(at>now+60000)return {quiet:false,text:'Check activity date',title:'The latest recorded activity is dated in the future.'};
  const days=Math.max(0,Math.floor((now-at)/86400000));
  const idle=!['working','operation','sending','queued'].includes(p.workState?.phase);
  const quiet=idle && days>=7 && !isArchived(p) && p.status!=='Complete';
  return {quiet,text:quiet?`Quiet for ${days} days`:days===0?'Worked on today':days===1?'Worked on yesterday':`Last activity ${days} days ago`,title:'Last recorded work: '+dateText(at)+'. Activity age does not grade project quality.'};
}
function cardSignals(p,state){
  const e=escapeHtml,activity=cardActivity(p),report=p.auditReport;
  const grade=/^[ABCDF]$/.test(report?.grade)?report.grade:null;
  const audited=report?.completedAt || report?.checkedAt;
  return `<div class="card-signals" aria-label="Project status and stats"><span class="card-state-label"><span class="card-state-dot" aria-hidden="true"></span>${e(state.label)}</span>${report?`<button type="button" class="card-audit-stat card-audit-grade-${grade || 'unknown'}" data-action="work-report" title="${e('Open the saved audit. Its grade reflects that review, not current work status. '+(audited?'Reviewed '+dateText(audited):'Review date unavailable.'))}"><strong>${e(grade?'Audit '+grade:'Audit not graded')}</strong><span>${e(cardShortDate(audited))}</span>${['waiting-fixes','queued','running'].includes(p.auditFollowUp?.status)?'<span>Pending re-audit</span>':''}</button>`:'<span class="card-stat">Not audited</span>'}<span class="card-stat${activity.quiet?' card-quiet':''}" title="${e(activity.title)}">${e(activity.text)}</span></div>`;
}
function cardCompletion(p){
  const candidates=[];
  const add=(key,at)=>{const stamp=Date.parse(at);if(Number.isFinite(stamp))candidates.push({key:key+':'+stamp,at:stamp});};
  if(p.workState?.outcome==='completed')add('codex',p.workState.completedAt);
  for(const a of p.activity || [])if(a.source==='Codex completion' && a.note==='Codex work completed')add('codex',a.at);
  for(const a of p.completedActions || [])add('manual:'+a.id,a.at);
  return candidates.sort((a,b)=>b.at-a.at)[0] || {key:'none',at:0};
}
function observeCardCompletions(items,now=Date.now()){
  for(const p of items){
    const completion=cardCompletion(p),previous=observedCardCompletions.get(p.id);
    if(previous && completion.key!==previous.key && completion.at>previous.at && now-completion.at>=-5000 && now-completion.at<120000 && !isArchived(p))pendingCardCelebrations.set(p.id,now+6000);
    if(!previous || completion.at>=previous.at)observedCardCompletions.set(p.id,completion);
  }
}
function celebrateVisibleCards(){
  for(const [id,until] of pendingCardCelebrations){
    if(until<Date.now()){pendingCardCelebrations.delete(id);continue;}
    const card=document.querySelector(`article.project[data-id="${CSS.escape(id)}"]`);
    if(!card)continue;
    pendingCardCelebrations.delete(id);card.classList.add('card-celebrating');
    const message=document.createElement('span');message.className='card-celebration-message';message.setAttribute('role','status');message.textContent='Task finished in '+(projects.find(p=>p.id===id)?.name || 'this project')+'.';card.append(message);
    setTimeout(()=>{card.classList.remove('card-celebrating');message.remove();},2600);
  }
}
async function load() {
  const sequence=++projectLoadSequence;
  const data = await request('/api/projects');
  if(sequence!==projectLoadSequence)return;
  archiveBackend=!!data.features?.projectArchive;
  await syncArchivePending(data);
  if(sequence!==projectLoadSequence)return;
  observeCardCompletions(data.projects);
  projects = data.projects; chatAssignments = data.chatAssignments || {};
  projectDeskRoot=data.appRoot || '';
  codexMessages=data.codexMessages || {};
  const sources = data.codex?.sources?.map(s=>`${s.name}: ${dateText(s.at)}`).join(' · ');
  $('#source').textContent = `Project index: ${sources || 'No saved index imported yet.'} Local chat replies and work completion are checked automatically while Project Desk runs.`;
  if(data.codexConnections)$('#connection-summary').textContent=`Chat connections: ${data.codexConnections.verified} verified locally, ${data.codexConnections.cloud || 0} cloud references, ${data.codexConnections.unavailable.length} need attention. Checked ${dateText(data.codexConnections.checkedAt)}.`;
  render();
  if(data.setup?.required && !document.querySelector('dialog[open]'))openSetup(data.setup);
}
// Size grid spans from each card's content instead of stretching a whole row.
let projectLayoutFrame=0,projectLayoutWidth=0;
function layoutProjectCards(){
  const container=$('#projects');
  if(!container)return;
  const cards=[...container.querySelectorAll(':scope > article.project')];
  if(!cards.length){container.classList.remove('projects-fit');return;}
  container.classList.add('projects-fit');
  const row=parseFloat(getComputedStyle(container).gridAutoRows) || 4;
  const spans=cards.map(card=>Math.max(1,Math.ceil((card.getBoundingClientRect().height+18)/row)));
  cards.forEach((card,index)=>{const span='span '+spans[index];if(card.style.gridRowEnd!==span)card.style.gridRowEnd=span;});
}
function scheduleProjectLayout(){
  if(projectLayoutFrame)return;
  projectLayoutFrame=requestAnimationFrame(()=>{projectLayoutFrame=0;layoutProjectCards();});
}
const projectCardSizes=typeof ResizeObserver==='function'?new ResizeObserver(scheduleProjectLayout):null;
const projectListSize=typeof ResizeObserver==='function'?new ResizeObserver(entries=>{
  const width=entries[0]?.contentRect.width;
  if(width!==projectLayoutWidth){projectLayoutWidth=width;scheduleProjectLayout();}
}):null;
projectListSize?.observe($('#projects'));
window.addEventListener('resize',scheduleProjectLayout);
document.fonts?.ready.then(scheduleProjectLayout);
function render() {
  const query = $('#search').value.toLowerCase();
  const pool=projects.filter(p=>isArchived(p)===archivedView);
  let shown = pool.filter(p=>(archivedView || !focusOnly || p.pinned) && (!$('#status').value || p.status===$('#status').value) && (!$('#kind').value || p.kind===$('#kind').value) && [p.name,p.agency,p.nextAction,p.blocker,p.suggestion?.text].join(' ').toLowerCase().includes(query));
  shown.sort((a,b)=>Number(!!b.pinned)-Number(!!a.pinned) || ($('#sort').value==='name' ? a.name.localeCompare(b.name) : (b.activity[0]?.at || '').localeCompare(a.activity[0]?.at || '') || a.name.localeCompare(b.name)));
  $('#focus-only').setAttribute('aria-pressed',String(focusOnly));$('#focus-only').textContent=focusOnly?'Show all projects':'Focus list';
  $('#focus-only').disabled=archivedView;
  $('#archive-view').textContent=archivedView?'Back to desk':`Archived (${projects.filter(isArchived).length})`;
  $('#archive-view').setAttribute('aria-pressed',String(archivedView));
  $('#project-view-title').textContent=archivedView?'Archived projects':'Your projects';
  $('#count').textContent = `${shown.length} of ${pool.length}`;
  projectCardSizes?.disconnect();
  $('#projects').innerHTML = shown.map(p=>{
    const e=escapeHtml, working=workBusy(p), s=working?null:p.suggestion,cardState=cardWorkState(p);
    return `<article class="project card-${cardState.key}" data-id="${e(p.id)}" data-work-state="${cardState.key}"><div class="card-top"><div><h3>${e(p.name)}</h3><span class="kind">${e(p.kind)}${p.kind==='Documents Render' && p.agency?' — '+e(p.agency):''}</span></div><div class="card-controls"><span class="badge ${e(p.status)}">${e(p.status)}</span><div class="card-organize"><button class="pin-project" data-action="pin" aria-pressed="${!!p.pinned}" aria-label="${p.pinned?'Unpin project':'Pin project'}">${p.pinned?'Pinned':'Pin'}</button><button class="archive-project" data-action="${isArchived(p)?'restore':'archive'}" title="${isArchived(p)?'Show this project on the desk again':'Hide from the desk; keep the project, files, and chats'}">${isArchived(p)?'Restore project':'Archive project'}</button></div></div></div><div class="card-body">${cardSignals(p,cardState)}${workMarkup(p)}<div class="next" ${working?'hidden':''}><h4>Your next action</h4><p class="${p.nextAction?'':'empty'}"><button type="button" class="next-action-link" data-action="review">${e(p.nextAction || 'Choose your next step')}</button></p>${p.nextAction?'<button class="done-action" data-action="complete">Mark done manually</button><small class="manual-done-help">Use this for work you finish yourself. Work sent to Codex updates automatically when its chat finishes.</small>':''}</div>${p.blocker?`<p class="blocker"><strong>Blocked by:</strong> ${e(p.blocker)}</p>`:''}${s?`<div class="suggestion"><h4>Suggested next action</h4><p>${e(s.text)}</p><small>${e(s.reason)}</small><small>${e(s.source)}${s.at?' · '+e(dateText(s.at)):''}</small><div class="buttons"><button data-action="accept" title="Send this suggestion directly to the linked Codex chat">Accept</button><button class="quiet" data-action="review-suggestion">Review and send</button><button class="quiet" data-action="dismiss">Dismiss</button></div></div>`:''}${activityMarkup(p)}${p.completedActions?.length?`<details class="completed-history"><summary>Completed actions (${p.completedActions.length})</summary><ol>${p.completedActions.map(item=>`<li><strong>${e(item.action)}</strong><small>${e(dateText(item.at))}</small>${item.note?`<p>${e(item.note)}</p>`:''}</li>`).join('')}</ol></details>`:''}${replyMarkup(p)}<div class="links">${p.repo?`<a href="https://github.com/${e(p.repo)}" target="_blank" rel="noopener noreferrer">GitHub repository</a>`:''}${p.chats.slice(0,2).map(c=>c.connectionStatus==='unavailable'?`<span class="connection-unavailable">Unavailable chat: ${e(c.title)}</span>`:`<a href="${e(c.url)}" title="Open in Codex">${e(compactText(c.title,100))}${c.hostId && c.hostId!=='local'?' <span class="chat-link-cloud">(cloud)</span>':''}</a>`).join('')}</div></div><footer class="card-footer">${p.status==='Unreviewed' && !working?'<button data-action="reviewed">Mark reviewed</button>':''}${p.actionDraft && !working?'<button data-action="review">Resume draft</button>':''}${!working?'<button data-action="edit">Edit project</button><button data-action="log">Log activity</button>':''}${p.chats.length && !working?'<button data-action="move">Move chat</button>':''}${p.chats.some(c=>chatAssignments[c.id]?.nativeStatus==='pending')?'<button data-action="pending">Finish Codex move</button>':''}${p.repo?'<button data-action="github">Refresh GitHub</button>':''}${Object.values(codexMessages).some(r=>r.projectId===p.id)?`<button class="delivery-receipt" data-action="receipt">${e(deliveryLabel(Object.values(codexMessages).filter(r=>r.projectId===p.id).sort((a,b)=>b.createdAt.localeCompare(a.createdAt))[0]))}</button>`:''}${p.githubCheckedAt?`<span class="source-label">GitHub checked ${e(dateText(p.githubCheckedAt))}</span>`:''}</footer></article>`;
  }).join('') || `<p class="no-results">${archivedView?'No archived projects match. Archived projects are kept here and can be restored.':focusOnly?'No pinned projects match. Show all projects to pin one, or adjust your filters.':'No projects match. Change your filters or add a project.'}</p>`;
  layoutProjectCards();
  $('#projects').querySelectorAll(':scope > article.project').forEach(card=>projectCardSizes?.observe(card));
  celebrateVisibleCards();
}
function compactText(value,limit=180){
  const text=String(value ?? '').replace(/\s+/g,' ').trim();
  return text.length>limit?text.slice(0,limit).trimEnd()+'…':text;
}
function activityNoteMarkup(note){
  const text=String(note ?? ''),preview=compactText(text),e=escapeHtml;
  const full=text.replace(/\s+/g,' ').trim().length>180;
  return `<p class="activity-preview">${e(preview)}</p>${full?`<details class="activity-note"><summary>Read full activity</summary><div class="activity-full" tabindex="0" role="region" aria-label="Full activity note">${e(text)}</div></details>`:''}`;
}
function activityMarkup(p){
  const a=p.activity[0],e=escapeHtml;
  return `<div class="activity"><h4>Last worked on</h4><strong>${e(dateText(a?.at))}</strong>${a?`${activityNoteMarkup(a.note)}<span class="source-label">${e(a.source)}</span>`:'<p>Log planning or progress to get started.</p>'}${p.activity.length>1?`<details><summary>Recent activity</summary><ol class="activity-history" tabindex="0" aria-label="Recent project activity">${p.activity.slice(1,8).map(item=>`<li>${activityNoteMarkup(item.note)}${e(dateText(item.at))} · ${e(item.source)}</li>`).join('')}</ol></details>`:''}</div>`;
}
function replyMarkup(p){
  const r=p.latestReply,e=escapeHtml;
  if(!r)return '<section class="latest-reply"><h4>Latest Codex reply</h4><p class="hint">No saved final reply yet. Link a local chat through the next action to see its reply here.</p></section>';
  return `<section class="latest-reply"><h4>Latest Codex reply</h4><p class="reply-preview">${e(compactText(r.text,280))}</p>${r.text.length>280?`<details><summary>Read full reply</summary><p class="reply-full">${e(r.text)}</p>${r.truncated?'<p class="hint">Open the chat for the complete reply.</p>':''}</details>`:''}<a href="codex://threads/${e(r.threadId)}">${e(compactText(r.title,100))}</a><small>${e(dateText(r.at))}</small>${p.replyCheckError?`<p class="hint">${e(p.replyCheckError)}</p>`:''}</section>`;
}
$('#focus-only').onclick=()=>{focusOnly=!focusOnly;try{localStorage.setItem('project-desk-focus',String(focusOnly));}catch{}render();};
$('#archive-view').onclick=()=>{archivedView=!archivedView;render();};
function openEditor(project) {
  editing = project?.id || null;
  const form=$('#project-form'); form.reset(); $('#editor-title').textContent=project?'Edit project':'Add project';
  for (const key of ['name','kind','status','nextAction','blocker','repo','agency','path','websiteUrl']) form.elements[key].value=project?.[key] ?? ({kind:'Mixed',status:'Active'}[key] || '');
  const agencies=[...new Set(projects.map(p=>p.agency).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  $('#agency-options').innerHTML=agencies.map(a=>`<option value="${escapeHtml(a)}"></option>`).join('');
  updateAgency();
  $('#editor-chats').innerHTML=project?.chats.length ? `<h3>Linked Codex chats</h3>${project.chats.map(c=>`<div class="chat-row"><div><a href="${escapeHtml(c.url)}">${escapeHtml(c.title)}</a><small>${escapeHtml(dateText(c.at))}</small>${pendingLabel(c.id)}</div><button type="button" class="quiet" data-thread="${escapeHtml(c.id)}">Move chat</button></div>`).join('')}` : '<p class="hint">No linked Codex chats in the current index.</p>';
  $('#editor').showModal();
}
function pendingLabel(id) {
  return chatAssignments[id]?.nativeStatus==='pending' ? '<small class="pending-move">Move in Codex pending</small>' : '';
}
function updateAgency() {
  const form=$('#project-form'), visible=form.elements.kind.value==='Documents Render';
  $('#agency-field').hidden=!visible; form.elements.agency.required=visible;
}
$('#project-form').elements.kind.onchange=updateAgency;
$('#editor-chats').onclick=event=>{
  const button=event.target.closest('button[data-thread]'); if(!button) return;
  const project=projects.find(p=>p.id===editing); $('#editor').close(); openMover(project,button.dataset.thread);
};
function openMover(project, threadId=null) {
  moving=project.id;
  const form=$('#move-form'); form.reset();
  form.elements.threadId.innerHTML=project.chats.map(c=>`<option value="${escapeHtml(c.id)}">${escapeHtml(c.title)}</option>`).join('');
  form.elements.targetProjectId.innerHTML=projects.filter(p=>p.id!==project.id).sort((a,b)=>a.name.localeCompare(b.name)).map(p=>`<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}${p.codexProjectId?'':' (tracker only)'}</option>`).join('');
  if(threadId) form.elements.threadId.value=threadId;
  updateMoveDestination(); $('#mover').showModal();
}
function updateMoveDestination() {
  const form=$('#move-form'), target=projects.find(p=>p.id===form.elements.targetProjectId.value);
  const native=!!target?.codexProjectId;
  form.elements.native.disabled=!native; form.elements.native.checked=native;
  $('#move-help').textContent=native ? 'The tracker moves its link and activity immediately. Moving the actual chat in Codex requires pasting the prepared instruction into this chat.' : 'This project exists only in the tracker. This move will refile the link and activity here; it will not move the actual Codex chat.';
}
function showMoveResult(result) {
  $('#move-result-note').textContent=`The chat link and its activity are now under ${result.targetName} in Project desk.`;
  $('#native-instruction').hidden=result.nativeStatus!=='pending';
  $('#move-instruction').value=`Move Codex chat ${JSON.stringify(result.title)} (thread ID: ${result.threadId}) to the existing Codex project ${JSON.stringify(result.targetName)} (project ID: ${result.codexProjectId}). Then mark this Project desk move complete in ${projectDeskRoot || 'the Project Desk project folder'} using manage_moves.py after the native move succeeds.`;
  $('#move-result').showModal();
}
$('#move-form').elements.targetProjectId.onchange=updateMoveDestination;
$('#move-form').onsubmit=async event=>{
  event.preventDefault(); const form=event.target, button=form.querySelector('[type=submit]'); button.disabled=true;
  try {
    const result=await request('/api/move-chat',{threadId:form.elements.threadId.value,targetProjectId:form.elements.targetProjectId.value,native:form.elements.native.checked});
    $('#mover').close(); await load();
    showMoveResult(result);
  } catch(error) { notice(error.message); } finally { button.disabled=false; }
};
$('#copy-move').onclick=async()=>{
  try { await navigator.clipboard.writeText($('#move-instruction').value); notice('Instruction copied. Paste it into Codex to finish the move.'); }
  catch { $('#move-instruction').focus(); $('#move-instruction').select(); notice('Select and copy the instruction, then paste it into Codex.'); }
};
$('#add').onclick=()=>openEditor(null);
for(const button of document.querySelectorAll('.close')) button.onclick=()=>button.closest('dialog').close();
for(const id of ['search','status','kind','sort']) $('#'+id).addEventListener(id==='search'?'input':'change',render);
$('#projects').onclick=async event=>{
  const button=event.target.closest('button[data-action]'); if(!button) return;
  const p=projects.find(p=>p.id===button.closest('article').dataset.id), action=button.dataset.action;
  if(await handleWorkAction(p,action))return;
  if(action==='archive' || action==='restore'){
    if(action==='archive' && !window.confirm(`Archive "${p.name}"?\n\nThis removes it from the desk. Files, chats, and history are kept. You can restore it from Archived.`))return;
    button.disabled=true;try{await setProjectArchived(p,action==='archive');}catch(error){notice(error.message);}finally{button.disabled=false;}return;
  }
  if(action==='pin'){
    button.disabled=true;try{await request('/api/projects',{id:p.id,pinned:!p.pinned});await load();}catch(error){notice(error.message);}finally{button.disabled=false;}return;
  }
  if(action==='edit')return openEditor(p);
  if(action==='accept')return acceptSuggestion(p,button);
  if(action==='review-suggestion')return openActionReview(p,null,{key:'suggestion:'+p.id+':'+JSON.stringify(p.suggestion),action:p.suggestion.text,reason:p.suggestion.reason || '',instructions:''});
  if(action==='review')return openActionReview(p);
  if(action==='receipt'){
    const receipt=Object.values(codexMessages).filter(r=>r.projectId===p.id).sort((a,b)=>b.createdAt.localeCompare(a.createdAt))[0];
    if(receipt)openDelivery(receipt);return;
  }
  if(action==='move') return openMover(p);
  if(action==='pending') return showMoveResult(chatAssignments[p.chats.find(c=>chatAssignments[c.id]?.nativeStatus==='pending').id]);
  if(action==='complete') {
    completing={id:p.id, expectedAction:p.nextAction.trim(), requestId:crypto.randomUUID()};
    $('#complete-form').reset(); $('#complete-project').textContent=p.name;
    $('#complete-action-text').textContent=p.nextAction;
    $('#completer').showModal(); return;
  }
  if(action==='log') { logging=p.id; $('#log-form').reset(); $('#log-project').textContent=p.name; $('#logger').showModal(); return; }
  button.disabled=true;
  try {
    await request(action==='github'?'/api/github':'/api/projects',{id:p.id,action});
    await load(); notice(action==='dismiss'?'Suggestion dismissed.':action==='reviewed'?'Project reviewed and marked Active.':'GitHub activity refreshed.');
  } catch(error) { notice(error.message); } finally { button.disabled=false; }
};
$('#project-form').onsubmit=async event=>{
  event.preventDefault(); const form=event.target, button=form.querySelector('[type=submit]'); button.disabled=true;
  try { const payload=Object.fromEntries(new FormData(form)); if(editing) payload.id=editing;
    await request('/api/projects',payload); $('#editor').close(); await load(); notice('Project saved.');
  } catch(error) { notice(error.message); } finally { button.disabled=false; }
};
$('#log-form').onsubmit=async event=>{
  event.preventDefault(); const button=event.target.querySelector('[type=submit]'); button.disabled=true;
  try { await request('/api/projects',{id:logging,action:'log',note:event.target.elements.note.value}); $('#logger').close(); await load(); notice('Activity recorded.'); }
  catch(error) { notice(error.message); } finally { button.disabled=false; }
};
$('#complete-form').onsubmit=async event=>{
  event.preventDefault(); const form=event.target, button=form.querySelector('[type=submit]'); button.disabled=true;
  try {
    await request('/api/projects',{...completing,action:'complete-action',note:form.elements.note.value,nextAction:form.elements.nextAction.value});
    $('#completer').close(); await load(); notice('Action completed. Progress recorded.');
  } catch(error) { notice(error.message); } finally { button.disabled=false; }
};
$('#refresh').onclick=async()=>{
  const button=$('#refresh'); button.disabled=true; button.textContent='Reading saved index…';
  try { await request('/api/codex',{}); await load(); notice('Latest available Codex index imported.'); }
  catch(error) { notice(error.message); } finally { button.disabled=false; button.textContent='Refresh Codex index'; }
};
load().catch(error=>notice(error.message));
$('#refresh-desk').onclick=async()=>{
  const button=$('#refresh-desk');button.disabled=true;button.setAttribute('aria-busy','true');button.textContent='Refreshing…';
  try{await load();const job=await request('/api/codex/replies',{});await waitCodexJob(job.id);await load();notice('Project list refreshed.');}
  catch(error){notice(error.message);}
  finally{button.disabled=false;button.removeAttribute('aria-busy');button.textContent='↻ Refresh';}
};
function refreshWhenIdle(){
  if(document.visibilityState==='visible' && !document.querySelector('dialog[open],#projects details[open]') && !$('#projects').contains(document.activeElement) && !window.getSelection()?.toString())load().catch(()=>{});
}
window.addEventListener('focus',refreshWhenIdle);
setInterval(refreshWhenIdle,5000);
