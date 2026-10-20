// 电池（battery-plan.md v2 §5、§4）的端到端：连本机无头 Edge（CDP），打开 Studio（假 robotd 回放二号鸭 + 电池剧本，
// Studio 的估算器 20 倍速快进），看总览电池格的各种状态、点开的详情、待办，再到设置页改提醒线 / 红线、
// 「我量了电池电压」、切到台架电源。每一步的结果用 JSON 打到 stdout，由 tests/test_battery_e2e.py 判断。
// 单独跑（先起好假 robotd、Studio（STUDIO_BATTERY_SPEED=20）、无头 Edge）：
//   node tests/battery_e2e.mjs --url http://127.0.0.1:18103/ --cdp 9353 --fake 17056 [--shots <截图目录>]
// Node ≥ 22（自带 WebSocket），不需要装任何包。
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import net from 'node:net';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('url');
const CDP = arg('cdp');
const FAKE = Number(arg('fake'));
const SHOTS = arg('shots', '');
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => process.stderr.write(`[battery-e2e] ${a.join(' ')}\n`);

const fakeSet = (params) => new Promise((resolve, reject) => {
  const s = net.connect(FAKE, '127.0.0.1', () => s.write(`${JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'fake.set', params })}\n`));
  let buf = '';
  s.on('data', (d) => { buf += d; if (buf.includes('\n')) { s.end(); resolve(JSON.parse(buf)); } });
  s.on('error', reject);
});
const studioLogs = async () => ((await (await fetch(`${BASE}api/logs?limit=500`)).json()).items || []).map((e) => e.msg);

