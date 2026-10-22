// CDP browser test against the test-only runtime in test_models_e2e.py. No motion commands.
import { mkdirSync, writeFileSync } from 'node:fs';
const arg = key => process.argv[process.argv.indexOf(`--${key}`) + 1];
const base = arg('url'), shots = arg('shots');
if (shots) mkdirSync(shots, { recursive: true });
const target = await (await fetch(`http://127.0.0.1:${arg('cdp')}/json/new?about:blank`, { method: 'PUT' })).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(resolve => socket.addEventListener('open', resolve, { once: true }));
let seq = 0;
const pending = new Map(), errors = [];
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq;
  const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
  pending.set(id, message => { clearTimeout(timer); message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result); });
  socket.send(JSON.stringify({ id, method, params }));
});
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) { pending.get(message.id)(message); pending.delete(message.id); }
  if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
  if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') errors.push(message.params.args.map(arg => arg.value || arg.description).join(' '));
});
const js = async expression => {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result?.value;
};
const wait = async (expression, what, timeout = 15000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await js(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Timeout: ${what}\n${await js("document.querySelector('.models-page')?.innerText?.slice(0,3000) || document.body.innerText.slice(0,2000)")}`);
};
const assert = (value, message) => { if (!value) throw new Error(message); };
const click = async selector => {
  await wait(`!!document.querySelector(${JSON.stringify(selector)}) && !document.querySelector(${JSON.stringify(selector)}).disabled`, `enabled ${selector}`);
  await js(`document.querySelector(${JSON.stringify(selector)}).click()`);
};
const fill = (selector, value) => js(`(() => { const el=document.querySelector(${JSON.stringify(selector)}); el.value=${JSON.stringify(value)}; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); })()`);
const chooseFile = async path => {
  const { root } = await send('DOM.getDocument');
  const { nodeId } = await send('DOM.querySelector', { nodeId: root.nodeId, selector: 'input[aria-label="导入模型包"]' });
  await send('DOM.setFileInputFiles', { nodeId, files: [path] });
};
const done = () => wait(`!document.querySelector('.models-page[aria-busy="true"]')`, 'operation complete', 30000);
const confirm = async () => {
  await click('.models-confirm button:last-child');
  await done();
};
const screenshot = async name => {
  if (!shots) return;
  const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  writeFileSync(`${shots}/${name}.png`, Buffer.from(result.data, 'base64'));
};
try {
  await send('Page.enable'); await send('Runtime.enable'); await send('DOM.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `(() => {
    const Original=window.WebSocket; window.__modelWs=[]; window.__modelSent=[];
    window.WebSocket=class extends Original {
      constructor(...args) { super(...args); window.__modelWs.push(this); }
      send(value) { try { window.__modelSent.push(JSON.parse(value)); } catch {} return super.send(value); }
    };
  })();` });
  await send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: `${base}#/models` });
  await wait(`document.querySelectorAll('.models-item').length >= 7`, 'default model library', 30000);
  await done();
  assert(await js(`document.querySelectorAll('[data-model-id^="builtin"] [data-model-action="delete"]').length === 0`), 'builtin deletion must not be offered');
  await chooseFile(arg('invalid'));
  await click('button[aria-label="导入模型"]');
  await wait(`document.querySelector('.models-page [role="alert"]')?.innerText?.length > 0`, 'invalid archive error');
  await done();
  assert(await js(`![...document.querySelectorAll('.models-item')].some(e=>e.dataset.modelName==='浏览器训练模型')`), 'invalid archive must not install');
  await chooseFile(arg('package'));
  await fill('input[aria-label="模型名称"]', '浏览器训练模型');
  await click('button[aria-label="导入模型"]');
  await wait(`!!document.querySelector('[data-model-name="浏览器训练模型"]')`, 'imported model');
  await done();
  assert(await js(`!document.querySelector('[data-model-name="浏览器训练模型"]').innerText.includes('当前选用')`), 'install must not select');
  await click('button[aria-label="重命名 浏览器训练模型"]');
  await fill('input[aria-label="模型名称 浏览器训练模型"]', '慢走模型');
  await js(`document.querySelector('.models-rename').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))`);
  await wait(`!!document.querySelector('[data-model-name="慢走模型"]')`, 'renamed model'); await done();
  await click('button[aria-label="使用 慢走模型"]');
  await wait(`document.querySelector('[data-model-name="慢走模型"]')?.innerText.includes('当前选用')`, 'runtime confirmed selection'); await done();
  assert(await js(`document.querySelector('button[aria-label="删除 慢走模型"]').disabled`), 'referenced model deletion must be disabled');
  assert(await js(`!document.querySelector('[data-model-name="慢走模型"]').innerText.includes('正在执行')`), 'selected idle model is not running');
  await screenshot('models-desktop');

  // Read-only physical-key capture: inject input snapshots, never a drive/skill command.
  await wait(`document.querySelector('.models-page')?.dataset.captureReady==='true'`, 'stable safe bindings');
  await click('button[aria-label="设置按键 前滚翻"]');
  await wait(`!!document.querySelector('.models-capture')`, 'physical key capture');
  await wait(`window.__modelSent.filter(m=>m.t==='hb').at(-1)?.pad_visible===true`, 'capture listener ready');
  await js(`(() => { const s=window.__modelWs.find(s=>s.url.endsWith('/ws'));
    for (const buttons of [{},{south:true}]) s.onmessage({data:JSON.stringify({t:'pad',live:{state:'attached',last_ms:0,buttons}})});
  })()`);
  await wait(`!!document.querySelector('.models-confirm')`, 'captured key conflict');
  await click('.models-confirm button:first-child');
  await wait(`!document.querySelector('.models-confirm')`, 'cancel replacement');
  await wait(`window.__modelSent.some(m=>m.t==='hb' && m.pad_visible===true) && window.__modelSent.filter(m=>m.t==='hb').at(-1).pad_visible===false`, 'capture subscription released');
  const beforeBind = await js(`fetch('/api/models').then(r=>r.json())`);
  assert(beforeBind.data.bindings.find(b=>b.button==='a').slot==='ground_pick', 'cancelled capture must not change binding');
  assert(await js(`window.__modelSent.filter(m=>m.t==='cmd').every(m=>m.name==='pad.op' && m.args.op==='watch')`), 'key capture must only request read-only pad snapshots');

  await fill('select[aria-label="绑定动作 A"]', 'roulade');
  await click('button[aria-label="设置按键 A"]');
  await wait(`document.querySelector('.models-confirm')?.innerText.includes('替换绑定')`, 'key conflict confirmation');
  assert(await js(`document.querySelector('.models-confirm').innerText.includes('现在：')`), 'conflict must identify old binding');
  await confirm();
  await wait(`document.querySelector('[data-button="a"] .models-binding-current').innerText.includes('前滚翻')`, 'binding readback');
  await click('button[aria-label="取消绑定 A"]'); await done();
  await wait(`document.querySelector('[data-button="a"] .models-binding-current').innerText.includes('未绑定')`, 'clear binding');
  await click('button[aria-label="恢复默认按键"]'); await confirm();
  await wait(`document.querySelector('[data-button="a"] .models-binding-current').innerText.includes('低头捡东西')`, 'default binding restored');

  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await js('window.scrollTo(0,0)');
  await new Promise(resolve => setTimeout(resolve, 250));
  const mobileFits = await js('document.documentElement.scrollWidth <= innerWidth + 1');
  await screenshot('models-mobile');
  assert(mobileFits, 'mobile page must fit width without horizontal overflow');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await click('[data-slot="walk"] [data-model-action="restore"]'); await confirm();
  await wait(`!document.querySelector('[data-model-name="慢走模型"]').innerText.includes('当前选用')`, 'restored model default');
  await click('button[aria-label="删除 慢走模型"]'); await confirm();
  await wait(`!document.querySelector('[data-model-name="慢走模型"]')`, 'imported model deleted');
  // Navigation/reload must read persisted metadata rather than retain stale optimistic rows.
  await send('Page.reload');
  await wait(`document.querySelectorAll('.models-item').length >= 7`, 'library after reload', 30000);
  const data = await js(`fetch('/api/models').then(r=>r.json())`);
  process.stdout.write(JSON.stringify({ errors, mobileFits, importedAfterDelete: data.data.items.filter(i=>i.source==='imported').length }));
} finally {
  socket.close();
}
