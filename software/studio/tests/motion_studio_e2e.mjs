import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import net from 'node:net';

const arg = key => process.argv[process.argv.indexOf(`--${key}`) + 1];
const shots = arg('shots'); mkdirSync(shots, { recursive: true });
const page = await (await fetch(`http://127.0.0.1:${arg('cdp')}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener('open', resolve, { once: true }));
let serial = 0; const pending = new Map(), errors = [], report = { errors, layouts: [] };
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++serial, timer = setTimeout(() => { pending.delete(id); reject(Error(`CDP timeout: ${method}`)); }, 12000);
  pending.set(id, message => { clearTimeout(timer); message.error ? reject(Error(JSON.stringify(message.error))) : resolve(message.result); });
  ws.send(JSON.stringify({ id, method, params }));
});
ws.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
  if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
  if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') errors.push(message.params.args.map(a => a.value || a.description).join(' '));
});
const js = async expression => {
  const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const assert = (condition, message) => { if (!condition) throw Error(message); };
const wait = async (expression, description, timeout = 14000) => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await js(expression)) return; await sleep(80); }
  writeFileSync(`${shots}/failure-state.json`, JSON.stringify(await js(`({visibility:document.visibilityState,focus:document.hasFocus(),activity:window.__pad?.active,frames:window.__frames,hbs:window.__hbs,motion:window.__motionRequests?.slice(-12)})`), null, 2));
  throw Error(`Timed out: ${description}\n${await js('document.body.innerText.slice(-7000)')}\nConsole errors: ${JSON.stringify(errors)}`);
};
const click = async selector => {
  await wait(`document.querySelector(${JSON.stringify(selector)}) && !document.querySelector(${JSON.stringify(selector)}).disabled`, selector);
  await js(`document.querySelector(${JSON.stringify(selector)}).click()`);
};
const input = async (selector, value) => js(`(() => {const e=document.querySelector(${JSON.stringify(selector)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
const state = value => wait(`document.querySelector('#motion-studio')?.dataset.state===${JSON.stringify(value)}`, `state ${value}`);
const records = () => readFileSync(arg('record'), 'utf8').split('\n').filter(Boolean).map(line => JSON.parse(line));
const nonzeroHead = r => r.method === 'robot.head' && Object.values(r.params).some(value => typeof value === 'number' && Math.abs(value) > 0.001);
const movingIntent = r => nonzeroHead(r) || (r.method === 'robot.mouth' && r.params.open > 0.001)
  || (['robot.move', 'robot.pose'].includes(r.method) && Object.entries(r.params).some(([key, value]) => key !== 'active' && typeof value === 'number' && Math.abs(value) > 0.001));
const fakeSet = params => new Promise((resolve, reject) => {
  const client = net.connect(Number(arg('fake')), '127.0.0.1', () => client.write(`${JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'fake.set', params })}\n`));
  let text = ''; client.on('error', reject); client.on('data', chunk => { text += chunk; if (text.includes('\n')) { client.end(); resolve(JSON.parse(text)); } });
});
const shot = async name => {
  await send('Page.bringToFront');
  await js(`new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))`);
  const image = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  writeFileSync(`${shots}/${name}.png`, Buffer.from(image.data, 'base64'));
};
try {
  await send('Runtime.enable'); await send('Page.enable');
  // Windows can background a long-running headless Edge tab. Keep this controlled
  // test active; production visibility/heartbeat guards remain unchanged.
  await send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `
    window.__motionRequests=[];window.__frames=[];window.__hbs=[];
    {const original=WebSocket.prototype.send;WebSocket.prototype.send=function(payload){
      try{if(!this.__observed){this.__observed=true;window.__motionSocket=this;this.addEventListener('message',e=>{try{const m=JSON.parse(e.data);window.__frames.push({at:performance.now(),t:m.t,state:m.motion_studio?.state,id:m.id,ok:m.ok});if(window.__frames.length>40)window.__frames.shift();}catch{}});this.addEventListener('close',e=>window.__frames.push({closed:e.code,at:performance.now()}));}
        const value=JSON.parse(payload);if(value.t==='hb'&&window.__dropHeartbeat)return;
        if(value.t==='cmd'&&value.name==='pad.op'&&value.args?.op==='motion')window.__motionRequests.push(value.args);
        if(value.t==='hb'){window.__hbs.push({at:performance.now(),...value});if(window.__hbs.length>10)window.__hbs.shift();}}catch{}
      return original.call(this,payload);
    };}
  ` });
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await fakeSet({ pad_connected: false, posture: 'policy' });
  await send('Page.navigate', { url: arg('url') }); await send('Page.bringToFront');
  await wait(`document.querySelector('#motion-studio')`, 'motion recording panel');
  await js(`document.querySelector('#motion-studio').scrollIntoView({block:'center'})`);
  await wait(`window.__pad?.active`, 'active remote');
  await click('[title="robot.do kick_left"]');
  await wait(`document.querySelector('[data-motion="record_start"]').disabled && document.querySelector('#motion-studio').innerText.includes('上个模型技能')`, 'skill completion barrier');
  await click('.pd-bigs .pd-stopbtn');
  await wait(`document.querySelector('#motion-studio').innerText.includes('已确认策略停下')`, 'runtime stopped while policy config remains enabled');
  assert(await js(`document.querySelector('[data-motion="record_start"]').disabled`), 'stopped policy still cannot record');
  await click('.pd-bigs button:nth-child(2)');
  await wait(`!document.querySelector('[data-motion="record_start"]').disabled && !document.querySelector('[data-motion="idle_start"]').disabled`, 'fresh ready state clears skill barrier');
  report.skill_gate_recovered = true;
  await click('[data-motion="record_start"]'); await state('recording');
  const begin = records().length;
  await click('[data-motion="idle_start"]'); await sleep(900);
  await click('[data-motion="idle_stop"]');
  await click('.pd-sounds button');
  await click('[data-motion="record_pause"]'); await state('record_paused'); await sleep(200);
  await click('[data-motion="record_resume"]'); await state('recording');
  await click('[data-motion="idle_start"]'); await sleep(600); await click('[data-motion="idle_stop"]');
  await click('[data-motion="record_finish"]'); await state('draft');
  report.recorded_head_frames = records().slice(begin).filter(nonzeroHead).length;
  report.recorded_action_frames = records().slice(begin).filter(movingIntent).length;
  assert(report.recorded_action_frames > 3, 'lively recording must issue real head or mouth intents');
  await input('[name="motion-name"]', '展示一号'); await click('[data-motion="save"]');
  await wait(`document.querySelector('#motion-studio').innerText.includes('展示一号')`, 'saved recording');
  await state('idle');
  const playBegin = records().length;
  await click('[data-motion="play"]'); await state('playing'); await sleep(450);
  await click('[data-motion="pause"]'); await state('play_paused'); await sleep(180);
  const pauseBegin = records().length; await sleep(260);
  assert(!records().slice(pauseBegin).some(movingIntent), 'paused replay must not emit moving goals');
  await click('[data-motion="resume"]'); await state('playing'); await sleep(450);
  await click('[data-motion="stop"]'); await state('idle');
  report.replayed_head_frames = records().slice(playBegin).filter(nonzeroHead).length;
  report.replayed_action_frames = records().slice(playBegin).filter(movingIntent).length;
  assert(report.replayed_action_frames > 3, 'playback must issue recorded intents');
  await js(`(() => {const e=document.querySelector('[aria-label="回放次数"]');e.value='3';e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  const repeatedBegin = records().length;
  await click('[data-motion="play"]'); await state('playing');
  await js(`window.__motionLoopChecks=[]`);
  await wait(`(() => {const e=document.querySelector('#motion-studio');const n=Number(e.dataset.loop);if(n&&!window.__motionLoopChecks.includes(n))window.__motionLoopChecks.push(n);return e.dataset.state==='idle';})()`, 'finite playback completion');
  report.loops_seen = await js('window.__motionLoopChecks');
  assert([1, 2, 3].every(value => report.loops_seen.includes(value)), 'all three playback rounds must run');
  report.three_loop_head_frames = records().slice(repeatedBegin).filter(nonzeroHead).length;
  report.three_loop_action_frames = records().slice(repeatedBegin).filter(movingIntent).length;
  // The scheduler drops late continuous samples rather than bursting stale goals.
  assert(report.three_loop_action_frames >= report.recorded_action_frames * 2.5, 'three rounds must produce recorded motion, allowing late-sample coalescing');
  const changes = await js(`window.__motionRequests.filter(x=>['pause','resume','record_pause','record_resume','record_finish','idle_stop'].includes(x.action))`);
  assert(changes.length >= 6 && changes.every(change => typeof change.session_id === 'string' && change.session_id.length > 0),
    'live-session mutations must carry their original session token');
  await click('[data-motion="rename_open"]'); await input('[name="motion-rename"]', '展示改名');
  await click('[data-motion="rename"]');
  await wait(`document.querySelector('#motion-studio').innerText.includes('展示改名')`, 'renamed');
  await send('Page.reload'); await wait(`document.querySelector('#motion-studio')?.innerText.includes('展示改名')`, 'persisted clip after reload');
  await js(`document.querySelector('#motion-studio').scrollIntoView({block:'center'})`);
  await wait(`window.__pad?.active`, 'active again');
  await click('[data-motion="idle_start"]'); await state('idle_motion'); await sleep(250);
  await js(`location.hash='/logs'`); await sleep(900);
  const goneBegin = records().length; await sleep(300);
  assert(!records().slice(goneBegin).some(movingIntent), 'leaving page stops lively output');
  await js(`location.hash='/pad'`); await wait(`window.__pad?.active`, 'remote return'); await state('idle');
  for (const width of [1440, 390, 320]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 1000, deviceScaleFactor: 1, mobile: width < 500 });
    await js(`document.querySelector('#motion-studio').scrollIntoView({block:'center'})`); await sleep(250);
    assert(await js(`document.documentElement.scrollWidth<=innerWidth+1`), `${width}px page overflows horizontally`);
    const rect = await js(`(() => {const r=document.querySelector('#motion-studio').getBoundingClientRect();return {left:r.left,right:r.right};})()`);
    assert(rect.left >= -1 && rect.right <= width + 1, `${width}px motion controls overflow`);
    report.layouts.push(width); await shot(`motion-${width}`);
  }
  await click('[data-motion="delete_open"]'); await click('[data-motion="delete"]');
  await wait(`!document.querySelector('#motion-studio').innerText.includes('展示改名')`, 'delete recording');

  // A clip consisting only of sit/stand must be meaningful and remain one session.
  const postureCalls = () => records().filter(r => r.method === 'robot.do' && r.params?.skill === 'sit_toggle');
  const waitCalls = async count => {
    const end = Date.now() + 8000;
    while (postureCalls().length < count && Date.now() < end) await sleep(50);
    assert(postureCalls().length >= count, 'expected posture command to reach robotd');
  };
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await fakeSet({ posture: 'policy', posture_delay_s: .8 });
  await js(`document.querySelector('#motion-studio').scrollIntoView({block:'center'})`);
  await wait(`window.__pad?.active`, 'active posture recorder');
  await click('[data-motion="record_start"]'); await state('recording');
  const recordPostureBegin = postureCalls().length;
  await click('#pd-remote .pd-bigs button:nth-child(3)');
  await wait(`document.querySelector('#motion-studio').dataset.state==='recording' && document.querySelector('#pd-remote .pd-pose b').innerText==='坐着'`, 'sit remains in recording');
  await wait(`!document.querySelector('[data-motion-posture]')`, 'seated transition confirmed');
  await click('#pd-remote .pd-bigs button:nth-child(1)');
  await wait(`document.querySelector('#motion-studio').dataset.state==='recording' && document.querySelector('#pd-remote .pd-pose b').innerText.includes('准备好走') && !document.querySelector('[data-motion-posture]')`, 'stand remains in recording and finishes');
  await click('[data-motion="record_finish"]'); await state('draft');
  report.recorded_posture_commands = postureCalls().length - recordPostureBegin;
  assert(report.recorded_posture_commands === 2, 'recording sends exactly sit then stand');
  await input('[name="motion-name"]', '坐下再站起'); await click('[data-motion="save"]'); await state('idle');

  const playPostureBegin = postureCalls().length;
  await click('[data-motion="play"]'); await state('playing');
  await js(`window.__postureSeen=[]`);
  await wait(`(() => {const e=document.querySelector('#motion-studio');const p=document.querySelector('#pd-remote .pd-pose b').innerText;if(!window.__postureSeen.includes(p))window.__postureSeen.push(p);return e.dataset.state==='idle';})()`, 'posture replay completion', 45000);
  report.posture_states_seen = await js('window.__postureSeen');
  report.replayed_posture_commands = postureCalls().length - playPostureBegin;
  assert(report.replayed_posture_commands === 2 && report.posture_states_seen.includes('坐着') && report.posture_states_seen.some(p=>p.includes('准备好走')), 'replay must actually sit then stand');

  await js(`(() => {const e=document.querySelector('[aria-label="回放次数"]');e.value='3';e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  const repeatPostureBegin = postureCalls().length;
  await click('[data-motion="play"]'); await state('playing');
  await wait(`document.querySelector('#motion-studio').dataset.state==='idle'`, 'three sit/stand loops complete', 90000);
  report.repeated_posture_commands = postureCalls().length - repeatPostureBegin;
  assert(report.repeated_posture_commands === 6, 'three loops each issue sit and stand exactly once');

  await fakeSet({ posture_delay_s: 2.5 });
  const cancelPostureBegin = postureCalls().length;
  await click('[data-motion="play"]'); await state('playing');
  await waitCalls(cancelPostureBegin + 1);
  await wait(`document.querySelector('[data-motion-posture="sit"]')`, 'visible sit progress');
  await click('[data-motion="stop"]'); await state('idle');
  report.posture_stop_message = await js(`document.querySelector('.motion-result')?.innerText || ''`);
  await sleep(3200);
  report.cancelled_posture_commands = postureCalls().length - cancelPostureBegin;
  assert(report.cancelled_posture_commands === 1, 'stop after sit must never execute later stand');

  await fakeSet({ posture: 'holding' }); await sleep(1400); await fakeSet({ posture: 'policy' });
  await wait(`!document.querySelector('[data-motion="record_start"]').disabled`, 'ready after manual stop/start reset');
  const leavePostureBegin = postureCalls().length;
  await click('[data-motion="play"]'); await state('playing'); await waitCalls(leavePostureBegin + 1);
  await js(`location.hash='/logs'`); await sleep(3800);
  report.disconnected_posture_commands = postureCalls().length - leavePostureBegin;
  assert(report.disconnected_posture_commands === 1, 'navigation during sit cancels subsequent stand');
  await js(`location.hash='/pad'`); await wait(`document.querySelector('#motion-studio')`, 'return to recording library');
  await state('idle');
  report.posture_layouts = [];
  for (const width of [390, 320, 1440]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 1000, deviceScaleFactor: 1, mobile: width < 500 });
    await js(`document.querySelector('#motion-studio').scrollIntoView({block:'center'})`);
    assert(await js(`document.documentElement.scrollWidth<=innerWidth+1`), `${width}px posture feedback overflows`);
    report.posture_layouts.push(width); await shot(`posture-${width}`);
  }
  await fakeSet({posture:'holding'}); await sleep(1300); await fakeSet({posture:'policy'});
  await js(`document.querySelector('#audio-interaction').scrollIntoView({block:'center'})`);
  await wait(`document.querySelector('[data-audio="music"]') && !document.querySelector('[data-audio="music"]').disabled`, 'audio control ready');
  await click('[data-audio="music"]');
  await wait(`document.querySelector('[data-audio-listening="true"]') && document.querySelector('[data-audio-rhythm]')?.innerText==='等待清晰节拍'`, 'microphone waiting for its first stable beat');
  const musicBegin = records().length;
  await click('[data-motion-kind="music"]'); await state('idle_motion');
  await wait(`document.querySelector('#motion-studio .motion-state')?.innerText==='等待稳定节拍'`, 'explicit waiting state before rhythm evidence');
  report.music_waiting_visible = true;
  report.music_waiting_no_motion = !records().slice(musicBegin).some(movingIntent);
  assert(report.music_waiting_no_motion, 'waiting for music must not invent motion');
  await wait(`document.querySelector('[data-audio-rhythm]')?.innerText.includes('120 BPM') && document.querySelector('#motion-studio .motion-state')?.innerText==='随乐律动中'`, 'visible tempo and actual music motion');
  report.music_moving_visible = true;
  await sleep(900);
  const musicFrames = records().slice(musicBegin);
  report.music_head_frames = musicFrames.filter(nonzeroHead).length;
  report.music_body_frames = musicFrames.filter(r=>r.method==='robot.pose' && r.params.active && Math.abs(r.params.roll||0)>.001).length;
  assert(report.music_head_frames>2 && report.music_body_frames>2,'music drives small head/body intents');
  assert(!musicFrames.some(r=>['robot.init','robot.enable'].includes(r.method)),'music never powers or starts policy');
  // The server owns a confirmed standalone music session. Losing focus must
  // not require browser action heartbeats to keep it running.
  const backgroundCommandBegin = await js('window.__motionRequests.length');
  // Simulate suspended/throttled JS heartbeats. Native browser Ping/Pong still
  // operates, so the connection is alive independently of JavaScript timers.
  await js(`window.__dropHeartbeat=true`);
  await js(`window.dispatchEvent(new Event('blur'))`);
  await sleep(900);
  const blurBegin = records().length; await sleep(650);
  report.music_blur_frames = records().slice(blurBegin).filter(nonzeroHead).length;
  assert(report.music_blur_frames>4,'confirmed standalone music continues after blur and heartbeat deadline');
  await js(`window.dispatchEvent(new Event('focus'))`);
  // A real route change unmounts the component and removes the browser robot
  // viewer. Continue past both robotd's 10s linger and the generic 30s JS
  // heartbeat deadline, using real internal state and native protocol liveness.
  await js(`location.hash='/logs'`);
  await sleep(31500);
  const backgroundBegin = records().length; await sleep(900);
  report.music_background_frames = records().slice(backgroundBegin).filter(nonzeroHead).length;
  assert(report.music_background_frames>5,'music survives unmount and >30s JavaScript heartbeat silence');
  report.music_background_action_heartbeats = await js(`window.__motionRequests.slice(${backgroundCommandBegin}).filter(x=>x.action==='heartbeat').length`);
  assert(report.music_background_action_heartbeats===0,'standalone background music does not use browser action heartbeats');
  await js(`window.__dropHeartbeat=false;window.dispatchEvent(new Event('focus'));location.hash='/pad'`);
  await wait(`document.querySelector('#motion-studio')?.dataset.state==='idle_motion'`, 'same background music session on return');
  await js(`document.querySelector('#audio-interaction').scrollIntoView({block:'center'})`);
  await wait(`window.__pad?.active`, 'foreground control restored after background music');
  report.music_background_returned = await js(`document.querySelector('#motion-studio .motion-state')?.innerText==='随乐律动中'`);
  assert(report.music_background_returned,'return shows the current server music session');
  await click('[data-audio="listening"]'); await state('idle'); await sleep(250);
  const musicOff = records().length; await sleep(550);
  report.music_off_stopped = !records().slice(musicOff).some(movingIntent);
  assert(report.music_off_stopped,'microphone off stops subsequent music movement');
  await shot('audio-and-music-1440');
  for (const width of [390,320]) {
    await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:true});
    await js(`document.querySelector('#audio-interaction').scrollIntoView({block:'center'})`);
    assert(await js(`document.documentElement.scrollWidth<=innerWidth+1`),`${width}px audio panel overflows`);
    await sleep(200);
    await shot(`audio-${width}`);
  }
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await js(`document.querySelector('#motion-studio').scrollIntoView({block:'center'})`);
  await wait(`window.__pad?.active`, 'active area before disconnect test');
  await click('[data-audio="music"]');
  await click('[data-motion-kind="music"]'); await state('idle_motion');
  await wait(`document.querySelector('#motion-studio .motion-state')?.innerText==='随乐律动中'`, 'music restarted for real disconnect check');
  await sleep(300);
  await js(`window.__motionSocket.close(1000,'music disconnect check')`);
  await sleep(1300);
  const disconnectedMusic = records().length; await sleep(800);
  report.music_disconnect_stopped = !records().slice(disconnectedMusic).some(movingIntent);
  assert(report.music_disconnect_stopped,'true WebSocket disconnect stops music and reconnect never revives it');
  assert(errors.length === 0, errors.join('\n'));
  process.stdout.write(JSON.stringify(report));
} finally {
  try { await send('Page.close'); } catch { /* Page may already be closing. */ }
  ws.close();
}