// ---------------- CDP ----------------
const page = await (await fetch(`http://127.0.0.1:${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let id = 0;
const waiting = new Map();
const errors = [];
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(m.params.args.map((a) => a.value ?? a.description).join(' '));
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; waiting.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(`页面里出错：${r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text}`);
  return r.result?.result?.value;
};
const cellText = () => js(`(document.querySelector('.bat-cell')?.innerText || '').replace(/\\s+/g, ' ').trim()`);
const waitFor = async (expr, what, timeout = 15000, every = 100) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(expr)) return true; await sleep(every); }
  throw new Error(`${timeout / 1000} 秒没等到：${what}。电池格现在：${await cellText()} ／ 待办：${await js(`document.querySelector('.todo')?.innerText?.replace(/\\s+/g, ' ')`)}`);
};
await send('Runtime.enable');
await send('Page.enable');
let VIEW = { w: 1440, h: 900, mobile: false };
async function setView(w, h, mobile) {
  VIEW = { w, h, mobile };
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: mobile ? 2 : 1, mobile });
  await send('Emulation.setTouchEmulationEnabled', { enabled: !!mobile, maxTouchPoints: mobile ? 5 : 1 });
}
async function open(hash, w = 1440, h = 900, mobile = false) {
  await send('Page.bringToFront');
  await send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await setView(w, h, mobile);
  await send('Page.navigate', { url: `${BASE}${hash}` });
}
// 截图：sels 里几个元素的外接框（详情弹窗是绝对定位的，跟电池格一起框）
async function shot(name, ...sels) {
  if (!SHOTS) return;
  const r = await js(`(() => { const rs = ${JSON.stringify(sels)}.map((s) => document.querySelector(s)).filter(Boolean).map((e) => e.getBoundingClientRect());
    if (!rs.length) return null;
    const l = Math.min(...rs.map((r) => r.left)), t = Math.min(...rs.map((r) => r.top)), R = Math.max(...rs.map((r) => r.right)), B = Math.max(...rs.map((r) => r.bottom));
    return { x: l + scrollX - 8, y: t + scrollY - 8, width: R - l + 16, height: B - t + 16 }; })()`);
  const res = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, ...(r ? { clip: { ...r, scale: 1 } } : {}) });
  writeFileSync(join(SHOTS, name), Buffer.from(res.result.data, 'base64'));
  log('截图', name);
}
const mode = (m) => `document.querySelector('.bat-cell')?.dataset.mode === ${JSON.stringify(m)}`;
const todoText = () => js(`(document.querySelector('.todo')?.innerText || '').replace(/\\s+/g, ' ')`);
// 估算器 20 倍速：读不到 10 秒（真时间 0.5 秒）就重新起步。用它把上一段的「最近 5 分钟」清掉，换一个新电压
async function restart(battery) {
  await fakeSet({ battery: { gone: true } });
  await waitFor(mode('no_data'), '读不到电压', 8000);
  await fakeSet({ battery: { gone: false, sag: 0, ...battery } });
}

const out = { errors, steps: {} };

// ---- 1. 总览：静置 7.62 V ----
await fakeSet({ battery: { v: 7.62, sag: 0, gone: false } });
await open('#/');
await waitFor(`!!document.querySelector('.bat-cell') && !!document.querySelector('.band-cpu')`, '总览出来');
await waitFor(mode('calm'), '电池格出数');
await sleep(400);
out.steps.calm = { text: await cellText(), cls: await js(`document.querySelector('.bat-cell').className`) };
await shot('battery-calm.png', '.band');

// ---- 2. 点开看怎么算的 ----
await js(`document.querySelector('.bat-hit').click()`);
await waitFor(`!!document.querySelector('.bat-pop')`, '详情弹出来');
out.steps.detail = { lines: await js(`[...document.querySelectorAll('.bat-pop li')].map((l) => l.textContent)`),
  expanded: await js(`document.querySelector('.bat-hit').getAttribute('aria-expanded')`) };
await shot('battery-detail.png', '.band', '.bat-pop');
await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
await waitFor(`!document.querySelector('.bat-pop')`, '按 Esc 收起');

// ---- 3. 读不到 → 重新起步「估算中」 ----
await fakeSet({ battery: { gone: true } });
await waitFor(mode('no_data'), '读不到电压', 8000);
out.steps.nodata = { text: await cellText() };
await shot('battery-nodata.png', '.band');
await fakeSet({ battery: { gone: false, v: 7.40 } });
await waitFor(mode('estimating'), '估算中', 8000, 40);
out.steps.estimating = { text: await cellText(), todo: await todoText() };
await shot('battery-estimating.png', '.band');

// ---- 4. 黄：7.40 V（约 28%） ----
await waitFor(`document.querySelector('.bat-cell')?.classList.contains('warn')`, '黄条', 15000);
out.steps.warn = { text: await cellText(), todo: await todoText() };
await shot('battery-warn.png', '.band', '.todo');

// ---- 5. 红：7.15 V（约 9%） ----
await restart({ v: 7.15 });
await waitFor(`document.querySelector('.bat-cell')?.classList.contains('bad') && /电量只剩约/.test(document.querySelector('.todo')?.innerText || '')`, '红线', 15000);
out.steps.red = { text: await cellText(), todo: await todoText() };
await shot('battery-red.png', '.band', '.todo');

// ---- 6. 电压很低：负载把电压拉到 6.8 V 左右 ----
await restart({ v: 7.60 });
await waitFor(mode('calm'), '重新出数');
await fakeSet({ battery: { sag: 0.8 } });
await waitFor(`/电压很低/.test(document.querySelector('.todo')?.innerText || '')`, '电压很低', 15000);
out.steps.lowvolt = { text: await cellText(), todo: await todoText(), badge: await js(`!!document.querySelector('.bat-cell .badge.bad')`) };
await shot('battery-lowvolt.png', '.band', '.todo');
await fakeSet({ battery: { sag: 0 } });

// ---- 7. 手机宽度：电池格 + 详情不出横向滚动 ----
await restart({ v: 7.62 });
await open('#/', 390, 844, true);
await waitFor(mode('calm'), '手机上出数');
await js(`document.querySelector('.bat-hit').click()`);
await waitFor(`!!document.querySelector('.bat-pop')`, '手机上详情弹出来');
out.steps.mobile = await js(`({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
  popRight: Math.round(document.querySelector('.bat-pop').getBoundingClientRect().right) })`);
await shot('battery-mobile.png', '.band', '.bat-pop');

// ---- 8. 设置页：电池一栏 ----
await open('#/settings');
await waitFor(`!!document.querySelector('.bset input[name=bat-preset]')`, '设置页的电池一栏');
await sleep(300);
out.steps.settings = { text: await js(`document.querySelector('.bset').innerText.replace(/\\s+/g, ' ')`) };
await shot('settings-battery.png', '.bset');
const setNum = (label, v) => js(`(() => { const e = document.querySelector('.bset input[aria-label="${label}"]'); e.focus();
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(e, ${JSON.stringify(String(v))});
  e.dispatchEvent(new Event('input', { bubbles: true }));
  e.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); return e.value; })()`);
const clickBtn = (text) => js(`(() => { const b = [...document.querySelectorAll('.bset button')].find((x) => x.textContent.trim().startsWith(${JSON.stringify(text)}));
  if (!b || b.disabled) return false; b.click(); return true; })()`);
const bmsg = () => js(`[...document.querySelectorAll('.bset .msg')].map((e) => e.textContent.replace(/\\s+/g, ' ')).join(' | ')`);
// 不合法：红线 28%（没比提醒线 30% 低 5%）
await setNum('red_pct', 28);
await clickBtn('保存');
await waitFor(`/没存/.test(document.querySelector('.bset').innerText)`, '拒掉不合法的');
out.steps.bad = { msg: await bmsg() };
await setNum('red_pct', 20);
await clickBtn('保存');
await waitFor(`/已保存/.test(document.querySelector('.bset').innerText)`, '存好');
out.steps.saved = { msg: await bmsg(), logs: (await studioLogs()).filter((m) => m.startsWith('电池设置改了')) };
// 我量了电池电压：鸭子卸力静置（假 robotd 一开始就是软着的）
await sleep(2500);
await setNum('万用表读数', 7.80);
await clickBtn('算一下');
await waitFor(`/用这个校准/.test(document.querySelector('.bset').innerText) || /要先卸力/.test(document.querySelector('.bset').innerText)`, '算出校准');
out.steps.calc = { msg: await bmsg(), text: await js(`document.querySelector('.bset').innerText.replace(/\\s+/g, ' ')`) };
await shot('settings-calibrate.png', '.bset');
await clickBtn('用这个校准');
await waitFor(`/已保存/.test(document.querySelector('.bset').innerText) && /校准 \\+0\\.18 V/.test(document.querySelector('.bset').innerText)`, '校准存好', 8000);
out.steps.calibrated = { now: await js(`document.querySelector('.bset .now').textContent`) };

// ---- 9. 台架电源 ----
await js(`document.querySelector('.bset input[value=bench]').click()`);
await sleep(200);
out.steps.benchForm = { text: await js(`document.querySelector('.bset').innerText.replace(/\\s+/g, ' ')`) };
await clickBtn('保存');
await waitFor(`/已保存/.test(document.querySelector('.bset').innerText) && /台架电源（不算电量） · 只显示电压/.test(document.querySelector('.bset .now').textContent)`, '台架电源存好');
await shot('settings-bench.png', '.bset');
await open('#/');
await waitFor(mode('bench'), '总览变成台架电源');
await sleep(400);
out.steps.bench = { text: await cellText(), todo: await todoText() };
// 手机那一步弹出来的详情还开着（换页只换地址，总览一直挂着）：没开才点
await js(`document.querySelector('.bat-pop') || document.querySelector('.bat-hit').click()`);
await waitFor(`!!document.querySelector('.bat-pop')`, '台架电源的详情');
out.steps.bench.lines = await js(`[...document.querySelectorAll('.bat-pop li')].map((l) => l.textContent)`);
await shot('battery-bench.png', '.band', '.bat-pop');
// 收尾：回到 2S 锂电（别把设置留在台架电源）
await open('#/settings');
await waitFor(`!!document.querySelector('.bset input[value="2s_liion"]')`, '设置页');
await js(`document.querySelector('.bset input[value="2s_liion"]').click()`);
await sleep(200);
await clickBtn('保存');
await waitFor(`/已保存/.test(document.querySelector('.bset').innerText)`, '改回 2S 锂电');
out.logs = (await studioLogs()).filter((m) => /电量|电压|电池/.test(m)).slice(-40);

process.stdout.write(JSON.stringify(out));
ws.close();
await fetch(`http://127.0.0.1:${CDP}/json/close/${page.id}`);
