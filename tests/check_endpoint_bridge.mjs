import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../static/endpoint-bridge.js',import.meta.url),'utf8');
async function scenario({direct=false,key='',path='/installation'}={}){
 const calls=[];const store=new Map(key?[['epm_endpoint_key',key]]:[]);
 const native=async(input,options={})=>{
  const route=String(input);calls.push({route,options});
  const response=body=>new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}});
  if(route==='/portal/context')return response({direct_endpoint:direct,session:'portal-csrf'});
  if(route==='/portal/packages')return response({packages:[],can_install:false,host:{system:'Not connected'}});
  if(route==='/endpoint/rpc'){
   const body=JSON.parse(options.body);assert.equal(body.path,'/api/status');assert.equal(options.headers['X-Endpoint-Key'],key);
   return response({request_id:'request-one'});
  }
  if(route==='/endpoint/result/request-one')return response({done:true,result:{status:200,body:{hostname:'VISITING-VM',agents:[{id:'vm-agent'}]}}});
  if(route==='/api/status'){assert.equal(direct,true,'Portal-host status must never be fetched for a LAN visitor');return response({hostname:'LOCAL-PC'});}
  if(route==='/api/packages/download'){assert.equal(options.headers.get('X-Session'),'portal-csrf');return new Response('synthetic-kit');}
  throw Error('Unexpected native request: '+route);
 };
 const sandbox={fetch:native,Response,Headers,URL,URLSearchParams,Date,Promise,console,
  location:{href:'http://192.168.1.101:8765'+path,origin:'http://192.168.1.101:8765',pathname:path,search:'',hash:'',assign(){}},
  localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
  history:{replaceState(){}},document:{addEventListener(){},getElementById(){return null;}},
  setTimeout:callback=>queueMicrotask(callback),setInterval:()=>0,Event:class{},dispatchEvent(){}};
 sandbox.window=sandbox;vm.runInNewContext(source,sandbox);
 return {sandbox,calls};
}
{
 const {sandbox,calls}=await scenario();const response=await sandbox.fetch('/api/status');
 assert.equal(response.status,428);assert.equal(calls.filter(c=>c.route==='/api/status').length,0);
}
{
 const {sandbox,calls}=await scenario({key:'private-device-capability'});
 const result=await (await sandbox.fetch('/api/status')).json();
 assert.equal(result.hostname,'VISITING-VM');assert.equal(result.agents[0].id,'vm-agent');
 assert.equal(calls.filter(c=>c.route==='/api/status').length,0);
}
{
 const {sandbox}=await scenario({direct:true});
 assert.equal((await (await sandbox.fetch('/api/status')).json()).hostname,'LOCAL-PC');
}
{
 const {sandbox,calls}=await scenario({path:'/download-center'});
 assert.equal((await (await sandbox.fetch('/api/packages')).json()).host.system,'Not connected');
 assert.equal(calls.filter(c=>c.route==='/api/packages').length,0);
}
{
 const {sandbox}=await scenario({key:'private-device-capability'});
 assert.equal(await (await sandbox.fetch('/api/packages/download',{method:'POST',headers:{'X-Session':'endpoint-session'},body:'{}'})).text(),'synthetic-kit');
}
console.log('PASS: browser transport isolates paired endpoint data and never falls back to portal-host status.');

// Exercise the install button itself: OS selection, CSRF, installer filename and pairing storage.
{
 const downloaded=[];const store=new Map();let ready;
 const elements={
  'endpoint-install-platform':{value:''},'endpoint-connect-download':{},
  'endpoint-connect-clear':{},'endpoint-connect-message':{}
 };
 class BrowserURL extends URL {static createObjectURL(){return 'blob:installer';}static revokeObjectURL(){}}
 const native=async(route,options={})=>{
  if(route==='/portal/context')return Response.json({direct_endpoint:false,session:'setup-csrf'});
  if(route==='/endpoint/bootstrap'){
   assert.equal(JSON.parse(options.body).platform,'windows');assert.equal(options.headers['X-Portal-Session'],'setup-csrf');
   return new Response('@echo off',{headers:{'X-Endpoint-Browser-Key':'new-device-key'}});
  }
  if(route==='/endpoint/info')return Response.json({connected:false,message:'Awaiting installer'});
  throw Error('Unexpected install flow request '+route);
 };
 const sandbox={fetch:native,Response,Headers,URL:BrowserURL,URLSearchParams,Date,Promise,console,
  navigator:{userAgentData:{platform:'Windows'}},
  location:{href:'http://192.168.1.101:8765/',origin:'http://192.168.1.101:8765',pathname:'/',search:'',hash:''},history:{replaceState(){}},
  localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
  document:{addEventListener:(name,fn)=>{ready=fn;},getElementById:id=>elements[id]||null,
   createElement:()=>({click(){downloaded.push(this.download);},remove(){}}),body:{append(){}}},
  setTimeout:fn=>queueMicrotask(fn),setInterval:()=>0,Event:class{},dispatchEvent(){}};
 sandbox.window=sandbox;vm.runInNewContext(source,sandbox);ready();
 assert.equal(elements['endpoint-install-platform'].value,'windows');
 await elements['endpoint-connect-download'].onclick();
 assert.deepEqual(downloaded,['Install-connector.cmd']);assert.equal(store.get('epm_endpoint_key'),'new-device-key');
 assert.match(elements['endpoint-connect-message'].textContent,/Setup checks Python/);
}
console.log('PASS: Install connector requests the Windows installer and preserves private endpoint pairing.');
