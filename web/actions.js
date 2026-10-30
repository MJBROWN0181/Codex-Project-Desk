let actionReview=null, actionGeneration=0, actionSendId=null,deliveryWatch=0,actionReviewSeed=null,actionSuggestion=null;
const suggestionSendRequests=new Map(),suggestionSending=new Set();
async function acceptSuggestion(project,button){
  const key=project.id+JSON.stringify(project.suggestion);
  if(suggestionSending.has(key))return;
  suggestionSending.add(key);button.disabled=true;button.textContent="Sending…";
  if(!suggestionSendRequests.has(key))suggestionSendRequests.set(key,crypto.randomUUID());
  try{
    const receipt=await request("/api/codex/accept-suggestion",{projectId:project.id,requestId:suggestionSendRequests.get(key),suggestion:project.suggestion});
    await load().catch(()=>{});await openDelivery(receipt);
  }catch(error){notice(error.message);}
  finally{suggestionSending.delete(key);button.disabled=false;button.textContent="Accept";}
}
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let pickerChats=[];
function renderChatPicker(){
  const select=$('#action-form').elements.threadId,query=$('#chat-picker-search').value.trim().toLowerCase();
  const shown=pickerChats.filter(c=>c.title.toLowerCase().includes(query));
  $('#chat-picker-value').textContent=pickerChats.find(c=>c.id===select.value)?.title || 'Choose a Codex chat';
  $('#chat-picker-options').innerHTML=shown.map(c=>`<button type="button" class="chat-choice" data-chat="${escapeHtml(c.id)}" aria-pressed="${c.id===select.value}"><span>${escapeHtml(c.title)}</span><small>${c.linked?'Linked to this project':'Other local chat'}${c.cwd?' · '+escapeHtml(c.cwd):''}</small></button>`).join('');
  $('#chat-picker-empty').hidden=!!shown.length;
}
function closeChatPicker(){ $('#chat-picker-panel').hidden=true;$('#chat-picker-toggle').setAttribute('aria-expanded','false'); }
$('#chat-picker-toggle').onclick=()=>{
  const opening=$('#chat-picker-panel').hidden;$('#chat-picker-panel').hidden=!opening;$('#chat-picker-toggle').setAttribute('aria-expanded',String(opening));
  if(opening){$('#chat-picker-search').value='';renderChatPicker();$('#chat-picker-search').focus();}
};
$('#chat-picker-search').oninput=renderChatPicker;
$('#chat-picker-options').onclick=event=>{
  const choice=event.target.closest('[data-chat]');if(!choice)return;
  const select=$('#action-form').elements.threadId;select.value=choice.dataset.chat;closeChatPicker();renderChatPicker();$('#chat-picker-toggle').focus();select.dispatchEvent(new Event('change'));
};
$('#chat-picker-panel').onkeydown=event=>{
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeChatPicker();$('#chat-picker-toggle').focus();return;}
  if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
    const buttons=[...$('#chat-picker-options').querySelectorAll('button')];if(!buttons.length)return;
    event.preventDefault();let i=buttons.indexOf(document.activeElement);
    i=event.key==='Home'?0:event.key==='End'?buttons.length-1:event.key==='ArrowDown'?(i+1)%buttons.length:(i-1+buttons.length)%buttons.length;buttons[i].focus();
  }
};
async function waitCodexJob(id,onUpdate=null,shouldContinue=()=>true){
  for(let i=0;i<240;i++){
    if(!shouldContinue())throw new Error('Recommendation canceled.');
    const job=await request('/api/codex/jobs/'+encodeURIComponent(id));
    if(onUpdate)onUpdate(job);
    if(job.status==='complete')return job.result;
    if(job.status==='failed')throw new Error(job.error || 'Codex request failed.');
    await pause(1000);
  }
  throw new Error('Codex is still processing. You can close this view and try again later.');
}
function updateActionPreview(){
  const form=$('#action-form');
  let text='Next step:\n'+form.elements.action.value.trim();
  if(form.elements.reason.value.trim())text+='\n\nWhy this step:\n'+form.elements.reason.value.trim();
  if(form.elements.instructions.value.trim())text+='\n\nAdditional instructions:\n'+form.elements.instructions.value.trim();
  $('#action-preview').textContent=text;
}
function setRecommendationBusy(busy){
  $('#recommendation-thinking').hidden=!busy;
  $('#recommend-action').setAttribute('aria-busy',String(busy));
  $('#recommend-action').textContent=busy?'Thinking…':'Ask agent to recommend again';
}
async function generateAction(){
  const form=$('#action-form'),id=form.elements.threadId.value,sequence=++actionGeneration;
  if(!id){
    setRecommendationBusy(false);
    form.elements.action.readOnly=false;form.elements.reason.readOnly=false;
    $('#send-action').disabled=true;$('#recommend-action').disabled=true;
    $('#action-status').textContent='Choose an existing Codex chat to continue.';return;
  }
  form.elements.action.readOnly=true;form.elements.reason.readOnly=true;$('#send-action').disabled=true;
  setRecommendationBusy(true);
  $('#recommend-action').disabled=true;$('#action-status').textContent='Codex agent is reviewing recent messages and choosing a next step…';
  try{
    const job=await request('/api/codex/recommend',{projectId:actionReview.id,threadId:id});
    const answer=await waitCodexJob(job.id,null,()=>sequence===actionGeneration && $('#action-review').open);
    if(sequence!==actionGeneration || !$('#action-review').open)return;
    form.elements.action.value=answer.action;form.elements.reason.value=answer.reason;
    markDraftChanged();
    updateActionPreview();$('#action-status').textContent='Agent recommendation ready. Review or edit it, add instructions, then send.';
  }catch(error){if(sequence===actionGeneration)$('#action-status').textContent=error.message;}
  finally{if(sequence===actionGeneration){setRecommendationBusy(false);$('#recommend-action').disabled=false;form.elements.action.readOnly=false;form.elements.reason.readOnly=false;$('#send-action').disabled=false;}}
}
async function openActionReview(project,seed=null,suggestion=null){
  actionReview=project;actionSendId=crypto.randomUUID();const openSequence=++actionGeneration;
  actionReviewSeed=seed;actionSuggestion=suggestion;const source=seed || suggestion;
  $('#action-review h2').textContent=seed?'Review audit fixes':suggestion?'Review suggestion':'Review next action';
  $('#recommend-action').hidden=!!source;
  setRecommendationBusy(false);
  const form=$('#action-form');form.reset();
  closeChatPicker();pickerChats=[];$('#chat-picker-search').value='';
  $('#chat-destination').hidden=!!seed;$('#audit-destination').hidden=!seed;form.elements.threadId.disabled=!!seed;
  $('#chat-picker-toggle').disabled=true;
  $('#action-send-help').textContent=seed?'Send creates a new Audit chat for this project and delivers the reviewed fixes. Existing chats are preserved.':'Send delivers this reviewed message to the selected local chat and opens it in Codex.';
  form.elements.action.readOnly=true;form.elements.reason.readOnly=true;form.elements.instructions.readOnly=true;
  form.elements.action.value=source?.action || project.nextAction || project.suggestion?.text || '';
  form.elements.reason.value=source?.reason || project.nextActionReason || project.suggestion?.reason || '';
  form.elements.instructions.value=source?.instructions || '';
  $('#action-project').textContent=project.name;$('#action-status').textContent='Checking available Codex chats…';
  form.elements.threadId.innerHTML='<option value="">Loading chats…</option>';
  $('#send-action').disabled=true;$('#recommend-action').disabled=true;updateActionPreview();$('#action-review').showModal();
  try{
    const [result,draft]=await Promise.all([seed?Promise.resolve({chats:[]}):request('/api/codex/threads'),restoreActionDraft(project.id,openSequence,source?.key,suggestion?'Suggestion':'Audit fix')]);
    if(openSequence!==actionGeneration || !$('#action-review').open)return;
    const all=new Map(result.chats.map(c=>[c.id,c]));
    const normalized=value=>(value || '').replace(/[\\/]+/g,'/').replace(/\/$/,'').toLowerCase();
    const linked=project.chats.filter(c=>all.has(c.id));
    const matching=project.path?result.chats.filter(c=>normalized(c.cwd)===normalized(project.path)):[];
    const ordered=[...linked.map(c=>all.get(c.id)),...result.chats.filter(c=>!linked.some(l=>l.id===c.id))];
    form.elements.threadId.innerHTML='<option value="">Choose a Codex chat</option>'+ordered.map(c=>`<option value="${escapeHtml(c.id)}">${escapeHtml(c.title)}${linked.some(l=>l.id===c.id)?' (linked to this project)':''}</option>`).join('');
    const preferred=draft?(all.has(draft.threadId)?draft.threadId:null):(all.has(project.preferredChatId)?project.preferredChatId:(linked[0]?.id || matching[0]?.id));
    if(preferred)form.elements.threadId.value=preferred;
    pickerChats=ordered.map(c=>({...c,linked:linked.some(l=>l.id===c.id)}));renderChatPicker();$('#chat-picker-toggle').disabled=false;
    $('#send-action').disabled=!seed && !preferred;$('#recommend-action').disabled=!preferred;
    form.elements.action.readOnly=false;form.elements.reason.readOnly=false;form.elements.instructions.readOnly=false;
    if(draft){
      for(const key of ['action','reason','instructions'])form.elements[key].value=draft[key] || '';
      updateActionPreview();$('#send-action').disabled=!seed && !preferred;
      $('#action-status').textContent=preferred?'Saved draft restored. Review it before sending.':'The draft is preserved. Choose an available local chat before sending.';
    }else if(source){
      $('#send-action').disabled=!seed && !preferred;
      $('#action-status').textContent=seed?'Audit fix prompt ready. Review or edit it before sending to a new Audit chat.':'Displayed suggestion ready. Edit it, choose the destination, then send.';
      markDraftChanged();updateActionPreview();
    }else if(preferred)generateAction();else $('#action-status').textContent='Choose the existing Codex chat that should handle this project. A recommendation will be generated for that chat.';
    if(source && project.workPaused){
      $('#send-action').disabled=true;$('#action-status').textContent='This project is paused. Resume its queue on the card before sending these fixes. Your audit edits are saved separately.';
    }
    if(seed && !project.workPaused)$('#action-status').textContent='Review the fixes below. Send will create a new chat named Audit; nothing has been sent.';
  }catch(error){if(openSequence===actionGeneration)$('#action-status').textContent=error.message;}
}
function showReceipt(receipt){
  $('#delivery-title').textContent=deliveryLabel(receipt);
  $('#delivery-chat').textContent=receipt.title || 'Selected Codex chat';
  $('#delivery-note').textContent=receipt.error || receipt.note || (receipt.status==='received'?'Your message appears in the destination chat. Work completion is tracked separately.':'Your message is queued for the selected chat. Waiting for confirmation in chat history.');
  $('#delivery-message').textContent=receipt.message;
}
async function openDelivery(receipt){
  const watch=++deliveryWatch;showReceipt(receipt);
  if(!$('#delivery').open)$('#delivery').showModal();
  try{
    for(let i=0;i<80;i++){
      if(watch!==deliveryWatch || !$('#delivery').open)break;
      const latest=await request('/api/codex/jobs/'+encodeURIComponent(receipt.id));
      if(watch!==deliveryWatch || !$('#delivery').open)break;
      showReceipt(latest);
      if(['received','failed','unknown'].includes(latest.status))break;
      await pause(1000);
    }
  }catch(error){if(watch===deliveryWatch && $('#delivery').open)$('#delivery-note').textContent=error.message;}
  finally{if(watch===deliveryWatch)await load().catch(error=>notice(error.message));}
}
$('#delivery').addEventListener('close',()=>{
  ++deliveryWatch;load().catch(()=>{});
});
$('#action-form').addEventListener('input',updateActionPreview);
$('#action-form').elements.threadId.onchange=()=>{
  setRecommendationBusy(false);
  actionSendId=crypto.randomUUID();const hadDraft=!!activeDraftSession?.draft;markDraftChanged();
  if(actionReviewSeed || actionSuggestion){
    ++actionGeneration;const f=$('#action-form');f.elements.action.readOnly=false;f.elements.reason.readOnly=false;
    $('#send-action').disabled=!f.elements.threadId.value || !!actionReview.workPaused;
    $('#action-status').textContent=actionReview.workPaused?'This project is paused. Resume its queue on the card before sending these fixes.':'Your prompt is preserved. Review the destination and edits before sending.';return;
  }
  if(hadDraft){++actionGeneration;const f=$('#action-form');f.elements.action.readOnly=false;f.elements.reason.readOnly=false;$('#send-action').disabled=!f.elements.threadId.value;$('#recommend-action').disabled=!f.elements.threadId.value;$('#action-status').textContent='Destination changed. Your draft is preserved; ask the agent again if you want a new recommendation.';}
  else generateAction();
};
$('#recommend-action').onclick=generateAction;
$('#action-review').addEventListener('close',()=>{++actionGeneration;setRecommendationBusy(false);});
$('#action-form').onsubmit=async event=>{
  event.preventDefault();const form=event.target,button=$('#send-action');button.disabled=true;++actionGeneration;
  try{
    await flushDraft();
    if(!actionReviewSeed && !form.elements.threadId.value)throw new Error('Choose a Codex chat before sending.');
    const receipt=await request(actionReviewSeed?'/api/codex/send-audit':'/api/codex/send',{requestId:actionSendId,projectId:actionReview.id,...(actionReviewSeed?{}:{threadId:form.elements.threadId.value}),
      action:form.elements.action.value,reason:form.elements.reason.value,instructions:form.elements.instructions.value,preserveActionDraft:!!(actionReviewSeed || actionSuggestion),...(actionReviewSeed?.auditFolders?{auditFolders:actionReviewSeed.auditFolders}:{}),...(actionReviewSeed?.auditSourceKey?{auditSourceKey:actionReviewSeed.auditSourceKey}:{})});
    $('#action-review').close();await openDelivery(receipt);
  }catch(error){notice(error.message);}finally{button.disabled=false;}
};
document.addEventListener('click',async event=>{
  const anchor=event.target.closest('a[href^="codex://threads/"]');if(!anchor)return;
  event.preventDefault();const identity=anchor.getAttribute('href').split('/').at(-1);
  const project=projects.find(p=>p.id===anchor.closest('article')?.dataset.id) || projects.find(p=>p.id===editing) || projects.find(p=>p.chats.some(c=>c.id===identity));
  if(!project)return notice('The linked project could not be found. Refresh and try again.');
  try{await request('/api/codex/open',{projectId:project.id,threadId:identity});notice('Opened the selected chat in Codex.');}
  catch(error){notice(error.message);}
});
$('#check-connections').onclick=async()=>{
  const button=$('#check-connections');button.disabled=true;
  try{const job=await request('/api/codex/check',{});const result=await waitCodexJob(job.id);await load();notice(`${result.verified} local chats verified; ${result.cloud || 0} cloud references; ${result.unavailable.length} need attention.`);}
  catch(error){notice(error.message);}finally{button.disabled=false;}
};
