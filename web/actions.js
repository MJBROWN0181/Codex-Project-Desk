let actionReview=null, actionGeneration=0, actionSendId=null,deliveryWatch=0;
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
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
async function generateAction(){
  const form=$('#action-form'),id=form.elements.threadId.value,sequence=++actionGeneration;
  if(!id){
    form.elements.action.readOnly=false;form.elements.reason.readOnly=false;
    $('#send-action').disabled=true;$('#recommend-action').disabled=true;
    $('#action-status').textContent='Choose an existing Codex chat to continue.';return;
  }
  form.elements.action.readOnly=true;form.elements.reason.readOnly=true;$('#send-action').disabled=true;
  $('#recommend-action').disabled=true;$('#action-status').textContent='Codex agent is reviewing recent messages and choosing a next step…';
  try{
    const job=await request('/api/codex/recommend',{projectId:actionReview.id,threadId:id});
    const answer=await waitCodexJob(job.id,null,()=>sequence===actionGeneration && $('#action-review').open);
    if(sequence!==actionGeneration || !$('#action-review').open)return;
    form.elements.action.value=answer.action;form.elements.reason.value=answer.reason;
    updateActionPreview();$('#action-status').textContent='Agent recommendation ready. Review or edit it, add instructions, then send.';
  }catch(error){if(sequence===actionGeneration)$('#action-status').textContent=error.message;}
  finally{if(sequence===actionGeneration){$('#recommend-action').disabled=false;form.elements.action.readOnly=false;form.elements.reason.readOnly=false;$('#send-action').disabled=false;}}
}
async function openActionReview(project){
  actionReview=project;actionSendId=crypto.randomUUID();const openSequence=++actionGeneration;
  const form=$('#action-form');form.reset();
  form.elements.action.readOnly=false;form.elements.reason.readOnly=false;
  form.elements.action.value=project.nextAction || project.suggestion?.text || '';
  form.elements.reason.value=project.nextActionReason || project.suggestion?.reason || '';
  $('#action-project').textContent=project.name;$('#action-status').textContent='Checking available Codex chats…';
  form.elements.threadId.innerHTML='<option value="">Loading chats…</option>';
  $('#send-action').disabled=true;$('#recommend-action').disabled=true;updateActionPreview();$('#action-review').showModal();
  try{
    const result=await request('/api/codex/threads');
    if(openSequence!==actionGeneration || !$('#action-review').open)return;
    const all=new Map(result.chats.map(c=>[c.id,c]));
    const normalized=value=>(value || '').replace(/[\\/]+/g,'/').replace(/\/$/,'').toLowerCase();
    const linked=project.chats.filter(c=>all.has(c.id));
    const matching=project.path?result.chats.filter(c=>normalized(c.cwd)===normalized(project.path)):[];
    const ordered=[...linked.map(c=>all.get(c.id)),...result.chats.filter(c=>!linked.some(l=>l.id===c.id))];
    form.elements.threadId.innerHTML='<option value="">Choose a Codex chat</option>'+ordered.map(c=>`<option value="${escapeHtml(c.id)}">${escapeHtml(c.title)}${linked.some(l=>l.id===c.id)?' (linked to this project)':''}</option>`).join('');
    const preferred=all.has(project.preferredChatId)?project.preferredChatId:(linked[0]?.id || matching[0]?.id);
    if(preferred)form.elements.threadId.value=preferred;
    $('#send-action').disabled=false;$('#recommend-action').disabled=false;
    if(preferred)generateAction();else $('#action-status').textContent='Choose the existing Codex chat that should handle this project. A recommendation will be generated for that chat.';
  }catch(error){if(openSequence===actionGeneration)$('#action-status').textContent=error.message;}
}
function showReceipt(receipt){
  $('#delivery-title').textContent=deliveryLabel(receipt);
  $('#delivery-chat').textContent=receipt.title || 'Selected Codex chat';
  $('#delivery-note').textContent=receipt.error || receipt.note || (receipt.status==='received'?'Your reviewed message appears in the destination chat. Work completion is tracked separately.':'Your message is queued for the selected chat. Waiting for confirmation in chat history.');
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
$('#action-form').elements.threadId.onchange=()=>{actionSendId=crypto.randomUUID();generateAction();};
$('#recommend-action').onclick=generateAction;
$('#action-review').addEventListener('close',()=>{++actionGeneration;});
$('#action-form').onsubmit=async event=>{
  event.preventDefault();const form=event.target,button=$('#send-action');button.disabled=true;++actionGeneration;
  try{
    const receipt=await request('/api/codex/send',{requestId:actionSendId,projectId:actionReview.id,threadId:form.elements.threadId.value,
      action:form.elements.action.value,reason:form.elements.reason.value,instructions:form.elements.instructions.value});
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
