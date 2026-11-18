/* Endpoint transport: never substitute portal-host data for an unpaired visitor. */
(()=>{
const originalFetch=window.fetch.bind(window);
const storageName='epm_endpoint_key';
const fragment=new URLSearchParams(location.hash.slice(1));
if(fragment.has('endpoint')){localStorage.setItem(storageName,fragment.get('endpoint'));history.replaceState(null,'',location.pathname+location.search);}
let key=localStorage.getItem(storageName)||'';
const context=originalFetch('/portal/context').then(async response=>{if(response.status===401){location.assign('/login');throw Error('Portal sign-in required');}if(!response.ok)throw Error('Restart the portal to load endpoint connector support.');return response.json();});
const managed=new Set(['/api/status','/api/packages','/api/installation-health','/api/install','/api/uninstall','/api/elevate']);
let connection={connected:false,message:'Checking this PC connector…'};
const jsonResponse=(status,body)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
function headers(extra={}){return {'Content-Type':'application/json','X-Endpoint-Key':key,...extra};}
async function info(){
 const settings=await context;
 if(settings.direct_endpoint&&!key)connection={connected:true,direct:true,message:'Using this PC’s local endpoint engine.'};
 else if(!key)connection={connected:false,message:'Connect this PC to detect its OS and CyberArk agent. The portal host will not be scanned.'};
 else{const response=await originalFetch('/endpoint/info',{headers:headers()});if(!response.ok)throw Error('Endpoint connection unavailable');connection=await response.json();}
 render();
 if(!connection.connected)window.dispatchEvent(new Event('endpoint-disconnected'));
 return connection;
}
function render(){
 const message=document.getElementById('endpoint-connect-message');if(!message)return;
 message.textContent=connection.connected?(connection.direct?connection.message:'Connected to this endpoint: '+connection.hostname):connection.message;
 const download=document.getElementById('endpoint-connect-download');if(download)download.disabled=connection.direct||false;
 const clear=document.getElementById('endpoint-connect-clear');if(clear)clear.hidden=!key;
}
window.endpointBridge={get connected(){return connection.connected;},get paired(){return !!key;},refresh:info};
window.fetch=async(input,options={})=>{
 const url=new URL(typeof input==='string'?input:input.url,location.href);
 if(url.origin!==location.origin)return originalFetch(input,options);
 const settings=await context;
 if(url.pathname==='/api/packages/download'){
  const outgoing=new Headers(options.headers||{});outgoing.set('X-Session',settings.session);
  return originalFetch(input,{...options,headers:outgoing});
 }
 if(!managed.has(url.pathname))return originalFetch(input,options);
 if(settings.direct_endpoint&&!key)return originalFetch(input,options);
 if(url.pathname==='/api/packages'&&location.pathname==='/download-center'&&!key)return originalFetch('/portal/packages');
 if(!key)return jsonResponse(428,{error:'Connect this PC endpoint connector first. No portal-host fallback is allowed.',connector_required:true});
 try{
  const method=(options.method||'GET').toUpperCase();
  const body=options.body?JSON.parse(options.body):null;
  const response=await originalFetch('/endpoint/rpc',{method:'POST',headers:headers({'X-Portal-Session':settings.session}),body:JSON.stringify({method,path:url.pathname,body})});
  const queued=await response.json();
  if(!response.ok)throw Error(queued.error||'This PC connector is offline');
  const deadline=Date.now()+180000;
  while(Date.now()<deadline){
   await new Promise(resolve=>setTimeout(resolve,400));
   const resultResponse=await originalFetch('/endpoint/result/'+queued.request_id,{headers:headers()});
   const result=await resultResponse.json();
   if(!resultResponse.ok)throw Error(result.error||'Endpoint response unavailable');
   if(result.done)return jsonResponse(result.result.status,result.result.body);
  }
  throw Error('Endpoint response timed out. Check its connector and rescan before retrying; the operation may already have started.');
 }catch(error){return jsonResponse(409,{error:error.message,connector_required:true});}
};
document.addEventListener('DOMContentLoaded',()=>{
 const download=document.getElementById('endpoint-connect-download');
 if(download)download.onclick=async()=>{
  download.disabled=true;
  try{
   const settings=await context;
   const response=await originalFetch('/endpoint/bootstrap',{method:'POST',headers:{'Content-Type':'application/json','X-Portal-Session':settings.session},body:'{}'});
   if(!response.ok){const error=await response.json();throw Error(error.error);}
   key=response.headers.get('X-Endpoint-Browser-Key');if(!key)throw Error('Enrollment key not returned');
   localStorage.setItem(storageName,key);
   const blob=await response.blob();const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='endpoint-connector.zip';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);
   connection={connected:false,message:'Extract the kit ON THIS PC, then run Start connector.cmd (Windows) or sh start-connector.sh (macOS/Linux). Python 3.11+ required. Keep the connector console open.'};render();
   window.dispatchEvent(new Event('endpoint-disconnected'));
  }catch(error){connection={connected:false,message:error.message};render();}
  finally{download.disabled=false;}
 };
 const clear=document.getElementById('endpoint-connect-clear');
 if(clear)clear.onclick=()=>{key='';localStorage.removeItem(storageName);connection={connected:false,message:'Endpoint pairing cleared. Run/download the connector on the PC you want to use.'};render();window.dispatchEvent(new Event('endpoint-disconnected'));};
 info().catch(error=>{connection={connected:false,message:error.message};render();});
 setInterval(async()=>{try{const was=connection.connected;await info();if(!was&&connection.connected){window.dispatchEvent(new Event('endpoint-connected'));}}catch(error){connection={connected:false,message:error.message};render();window.dispatchEvent(new Event('endpoint-disconnected'));}},5000);
});
})();
