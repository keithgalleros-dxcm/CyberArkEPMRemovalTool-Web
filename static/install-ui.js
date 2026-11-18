let deploymentState=null, deploymentBusy=false;
function deploymentEnabled(){const button=$('install-start');if(button)button.disabled=deploymentBusy||elevationPending||!deploymentState?.can_install||!deploymentState.elevated||$('install-confirm').value!=='INSTALL'||!$('install-package').value;}
async function loadDeployment(){
 if(!$('install-package')&&!$('package-list'))return;
 try{
  const response=await fetch('/api/packages');const data=await response.json();if(!response.ok)throw Error(data.error);
  deploymentState=data;
  if($('install-host'))$('install-host').textContent=[data.host.system+' · '+data.host.version,'CPU: '+data.host.architecture,(data.host.distro_id?'Distribution: '+data.host.distro_id+' '+data.host.distro_version:''),'Existing agents: '+(data.existing_agents.map(a=>a.name).join(', ')||'None detected')].filter(Boolean).join('\n');
  if($('install-package')){const select=$('install-package');const selected=select.value;select.replaceChildren();for(const kit of data.packages.filter(p=>p.matched)){const option=document.createElement('option');option.value=kit.id;option.textContent=kit.title+' — '+kit.filename;select.append(option);}if(data.packages.some(p=>p.matched&&p.id===selected))select.value=selected;if(!select.options.length){const option=document.createElement('option');option.value='';option.textContent='No compatible complete deployment kit';select.append(option);}$('install-blockers').textContent=data.blockers.length?data.blockers.join('\n'):'Preflight passed. Review the selected installer and request administrator/root access if needed.';$('install-job').textContent=JSON.stringify(data.job,null,2);}
  if($('package-list')){const list=$('package-list');list.replaceChildren();for(const kit of data.packages){const card=document.createElement('article');card.className='card';const title=document.createElement('h2');title.textContent=kit.title;const details=document.createElement('p');details.textContent=kit.filename+' · '+(kit.bytes/1048576).toFixed(1)+' MB';const supported=document.createElement('p');supported.textContent=kit.supported;const label=document.createElement('p');label.className='eyebrow';label.textContent=kit.matched?'MATCHES THIS ENDPOINT':kit.ready?'MANUAL SUPPORT KIT':'MISSING CONFIGURATION OR KEY';const button=document.createElement('button');button.textContent='Download private kit';button.disabled=!kit.ready;button.onclick=()=>downloadDeployment(kit,button);card.append(title,label,details,supported,button);list.append(card);}if(!data.packages.length)list.textContent='No deployment kits found. Keep the private Cyberark Agents folder beside webapp, or configure EPM_AGENT_ROOT. It is intentionally excluded from public GitHub.';}
  deploymentEnabled();
 }catch(error){deploymentState=null;if($('install-blockers'))$('install-blockers').textContent=error.message;if($('download-message'))$('download-message').textContent=error.message;deploymentEnabled();}
}
async function downloadDeployment(kit,button){
 const message=$('download-message');button.disabled=true;
 try{if(!state)await refresh();if(!state)throw Error('Connect to the local console first.');
 message.textContent='Preparing confidential kit. This download contains the installation key and tenant configuration.';
 const response=await fetch('/api/packages/download',{method:'POST',headers:{'Content-Type':'application/json','X-Session':state.session},body:JSON.stringify({package_id:kit.id,confirmation:'DOWNLOAD_KIT'})});
 if(!response.ok){const error=await response.json();throw Error(error.error);}
 const blob=await response.blob();const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='epm-'+kit.id+'-private-kit.zip';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);message.textContent='Kit downloaded. Extract it, keep its files together, and follow INSTALL-README.txt on a supported endpoint. Share only through approved internal channels.';
 }catch(error){message.textContent=error.message;}finally{button.disabled=false;}
}
if($('install-rescan'))$('install-rescan').onclick=async()=>{await refresh();await loadDeployment();};
if($('install-confirm'))$('install-confirm').oninput=deploymentEnabled;
if($('install-start'))$('install-start').onclick=async()=>{
 deploymentBusy=true;deploymentEnabled();
 try{if(!state)await refresh();if(!state)throw Error('Local console unavailable.');
 const response=await fetch('/api/install',{method:'POST',headers:{'Content-Type':'application/json','X-Session':state.session},body:JSON.stringify({package_id:$('install-package').value,hostname:state.hostname,target_platform:state.target_platform,confirmation:$('install-confirm').value})});
 const data=await response.json();if(!response.ok)throw Error(data.error);$('install-confirm').value='';await refresh();await loadDeployment();
 }catch(error){$('install-job').textContent=error.message;}finally{deploymentBusy=false;deploymentEnabled();}
};
loadDeployment();
setInterval(()=>{if(deploymentState?.job.status==='running')loadDeployment();if($('reinstall-status')&&state){$('reinstall-status').textContent=state.job.operation==='uninstall'&&state.job.status==='completed'?(state.job.restart_required?'Removal completed. Restart this endpoint before opening installation.':'Removal verified. Complete any required restart, then open the installation workspace.'):'The installation workspace always rechecks for existing agents before installation.';}deploymentEnabled();},1500);
