let activeDraftSession=null;
const draftKey=id=>'project-desk-draft:'+id;
function localDraft(id){try{return JSON.parse(localStorage.getItem(draftKey(id)) || 'null');}catch{return null;}}
function draftSnapshot(){const f=$('#action-form');return {threadId:f.elements.threadId.value,action:f.elements.action.value,reason:f.elements.reason.value,instructions:f.elements.instructions.value};}
function markDraftChanged(){
  const session=activeDraftSession;if(!session)return;
  session.draft=draftSnapshot();session.changed++;session.editedAt=Date.now();
  try{localStorage.setItem(draftKey(session.projectId),JSON.stringify({draft:session.draft,revision:session.revision,editedAt:session.editedAt,dirty:true}));session.localSaved=true;}catch{session.localSaved=false;}
  $('#draft-status').textContent='Saving draft…';clearTimeout(session.timer);
  session.timer=setTimeout(()=>flushDraft(session),350);
}
async function flushDraft(session=activeDraftSession){
  if(!session || session.saved===session.changed || session.conflict)return;
  clearTimeout(session.timer);
  if(session.saving){await session.saving;return flushDraft(session);}
  const version=session.changed,draft={...session.draft};
  session.error=false;
  session.saving=(async()=>{
    try{
      const result=await request('/api/drafts',{projectId:session.projectId,expectedRevision:session.revision,draft});
      session.revision=result.revision;session.saved=version;
      try{const backup=localDraft(session.projectId);if(backup && backup.editedAt===session.editedAt)localStorage.setItem(draftKey(session.projectId),JSON.stringify({...backup,revision:result.revision,dirty:session.changed>version}));}catch{}
      if(activeDraftSession===session)$('#draft-status').textContent='Draft saved';
    }catch(error){session.error=true;session.conflict=error.message.includes('another window');if(activeDraftSession===session)$('#draft-status').textContent=session.conflict?error.message:(session.localSaved?'Draft kept locally. Server save failed: ':'Could not save the draft. Keep this window open: ')+error.message;}
    finally{session.saving=null;}
  })();
  await session.saving;
  if(session.saved!==session.changed && !session.conflict && !session.error)return flushDraft(session);
}
async function restoreActionDraft(projectId,generation){
  const previous=activeDraftSession;activeDraftSession=null;
  if(previous)await flushDraft(previous);
  const result=await request('/api/drafts/'+encodeURIComponent(projectId));
  if(generation!==actionGeneration || !$('#action-review').open)return null;
  const backup=localDraft(projectId);
  const useBackup=backup && backup.revision===result.revision && (backup.dirty || backup.editedAt>Date.parse(result.draft?.updatedAt || '1970-01-01'));
  const draft=useBackup?backup.draft:result.draft;
  activeDraftSession={projectId,revision:result.revision,draft,changed:useBackup?1:0,saved:0,editedAt:useBackup?backup.editedAt:Date.now()};
  $('#draft-status').textContent=draft?'Saved draft restored. Nothing has been sent.':'Edits are saved automatically. Nothing is sent until Send to Codex.';
  if(useBackup)flushDraft(activeDraftSession);
  return draft;
}
$('#action-form').addEventListener('input',event=>{if(event.target.name)markDraftChanged();});
$('#action-review').addEventListener('close',()=>flushDraft(activeDraftSession).finally(()=>load().catch(()=>{})));
window.addEventListener('pagehide',()=>flushDraft(activeDraftSession));
$('#discard-draft').onclick=async()=>{
  const session=activeDraftSession;if(!session)return;
  ++actionGeneration;
  await flushDraft(session);
  try{
    const result=await request('/api/drafts',{projectId:session.projectId,expectedRevision:session.revision,draft:null});
    clearTimeout(session.timer);session.revision=result.revision;session.saved=session.changed;session.conflict=false;session.draft=null;
    try{localStorage.removeItem(draftKey(session.projectId));}catch{}
    const f=$('#action-form');f.elements.action.value=actionReview.nextAction || '';f.elements.reason.value=actionReview.nextActionReason || '';f.elements.instructions.value='';
    f.elements.action.readOnly=false;f.elements.reason.readOnly=false;$('#send-action').disabled=!f.elements.threadId.value;$('#recommend-action').disabled=!f.elements.threadId.value;
    updateActionPreview();$('#draft-status').textContent='Draft discarded. Your saved next action is unchanged.';
  }catch(error){$('#draft-status').textContent=error.message;}
};
