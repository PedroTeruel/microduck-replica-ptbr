// Isolated local Edge QA only; all package/controller data are explicit fixtures.
import {mkdirSync,writeFileSync,readFileSync} from 'node:fs';
import net from 'node:net';
const arg=name=>process.argv[process.argv.indexOf(`--${name}`)+1];
const shots=arg('shots');mkdirSync(shots,{recursive:true});
const page=await(await fetch(`http://127.0.0.1:${arg('cdp')}/json/new?about:blank`,{method:'PUT'})).json();
const ws=new WebSocket(page.webSocketDebuggerUrl);
await new Promise(resolve=>ws.addEventListener('open',resolve,{once:true}));
let sequence=0;const pending=new Map(),errors=[],report={errors,layouts:[]};
ws.addEventListener('message',event=>{const r=JSON.parse(event.data);if(r.id){const task=pending.get(r.id);pending.delete(r.id);r.error?task.reject(Error(JSON.stringify(r.error))):task.resolve(r.result);}else if(r.method==='Runtime.exceptionThrown')errors.push(r.params.exceptionDetails.text);});
const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
const js=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result?.value;};
const wait=async(expression,label,timeout=16000)=>{const deadline=Date.now()+timeout;while(Date.now()<deadline){if(await js(expression))return;await new Promise(resolve=>setTimeout(resolve,80));}throw Error(`Timed out: ${label}`);};
const click=async op=>{await wait(`document.querySelector('[data-update="${op}"]')&&!document.querySelector('[data-update="${op}"]').disabled`,`${op} enabled`);await js(`document.querySelector('[data-update="${op}"]').click()`);};
const fixture=values=>new Promise((resolve,reject)=>{const socket=net.createConnection({host:'127.0.0.1',port:Number(arg('fixture-port'))});let data='';socket.on('connect',()=>socket.write(JSON.stringify({op:'fixture',...values})+'\n'));socket.on('data',chunk=>{data+=chunk;if(data.includes('\n')){socket.end();const r=JSON.parse(data.split('\n')[0]);r.ok?resolve(r):reject(Error(JSON.stringify(r)));}});socket.on('error',reject);});
const state=()=>js(`fetch('/api/updates').then(r=>r.json())`);
const settled=async(phase='completed')=>wait(`window.__updates.some(r=>r.job?.phase===${JSON.stringify(phase)}&&!r.busy)`,phase);
const clear=()=>js('window.__updates=[]');
const upload=async(data,name)=>{
  await js(`(()=>{const input=document.querySelector('[aria-label="软件更新包"]');const bytes=Uint8Array.from(atob(${JSON.stringify(data)}),c=>c.charCodeAt(0));const dt=new DataTransfer();dt.items.add(new File([bytes],${JSON.stringify(name)},{type:'application/octet-stream'}));input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
};
try{
  await send('Runtime.enable');await send('Page.enable');
  await send('Page.addScriptToEvaluateOnNewDocument',{source:`window.__updates=[];{const original=window.fetch;window.fetch=async function(...args){const response=await original.apply(this,args);if(String(args[0]).includes('/api/updates')){try{window.__updates.push(await response.clone().json());}catch{}}return response;};}`});
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:arg('url')});
  await wait(`document.querySelector('[data-updates]')&&!document.querySelector('[data-update="check"]').disabled`,'software update card');
  await clear();await click('check');await settled();
  report.no_release=(await state()).source_state==='no_release';
  await fixture({no_release:false,waiting:true});
  await clear();await click('check');await settled();await clear();await click('download');await settled('waiting_validation');
  report.downloaded_waiting=!(await state()).ready&&await js(`document.querySelector('[data-update="install"]').disabled`);
  await fixture({waiting:false});await clear();await click('validate');await settled();
  report.validated=(await state()).ready;
  await clear();await click('install');
  await wait(`window.__updates.some(r=>r.busy&&r.job?.operation==='install')`,'install job active');
  await send('Page.reload');
  await wait(`document.querySelector('[data-updates]')`,'update page reloaded');
  await wait(`window.__updates.some(r=>!r.busy&&r.installed==='2026.10.27')`,'installed after refresh');
  report.installed=(await state()).installed==='2026.10.27';
  report.reloaded_task=(await state()).job?.operation==='install';
  await clear();await click('rollback');await settled();
  report.rollback=(await state()).installed==='2026.10.26';
  await clear();await upload(readFileSync(arg('package')).toString('base64'),'fixture.software-update.tar');await settled();
  report.uploaded=(await state()).ready;
  for(const width of [1440,390,320]){
    await send('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:width<500});
    await js(`window.scrollTo(0,0);new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
    if(await js('document.documentElement.scrollWidth>innerWidth+2'))throw Error(`layout overflows at ${width}`);
    const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});writeFileSync(`${shots}/updates-${width}.png`,Buffer.from(shot.data,'base64'));report.layouts.push(width);
  }
  report.privileged_fields_rejected=await js(`fetch('/api/session').then(r=>r.json()).then(s=>fetch('/api/updates',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF':s.csrf},body:JSON.stringify({op:'download',url:'http://evil.example'})})).then(r=>r.status===400)`);
  await clear();await upload(Buffer.from('not an update archive').toString('base64'),'invalid.tar');
  await wait(`document.querySelector('[data-updates] [role="alert"]')`,'invalid package error');
  report.invalid_package=true;
  if(errors.length)throw Error(errors.join('\n'));
  console.log(JSON.stringify(report));
}finally{ws.close();}
