let projects = [], editing = null, logging = null, moving = null, chatAssignments = {}, completing = null, codexMessages = {};
const $ = s => document.querySelector(s);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateText = value => value ? new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)) : 'No activity recorded';
function deliveryLabel(receipt){
  return ({working:'Sending to Codex…',queued:'Queued in Codex',received:'Received by Codex',failed:'Send failed',unknown:'Delivery needs checking'})[receipt.status] || receipt.status;
}
let noticeTimer,projectLoadSequence=0;
let focusOnly=false;
try{focusOnly=localStorage.getItem('project-desk-focus')==='true';}catch{}
function notice(text) { $('#notice').textContent = text; clearTimeout(noticeTimer); noticeTimer = setTimeout(()=>$('#notice').textContent='',6500); }
async function request(url, body) {
  const response = await fetch(url, body === undefined ? {cache:'no-store'} : {method:'POST',keepalive:url==='/api/drafts',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Could not save changes.'); return data;
}
async function load() {
  const sequence=++projectLoadSequence;
  const data = await request('/api/projects');
  if(sequence!==projectLoadSequence)return;
  projects = data.projects; chatAssignments = data.chatAssignments || {};
  codexMessages=data.codexMessages || {};
  const sources = data.codex?.sources?.map(s=>`${s.name}: ${dateText(s.at)}`).join(' · ');
  $('#source').textContent = `Project index: ${sources || 'No saved index imported yet.'} Local chat replies and work completion are checked automatically while Project Desk runs.`;
  if(data.codexConnections)$('#connection-summary').textContent=`Chat connections: ${data.codexConnections.verified} verified locally, ${data.codexConnections.cloud || 0} cloud references, ${data.codexConnections.unavailable.length} need attention. Checked ${dateText(data.codexConnections.checkedAt)}.`;
  render();
}
function render() {
  const query = $('#search').value.toLowerCase();
  let shown = projects.filter(p=>(!focusOnly || p.pinned) && (!$('#status').value || p.status===$('#status').value) && (!$('#kind').value || p.kind===$('#kind').value) && [p.name,p.agency,p.nextAction,p.blocker,p.suggestion?.text].join(' ').toLowerCase().includes(query));
  shown.sort((a,b)=>Number(!!b.pinned)-Number(!!a.pinned) || ($('#sort').value==='name' ? a.name.localeCompare(b.name) : (b.activity[0]?.at || '').localeCompare(a.activity[0]?.at || '') || a.name.localeCompare(b.name)));
  $('#focus-only').setAttribute('aria-pressed',String(focusOnly));$('#focus-only').textContent=focusOnly?'Show all projects':'Focus list';
  $('#count').textContent = `${shown.length} of ${projects.length}`;
  $('#projects').innerHTML = shown.map(p=>{
    const e=escapeHtml, a=p.activity[0], working=workBusy(p), s=working?null:p.suggestion;
    return `<article class="project" data-id="${e(p.id)}"><div class="card-top"><div><h3>${e(p.name)}</h3><span class="kind">${e(p.kind)}${p.kind==='Documents Render' && p.agency?' — '+e(p.agency):''}</span></div><div class="card-controls"><span class="badge ${e(p.status)}">${e(p.status)}</span><button class="pin-project" data-action="pin" aria-pressed="${!!p.pinned}" aria-label="${p.pinned?'Unpin project':'Pin project'}">${p.pinned?'Pinned':'Pin'}</button></div></div><div class="card-body">${workMarkup(p)}<div class="next" ${working?'hidden':''}><h4>Your next action</h4><p class="${p.nextAction?'':'empty'}"><button type="button" class="next-action-link" data-action="review">${e(p.nextAction || 'Choose your next step')}</button></p>${p.nextAction?'<button class="done-action" data-action="complete">Next action done</button>':''}</div>${p.blocker?`<p class="blocker"><strong>Blocked by:</strong> ${e(p.blocker)}</p>`:''}${s?`<div class="suggestion"><h4>Suggested next action</h4><p>${e(s.text)}</p><small>${e(s.reason)}</small><small>${e(s.source)}${s.at?' · '+e(dateText(s.at)):''}</small><div class="buttons"><button data-action="review">Review and send</button><button data-action="accept">Accept</button><button class="quiet" data-action="change">Change</button><button class="quiet" data-action="dismiss">Dismiss</button></div></div>`:''}<div class="activity"><h4>Last worked on</h4><strong>${e(dateText(a?.at))}</strong>${a?`<p>${e(a.note)}</p><span class="source-label">${e(a.source)}</span>`:'<p>Log planning or progress to get started.</p>'}${p.activity.length>1?`<details><summary>Recent activity</summary><ol>${p.activity.slice(1,8).map(item=>`<li>${e(item.note)}<br>${e(dateText(item.at))} · ${e(item.source)}</li>`).join('')}</ol></details>`:''}</div>${p.completedActions?.length?`<details class="completed-history"><summary>Completed actions (${p.completedActions.length})</summary><ol>${p.completedActions.map(item=>`<li><strong>${e(item.action)}</strong><small>${e(dateText(item.at))}</small>${item.note?`<p>${e(item.note)}</p>`:''}</li>`).join('')}</ol></details>`:''}${replyMarkup(p)}<div class="links">${p.repo?`<a href="https://github.com/${e(p.repo)}" target="_blank" rel="noopener noreferrer">GitHub repository</a>`:''}${p.chats.slice(0,2).map(c=>c.connectionStatus==='unavailable'?`<span class="connection-unavailable">Unavailable chat: ${e(c.title)}</span>`:`<a href="${e(c.url)}" title="Open in Codex">${e(c.title)}${c.hostId && c.hostId!=='local'?' <span class="chat-link-cloud">(cloud)</span>':''}</a>`).join('')}</div></div><footer class="card-footer">${p.actionDraft && !working?'<button data-action="review">Resume draft</button>':''}${!working?'<button data-action="edit">Edit project</button><button data-action="log">Log activity</button>':''}${p.chats.length && !working?'<button data-action="move">Move chat</button>':''}${p.chats.some(c=>chatAssignments[c.id]?.nativeStatus==='pending')?'<button data-action="pending">Finish Codex move</button>':''}${p.repo?'<button data-action="github">Refresh GitHub</button>':''}${Object.values(codexMessages).some(r=>r.projectId===p.id)?`<button class="delivery-receipt" data-action="receipt">${e(deliveryLabel(Object.values(codexMessages).filter(r=>r.projectId===p.id).sort((a,b)=>b.createdAt.localeCompare(a.createdAt))[0]))}</button>`:''}${p.githubCheckedAt?`<span class="source-label">GitHub checked ${e(dateText(p.githubCheckedAt))}</span>`:''}</footer></article>`;
  }).join('') || `<p class="no-results">${focusOnly?'No pinned projects match. Show all projects to pin one, or adjust your filters.':'No projects match. Change your filters or add a project.'}</p>`;
}
function replyMarkup(p){
  const r=p.latestReply,e=escapeHtml;
  if(!r)return '<section class="latest-reply"><h4>Latest Codex reply</h4><p class="hint">No saved final reply yet. Link a local chat through the next action to see its reply here.</p></section>';
  return `<section class="latest-reply"><h4>Latest Codex reply</h4><p class="reply-preview">${e(r.text.slice(0,280))}${r.text.length>280?'…':''}</p>${r.text.length>280?`<details><summary>Read full reply</summary><p class="reply-full">${e(r.text)}</p>${r.truncated?'<p class="hint">Open the chat for the complete reply.</p>':''}</details>`:''}<a href="codex://threads/${e(r.threadId)}">${e(r.title)}</a><small>${e(dateText(r.at))}</small>${p.replyCheckError?`<p class="hint">${e(p.replyCheckError)}</p>`:''}</section>`;
}
$('#focus-only').onclick=()=>{focusOnly=!focusOnly;try{localStorage.setItem('project-desk-focus',String(focusOnly));}catch{}render();};
function openEditor(project, suggestion=false) {
  editing = project?.id || null;
  const form=$('#project-form'); form.reset(); $('#editor-title').textContent=project?'Edit project':'Add project';
  for (const key of ['name','kind','status','nextAction','blocker','repo','agency','path','websiteUrl']) form.elements[key].value=project?.[key] ?? ({kind:'Mixed',status:'Active'}[key] || '');
  const agencies=[...new Set(projects.map(p=>p.agency).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
  $('#agency-options').innerHTML=agencies.map(a=>`<option value="${escapeHtml(a)}"></option>`).join('');
  updateAgency();
  $('#editor-chats').innerHTML=project?.chats.length ? `<h3>Linked Codex chats</h3>${project.chats.map(c=>`<div class="chat-row"><div><a href="${escapeHtml(c.url)}">${escapeHtml(c.title)}</a><small>${escapeHtml(dateText(c.at))}</small>${pendingLabel(c.id)}</div><button type="button" class="quiet" data-thread="${escapeHtml(c.id)}">Move chat</button></div>`).join('')}` : '<p class="hint">No linked Codex chats in the current index.</p>';
  if (suggestion) form.elements.nextAction.value=project.suggestion.text;
  form.dataset.change = suggestion?'true':'false'; $('#editor').showModal();
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
  $('#move-instruction').value=`Move Codex chat ${JSON.stringify(result.title)} (thread ID: ${result.threadId}) to the existing Codex project ${JSON.stringify(result.targetName)} (project ID: ${result.codexProjectId}). Then mark this Project desk move complete in C:/Users/Mjbro/Desktop/Projects/ME/project-tracker using manage_moves.py after the native move succeeds.`;
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
  if(action==='pin'){
    button.disabled=true;try{await request('/api/projects',{id:p.id,pinned:!p.pinned});await load();}catch(error){notice(error.message);}finally{button.disabled=false;}return;
  }
  if(action==='edit' || action==='change') return openEditor(p,action==='change');
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
    await load(); notice(action==='accept'?'Next action accepted.':action==='dismiss'?'Suggestion dismissed.':'GitHub activity refreshed.');
  } catch(error) { notice(error.message); } finally { button.disabled=false; }
};
$('#project-form').onsubmit=async event=>{
  event.preventDefault(); const form=event.target, button=form.querySelector('[type=submit]'); button.disabled=true;
  try { const payload=Object.fromEntries(new FormData(form)); if(editing) payload.id=editing;
    if(form.dataset.change==='true') payload.action='dismiss';
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
