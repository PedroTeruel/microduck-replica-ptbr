// WiFi 配网（任务 10b）的端到端：假 configd 写一份 hotspot 的 net.json，Studio 真跑，无头 Edge 打开手机宽度。
// 走一遍：连 WiFi 卡片出现 → 选 Home → 填错密码 → 确认 → 「正在切换」→ last-try 红字「密码不对」。
// 每一步的结果用 JSON 打到 stdout，由 tests/test_wifi_e2e.py 判断。
// 单独跑（先起好假 robotd、Studio、无头 Edge）：
//   node tests/wifi_e2e.mjs --url http://127.0.0.1:18091/ --cdp 9344 [--shots <截图目录>]
// Node >= 22（自带 WebSocket），不需要装任何包。
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('url');
const CDP = arg('cdp');
const SHOTS = arg('shots', '');
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
const waitFor = async (expr, what, timeout = 12000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(expr)) return true; await sleep(100); }
  const now = await js(`[location.hash, document.querySelector('.overview')?.innerText?.slice(0, 800),
    document.querySelector('.wifi-card')?.innerText?.slice(0, 500), document.querySelector('.wifi-last-try')?.innerText,
    document.querySelector('.wifi-msg')?.innerText].join(' ／ ')`);
  throw new Error(`${timeout / 1000} 秒没等到：${what}。页面上现在：${now} ／ 页面报错：${JSON.stringify(errors)}`);
};
const setVal = async (sel, value) => js(`(() => {
  const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return false;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  set.call(e, ${JSON.stringify(value)}); e.dispatchEvent(new Event('input', { bubbles: true })); return e.value;
})()`);
const click = (sel) => js(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return false; e.click(); return true; })()`);
const shot = async (name) => {
  if (!SHOTS) return;
  const r = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(SHOTS, name), Buffer.from(r.result.data, 'base64'));
};

await send('Runtime.enable');
await send('Page.enable');
await send('Page.bringToFront');
await send('Emulation.setFocusEmulationEnabled', { enabled: true });
await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
await send('Page.navigate', { url: 'about:blank' });
await sleep(250);
await send('Page.navigate', { url: `${BASE}#/` });

const out = { errors };
await waitFor(`!!document.querySelector('.wifi-card')`, '总览出现「连 WiFi」卡片', 15000);
await waitFor(`!!document.querySelector('.wifi-net[data-ssid="Home"]')`, '扫描结果里出现 Home');
out.card = await js(`({ text: document.querySelector('.wifi-card').innerText.replace(/\\s+/g, ' '),
  beforeOnboard: !!(document.querySelector('.wifi-card').compareDocumentPosition(document.querySelector('.onb'))
    & Node.DOCUMENT_POSITION_FOLLOWING),
  sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`);
await shot('wifi-card-phone.png');

await click('.wifi-net[data-ssid="Home"] .wifi-net-head');
await waitFor(`!!document.querySelector('.wifi-psk')`, 'Home 展开密码框');
await click('.wifi-net[data-ssid="Home-5G"] .wifi-net-head');
await waitFor(`!!document.querySelector('.wifi-net[data-ssid="Home-5G"] .wifi-psk')`, '已保存的加密网络也展开密码框');
out.expanded = await js(`({ pskType: document.querySelector('.wifi-psk')?.type,
  saved: document.querySelector('.wifi-net[data-ssid="Home-5G"] .wifi-badge')?.textContent,
  savedNote: document.querySelector('.wifi-net[data-ssid="Home-5G"] .wifi-note')?.textContent })`);
await click('.wifi-net[data-ssid="Home-5G"] .wifi-net-head');
await click('.wifi-net[data-ssid="Home"] .wifi-net-head');
await waitFor(`!!document.querySelector('.wifi-net[data-ssid="Home"] .wifi-psk')`, 'Home 重新展开密码框');
await setVal('.wifi-psk', 'wrongpass');
await click('.wifi-net[data-ssid="Home"] .wifi-connect');
await waitFor(`!!document.querySelector('.wifi-confirm')`, '弹出切换确认');
out.confirm = await js(`document.querySelector('.wifi-confirm').innerText.replace(/\\s+/g, ' ')`);
await shot('wifi-confirm-phone.png');

await click('.wifi-confirm .btn-danger');
await waitFor(`/正在切换/.test(document.querySelector('.wifi-switching')?.innerText || '')`, '显示正在切换', 5000);
out.switching = await js(`document.querySelector('.wifi-switching').innerText.replace(/\\s+/g, ' ')`);
await shot('wifi-switching-phone.png');

await waitFor(`/上次连「Home」没成功：密码不对/.test(document.querySelector('.wifi-last-try')?.innerText || '')`, 'last-try 红字', 15000);
out.lastTry = await js(`({ text: document.querySelector('.wifi-last-try').innerText.replace(/\\s+/g, ' '),
  color: getComputedStyle(document.querySelector('.wifi-last-try')).color,
  sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`);
await shot('wifi-last-try-phone.png');

// 手机底栏只有「更多」能到设置：从那里进日志，再点导出诊断包
out.hotspotPasswordHint = await js(`document.querySelector('.wifi-card')?.innerText.includes('热点密码大家都知道')`);
await js(`[...document.querySelectorAll('.tabbar a')].find((a) => a.textContent.trim() === '更多').click()`);
await waitFor(`location.hash === '#/settings' && !!document.querySelector('.password-settings')`, '手机底栏进设置');
out.mobile = await js(`({ navHidden: getComputedStyle(document.querySelector('.nav')).display === 'none',
  hasLogs: !!document.querySelector('.settings-logs'), hasDiag: !!document.querySelector('.settings-diag') })`);
await shot('settings-mobile-links.png');
await click('.settings-logs');
await waitFor(`location.hash === '#/logs' && !!document.querySelector('.logs-export')`, '从设置进日志页');
out.mobile.logs = await js(`document.querySelector('.logs-export')?.textContent`);
await js(`window.__diagHref = ''; document.addEventListener('click', (e) => {
  const a = e.target.closest && e.target.closest('a.logs-export');
  if (a) { e.preventDefault(); window.__diagHref = a.getAttribute('href'); }
}, { capture: true, once: true })`);
await click('.logs-export');
out.mobile.diagClicked = await js('window.__diagHref');

// 设上登录密码后，热点卡片上的灰字提示消失（仍保持这台浏览器登录）
// 两个请求要在页面里发（同源、带这台浏览器的会话），不是在 Node 里
out.passwordSet = await js(`(async () => {
  const sess = await (await fetch('/api/session')).json();
  const r = await fetch('/api/password', { method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF': sess.csrf },
    body: JSON.stringify({ action: 'set', password: 'phone-secret', confirm: 'phone-secret' }) });
  return r.status;
})()`);
await js(`location.hash = '#/'`);
await waitFor(`!!document.querySelector('.wifi-card') && !document.querySelector('.wifi-card').innerText.includes('热点密码大家都知道')`,
  '设密码后热点提示消失', 10000);
out.hotspotPasswordHintAfterSet = await js(`document.querySelector('.wifi-card').innerText.includes('热点密码大家都知道')`);

process.stdout.write(JSON.stringify(out));
ws.close();
await fetch(`http://127.0.0.1:${CDP}/json/close/${page.id}`);
