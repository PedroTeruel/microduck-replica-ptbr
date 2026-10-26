// Isolated local development browser only. All AI requests target a loopback fixture.
import { mkdirSync, writeFileSync } from 'node:fs';
const arg = key => process.argv[process.argv.indexOf(`--${key}`)+1];
const shots = arg('shots'); mkdirSync(shots,{recursive:true});
const page = await (await fetch(`http://127.0.0.1:${arg('cdp')}/json/new?about:blank`,{method:'PUT'})).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(resolve=>ws.addEventListener('open',resolve,{once:true}));
let seq=0;const pending=new Map(),errors=[],report={errors,layouts:[]};
const send=(method,params={})=>new Promise((resolve,reject)=>{
  const id=++seq,timer=setTimeout(()=>{pending.delete(id);reject(Error(`CDP timeout:${method}`));},15000);
  pending.set(id,message=>{clearTimeout(timer);message.error?reject(Error(JSON.stringify(message.error))):resolve(message.result);});
  ws.send(JSON.stringify({id,method,params}));
});
ws.addEventListener('message',event=>{
  const message=JSON.parse(event.data);
  if(pending.has(message.id)){pending.get(message.id)(message);pending.delete(message.id);}
  if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.exception?.description||message.params.exceptionDetails.text);
  if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error'){
    const value=message.params.args.map(a=>a.value||a.description).join(' ');
    // Expected HTTP401 from the fixture is surfaced by the form, not an app exception.
    if(!value.includes('401'))errors.push(value);
  }
});
const js=async expression=>{
  const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
  if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);
  return r.result?.value;
};
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const assert=(value,message)=>{if(!value)throw Error(message);};
const wait=async(expression,label,timeout=18000)=>{
  const end=Date.now()+timeout;
  while(Date.now()<end){if(await js(expression))return;await sleep(80);}
  throw Error(`Timeout:${label}\n${await js("document.querySelector('[data-ai-settings]')?.innerText||document.body.innerText.slice(-4000)")}`);
};
const click=async selector=>{
  await wait(`document.querySelector(${JSON.stringify(selector)})&&!document.querySelector(${JSON.stringify(selector)}).disabled`,selector);
  await js(`document.querySelector(${JSON.stringify(selector)}).click()`);
};
const fill=(label,value)=>js(`(()=>{const e=document.querySelector('[aria-label='+${JSON.stringify(JSON.stringify(label))}+']');e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
const state=()=>js(`fetch('/api/ai').then(r=>r.json())`);
const choose=id=>fill('已保存连接',id);
const save=async name=>{
  await click('[data-ai="save"]');
  await wait(`window.__aiResponses.some(r=>r.saved_id&&r.connections?.some(c=>c.id===r.saved_id&&c.name===${JSON.stringify(name)}))`,'saved connection');
  await wait(`!document.querySelector('[data-ai="new"]').disabled`,'save completed');
};
const snapshot=async name=>{
  await send('Page.bringToFront');
  await js(`new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
  const r=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  writeFileSync(`${shots}/${name}.png`,Buffer.from(r.data,'base64'));
};
try{
  await send('Runtime.enable');await send('Page.enable');
  await send('Emulation.setFocusEmulationEnabled',{enabled:true});
  await send('Page.addScriptToEvaluateOnNewDocument',{source:`
    window.__aiResponses=[];
    {const original=window.fetch;window.fetch=async function(...args){const response=await original.apply(this,args);
      if(String(args[0]).includes('/api/ai')){try{window.__aiResponses.push(await response.clone().json());}catch{}}
      return response;};}
  `});
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:arg('url')});
  await wait(`document.querySelector('[data-ai="new"]')&&!document.querySelector('[data-ai="new"]').disabled`,'AI settings loaded');
  await js(`document.querySelector('[data-ai-settings]').scrollIntoView({block:'start'})`);
  await fill('连接名称','待开通的豆包');
  await save('待开通的豆包');
  let data=await state();const draft=data.connections.find(c=>c.name==='待开通的豆包');
  report.draft_ready_false=draft?.ready===false&&await js(`document.querySelector('[data-ai="test"]').disabled`);
  assert(report.draft_ready_false,'missing account/model/key is honestly a saved draft');
  assert((await (await fetch(`${arg('provider')}/metrics`)).json()).requests.length===0,'saving draft must not contact provider');
  await click('[data-ai="new"]');await fill('连接名称','本地模拟A');
  await fill('提供商','openai_compatible');await fill('Base URL',arg('provider'));
  await fill('Model ID','fake-duck-a');await fill('API Key','fixture-ai-key-A');
  await save('本地模拟A');
  data=await state();const a=data.connections.find(c=>c.name==='本地模拟A');
  assert(a?.ready&&a.key_configured,'complete saved profile must be ready');
  assert(await js(`document.querySelector('[aria-label="API Key"]').value===''`),'save clears Key input');
  await click('[data-ai="select"]');
  await wait(`document.querySelector('[data-ai-current]')?.innerText.includes('本地模拟A')`,'current profile');
  await click('[data-ai="new"]');await fill('连接名称','本地模拟B');
  await fill('提供商','openai_compatible');await fill('Base URL',arg('provider'));
  await fill('Model ID','fake-duck-b');await fill('API Key','fixture-ai-key-B');await save('本地模拟B');
  assert((await (await fetch(`${arg('provider')}/metrics`)).json()).requests.length===0,'save/select do not invoke model');
  await send('Page.reload');
  await wait(`document.querySelector('[aria-label="连接名称"]')?.value==='本地模拟A'`,'selected current survives reload');
  data=await state();report.current_persisted=data.current_id===a.id;
  report.key_hidden_after_reload=await js(`document.querySelector('[aria-label="API Key"]').value===''`);
  assert(report.current_persisted&&report.key_hidden_after_reload,'reload keeps current config without returning Key');
  await click('[data-ai="test"]');
  await wait(`document.querySelector('[data-ai-tested="true"]')?.innerText.includes('模拟回复')`,'real model test result');
  report.test_roundtrip=true;
  await fill('试聊内容','你好小鸭子');await click('[data-ai="send"]');
  await wait(`document.querySelector('[data-ai-history]')?.innerText.includes('模拟回复[fake-duck-a]：你好小鸭子')`,'first model reply');
  report.chat_roundtrip=true;
  await fill('试聊内容','再聊一句');await click('[data-ai="send"]');
  await wait(`document.querySelector('[data-ai-history]')?.innerText.includes('模拟回复[fake-duck-a]：再聊一句')`,'second model reply');
  const captured=(await (await fetch(`${arg('provider')}/metrics`)).json()).requests;
  report.multiturn=captured.some(r=>r.body.messages.length>=3&&r.body.messages.at(-1).content==='再聊一句');
  assert(report.multiturn,'second turn must include real previous conversation');
  await click('[data-ai="clear"]');
  assert(await js(`document.querySelector('[data-ai-history]').innerText.trim()===''`),'clear conversation works');
  await fill('Model ID','long-answer');await save('本地模拟A');
  await fill('试聊内容','长回答');await click('[data-ai="send"]');
  await wait(`document.querySelector('[data-ai-history]')?.innerText.includes('长'.repeat(2501))`,'long provider answer');
  await fill('试聊内容','长回答之后继续聊');await click('[data-ai="send"]');
  await wait(`document.querySelector('[data-ai-history]')?.innerText.includes('模拟回复[long-answer]：长回答之后继续聊')`,'next turn after long answer');
  report.long_reply_multiturn=true;
  await fill('Model ID','reject-auth');await save('本地模拟A');
  await click('[data-ai="test"]');await wait(`document.querySelector('[data-ai-settings] [role="alert"]')`,'provider authentication error');
  report.error_rendered=true;
  await fill('Model ID','echo-key');await save('本地模拟A');await click('[data-ai="test"]');
  await wait(`document.querySelector('[data-ai-tested="true"]')`,'key-echo fixture response handled');
  report.no_secret_in_responses_or_browser_storage=await js(`!JSON.stringify(window.__aiResponses).includes('fixture-ai-key')&&!JSON.stringify({...localStorage,...sessionStorage}).includes('fixture-ai-key')&&!document.querySelector('[data-ai-settings]').innerText.includes('fixture-ai-key')`);
  assert(report.no_secret_in_responses_or_browser_storage,'responses, provider errors and browser storage must not expose Key');
  for(const width of [1440,390,320]){
    await send('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:width<500});
    await js(`document.querySelector('[data-ai-settings]').scrollIntoView({block:'start'})`);await sleep(180);
    assert(await js(`document.documentElement.scrollWidth<=innerWidth+1`),`${width}px overflow`);
    report.layouts.push(width);await snapshot(`ai-${width}`);
  }
  await choose(draft.id);await click('[data-ai="delete"]');
  await wait(`!document.querySelector('[aria-label="已保存连接"]').innerText.includes('待开通的豆包')`,'draft deleted');
  data=await state();report.delete_succeeded=!data.connections.some(c=>c.id===draft.id)&&data.current_id===a.id;
  assert(report.delete_succeeded,'delete one profile must preserve another current profile');
  assert(errors.length===0,errors.join('\n'));
  process.stdout.write(JSON.stringify(report));
}finally{try{await send('Page.close');}catch{}ws.close();}
