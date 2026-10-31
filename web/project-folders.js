/* Project records UI; source files retain their original layout. */
(() => {
  const dialog=document.createElement('dialog');dialog.setAttribute('aria-label','Project folders');
  document.body.append(dialog);
  let selected=null, pending=false;
  function element(tag,text){const el=document.createElement(tag);if(text)el.textContent=text;return el;}
  function button(label,callback){const b=element('button',label);b.type='button';b.onclick=callback;return b;}
  function field(label,control){control.setAttribute('aria-label',label);const l=element('label',label);l.append(control);dialog.append(l);return control;}
  async function action(body){
    if(pending)return;pending=true;dialog.querySelectorAll('button').forEach(b=>b.disabled=true);
    try{const result=await request('/api/project/folders',{projectId:selected,...body});await load();return result;}
    catch(err){notice(err.message);throw err;}
    finally{pending=false;dialog.querySelectorAll('button').forEach(b=>b.disabled=false);}
  }
  function open(id){
    selected=id;const p=projects.find(p=>p.id===id);dialog.replaceChildren();
    const heading=element('div');heading.className='dialog-heading';heading.append(element('h2',p.name+' folders'),button('Close',()=>dialog.close()));dialog.append(heading);
    if(!p.recordsRoot){
      dialog.append(element('p','Enable records folders for this project under Desktop/Projects. Application code stays in its existing folder. Existing folders are never overwritten.'));
      dialog.append(button('Enable project folders',async()=>{try{await action({action:'enable'});open(id);}catch{}}));
    } else {
      dialog.append(element('p',p.recordsRoot));
      const select=element('select');select.append(new Option('Whole project',''));
      for(const name of p.features||[])select.append(new Option(name,name));select.value=p.activeFeature||'';
      field('Work folder',select);
      dialog.append(button('Select folder for reviews and ideas',async()=>{try{await action({action:'select',feature:select.value});notice('Work folder selected.');}catch{}}));
      const feature=field('New feature name',element('input'));feature.maxLength=160;
      dialog.append(button('Add feature',async()=>{try{await action({action:'feature',name:feature.value});open(id);}catch{}}));
      const checkout=field('Feature code checkout',element('select'));checkout.append(new Option('Find existing worktrees first',''));
      const checkoutNote=element('p','Feature records stay here; code chats run in the feature checkout. Existing trunk/work gates and project handoffs remain authoritative.');dialog.append(checkoutNote);
      dialog.append(button('Find existing worktrees',async()=>{try{const info=await action({action:'discover'});checkout.replaceChildren(new Option('Choose an existing feature checkout',''));for(const row of info.worktrees||[])if(row.available)checkout.append(new Option((row.branch||'detached')+' — '+row.path,row.path));checkoutNote.textContent=info.managed?'Trunk/work detected. Bind this feature to its work branch; trunk is blocked for feature work.':'Single checkout or non-Git project. Code uses the configured source folder.';}catch{}}));
      dialog.append(button('Bind selected feature to checkout',async()=>{try{await action({action:'bind',feature:select.value,path:checkout.value});notice('Feature checkout saved.');}catch{}}));
      const task=field('What should Codex work on?',element('textarea'));task.rows=4;task.maxLength=3000;
      dialog.append(element('p','Start work opens a fresh dated Codex chat in the verified source checkout and supplies the selected records folder’s latest completed handoff. Wrap up work saves the final handoff and keeps the finished chat available. Resume a paused project before starting new work.'));
      dialog.append(button('Start new chat',async()=>{try{await action({action:'start',feature:select.value,task:task.value,requestId:crypto.randomUUID()});dialog.close();notice('Creating a new dated Codex chat. Check its delivery status on the project.');}catch{}}));
      const idea=field('New idea for the selected folder',element('textarea'));idea.rows=3;idea.maxLength=10000;
      dialog.append(button('Save idea',async()=>{try{await action({action:'select',feature:select.value});await action({action:'idea',text:idea.value});idea.value='';notice('Idea saved.');}catch{}}));
    }
    if(!dialog.open)dialog.showModal();
  }
  function decorate(){
    for(const card of document.querySelectorAll('#projects article[data-id]')){
      if(card.querySelector('.project-folders-button'))continue;
      const b=button('Project folders',event=>{event.stopPropagation();open(card.dataset.id);});b.className='project-folders-button';
      (card.querySelector('.card-organize')||card).append(b);
    }
  }
  new MutationObserver(decorate).observe(document.querySelector('#projects'),{childList:true});decorate();
})();
