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
  throw Error(`Timed out: ${description}\n${await js('document.body.innerText.slice(-7000)')}`);
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
  const image = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  writeFileSync(`${shots}/${name}.png`, Buffer.from(image.data, 'base64'));
};
try {
  await send('Runtime.enable'); await send('Page.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `
    window.__motionRequests=[];
    {const original=WebSocket.prototype.send;WebSocket.prototype.send=function(payload){
      try{const value=JSON.parse(payload);if(value.t==='cmd'&&value.name==='pad.op'&&value.args?.op==='motion')window.__motionRequests.push(value.args);}catch{}
      return original.call(this,payload);
    };}
  ` });
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await fakeSet({ pad_connected: false, posture: 'policy' });
  await send('Page.navigate', { url: arg('url') }); await send('Page.bringToFront');
  await wait(`document.querySelector('#motion-studio')`, 'motion recording panel');
  await js(`document.querySelector('#motion-studio').scrollIntoView({block:'center'})`);
  await wait(`window.__pad?.active`, 'active remote');
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
  assert(errors.length === 0, errors.join('\n'));
  process.stdout.write(JSON.stringify(report));
} finally {
  try { await send('Page.close'); } catch { /* Page may already be closing. */ }
  ws.close();
}
