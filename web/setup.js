let setupStep=0,setupTools={};
function openSetup(tools={}){
  setupTools=tools;setupStep=0;renderSetup();
  document.querySelector('#setup-wizard').showModal();
}
function renderSetup(){
  const content=document.querySelector('#setup-content');
  document.querySelector('#setup-progress').textContent=`Step ${setupStep+1} of 3`;
  document.querySelector('#setup-back').hidden=setupStep===0;
  document.querySelector('#setup-next').textContent=setupStep===2?'Open my desk':'Next';
  document.querySelector('#setup-error').textContent='';
  if(setupStep===0)content.innerHTML='<h3>Your own project desk</h3><p>Start empty and add the projects you want to track. Your project details, chats, and activity are saved on this computer.</p><p>This download contains the app and test fixtures. No personal projects are included, and startup does not import local projects.</p>';
  if(setupStep===1)content.innerHTML=`<h3>What you need</h3><ul><li>Python: running successfully.</li><li>Codex CLI: ${setupTools.codexReady?'found':'optional; install it to use agent and chat features'}.</li><li>GitHub CLI: ${setupTools.githubReady?'found':'optional; install gh to use GitHub features'}.</li></ul><p>Manual project tracking works now. For connected features, sign in to Codex and GitHub separately. Finding a tool does not confirm sign-in.</p>`;
  if(setupStep===2)content.innerHTML='<h3>Choose how to begin</h3><label class="check-label"><input type="radio" name="setup-start" value="empty" checked>Start with an empty desk</label><label class="check-label"><input type="radio" name="setup-start" value="add">Add my first project</label><p>Add a name, type, and next action. A local folder, website URL, and GitHub repository are optional.</p><p>Later, use Refresh Codex index to explicitly import your own saved local index, if available. Getting started reopens this guide.</p><p>If you already have projects, both choices keep them.</p>';
}
document.querySelector('#setup-back').onclick=()=>{setupStep--;renderSetup();};
document.querySelector('#setup-next').onclick=async()=>{
  if(setupStep<2){setupStep++;renderSetup();return;}
  const button=document.querySelector('#setup-next');button.disabled=true;
  try{
    const add=document.querySelector('input[name="setup-start"]:checked').value==='add';
    await request('/api/setup',{});
    document.querySelector('#setup-wizard').close();
    if(add)openEditor(null);
  }catch(error){document.querySelector('#setup-error').textContent=error.message;}
  finally{button.disabled=false;}
};
document.querySelector('#setup-wizard').addEventListener('cancel',event=>event.preventDefault());
document.querySelector('#setup-help').onclick=async()=>{
  try{const data=await request('/api/projects');openSetup(data.setup || {});}catch(error){notice(error.message);}
};
