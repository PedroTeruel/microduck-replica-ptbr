// 出厂场景「写进主程序」的端到端（任务 13）：连本机无头 Edge（CDP），走完标定模式 -> 运动模式。
// 假 robotd 用 --mode commissioning --calib factory 起（出厂未标定）；Studio 由 tests/test_commit_e2e.py 用
// 一个把 studio.helper.calib_commit 换成假实现的启动脚本拉起（电脑上没有 root 小助手）。
//
// --phase factory：出厂状态的准备情况（按钮灰着）、预览能展开、每颗的方向 / 限位 / TOML 都在。
// --phase imu    ：IMU 页粗校：托起摆正采静止 -> 往前低头采前倾 -> 算方向 -> 交给主程序 verify-imu。
// --phase servo  ：舵机页一键中位（--servo-sim），然后交还主程序。
// --phase commit ：第 3 步写进主程序；假小助手让假主程序切 motion + control，清单第 3 步 ✓、顶栏显示运动模式。
// --phase fail   ：假小助手让标定被拒；页面要能看到失败原因，而且断线期间进度卡不能被「断线时不检查」盖掉。
// 结果用 JSON 打到 stdout，由 tests/test_commit_e2e.py 判断。Node >= 22，不需要装包。
import { mkdirSync, writeFileSync } from 'node:fs';
import { createConnection } from 'node:net';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('url');
const CDP = arg('cdp');
const FAKE = Number(arg('fake-port'));
const PHASE = arg('phase', 'factory');
const SHOTS = arg('shots', '');
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => process.stderr.write(`[commit-e2e] ${a.join(' ')}` + '\n');

// 测试控制口：给假 robotd / 假 configd 发 fake.set（同一个假对象）
const fakeSet = (params) => new Promise((resolve, reject) => {
  const s = createConnection({ host: '127.0.0.1', port: FAKE }, () => {
    s.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'fake.set', params }) + '\n');
  });
  let buf = '', done = false;
  const timer = setTimeout(() => { if (!done) { done = true; s.destroy(); reject(new Error('fake.set 超时')); } }, 5000);
  s.on('data', (d) => {
    buf += d;
    const i = buf.indexOf('\n');
    if (i < 0 || done) return;
    done = true; clearTimeout(timer);
    const line = buf.slice(0, i); s.end();
    try {
      const m = JSON.parse(line);
      if (m.error) reject(new Error(JSON.stringify(m.error))); else resolve(m.result);
    } catch (e) { reject(e); }
  });
  s.on('error', (e) => { if (!done) { done = true; clearTimeout(timer); reject(e); } });
});

const page = await (await fetch(`http://127.0.0.1:${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let id = 0;
const waiting = new Map();
const errors = [];
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id).ok(m); waiting.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(m.params.args.map((a) => a.value ?? a.description).join(' '));
});
const send = (method, params = {}) => new Promise((ok, fail) => {
  const i = ++id;
  const timer = setTimeout(() => {
    waiting.delete(i);
    fail(new Error(`CDP ${method} 15 秒没回`));
  }, 15000);
  waiting.set(i, { ok: (m) => { clearTimeout(timer); ok(m); }, fail: (e) => { clearTimeout(timer); fail(e); } });
  ws.send(JSON.stringify({ id: i, method, params }));
});
ws.addEventListener('close', () => {
  for (const w of waiting.values()) w.fail(new Error('Edge 调试连接断了'));
  waiting.clear();
});
ws.addEventListener('error', () => log('CDP WebSocket 出错'));
const js = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(`页面里出错：${r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text}`);
  return r.result?.result?.value;
};
const waitFor = async (expr, what, timeout = 12000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(expr)) return true; await sleep(100); }
  const now = await js(`[location.hash, document.querySelector('[data-step="commit"]')?.innerText?.slice(0, 600), document.querySelector('.onb-h')?.innerText, document.querySelector('.imu-coarse')?.innerText?.slice(0, 400), document.querySelector('.sv-sub')?.innerText].join(' ／ ')`);
  throw new Error(`${timeout / 1000} 秒没等到：${what}。页面上现在：${now}。页面错误：${errors.slice(-4).join(' ｜ ')}`);
};
const shot = async (name) => {
  if (!SHOTS) return;
  const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  writeFileSync(`${SHOTS}/${name}`, Buffer.from(r.result.data, 'base64'));
};
const clickExact = (sel, text) => js(`(() => { const b = [...document.querySelectorAll(${JSON.stringify(sel)})]
  .find((x) => x.textContent.trim() === ${JSON.stringify(text)} && !x.disabled);
  if (!b) return false; b.scrollIntoView({ block: 'center' }); b.click(); return true; })()`);
const clickHas = (sel, text) => js(`(() => { const b = [...document.querySelectorAll(${JSON.stringify(sel)})]
  .find((x) => x.textContent.includes(${JSON.stringify(text)}) && !x.disabled);
  if (!b) return false; b.scrollIntoView({ block: 'center' }); b.click(); return true; })()`);

log('连上 Edge，开始加载页面');
await send('Page.enable');
await send('Runtime.enable');
await send('Page.bringToFront');                                  // 页面要算「在前台」：后台时 Studio 1 Hz 推，清单判成断线
await send('Emulation.setFocusEmulationEnabled', { enabled: true });
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: `${BASE}#/` });
await sleep(800);

log('页面已打开');
const out = { phase: PHASE };
const card = `document.querySelector('[data-step="commit"] .onb-commit')`;
const snapshot = () => js(`(() => {
  const c = ${card};
  if (!c) return null;
  const checks = [...c.querySelectorAll('.onb-checks li')].map((li) => ({
    ok: li.classList.contains('ok'), text: li.innerText.replace(/\\s+/g, ' ').trim() }));
  const act = [...c.querySelectorAll('.onb-commit-acts button')];
  const write = act.find((b) => b.textContent.includes('写进主程序'));
  return {
    rowState: document.querySelector('[data-step="commit"] .onb-mark')?.getAttribute('aria-label'),
    desc: c.querySelector('.onb-commit-desc')?.innerText,
    checks, bad: checks.filter((x) => !x.ok).length,
    writeDisabled: !!(write && write.disabled),
    job: c.querySelector('.onb-commit-job')?.innerText || null,
    msg: c.querySelector('.onb-commit-msg')?.innerText || null,
    msgs: [...c.querySelectorAll('.onb-commit-msg')].map((e) => e.innerText.replace(/\\s+/g, ' ').trim()),
  };
})()`);

if (PHASE === 'imu') {
  log('IMU 页：粗校');
  await js(`location.hash = '#/imu'`);
  await waitFor(`!!document.querySelector('.imu-coarse')`, 'IMU 粗校卡片', 20000);
  out.start = await js(`document.querySelector('.imu-coarse')?.innerText.replace(/\\s+/g, ' ').slice(0, 500)`);
  if (!await clickHas('.imu-coarse button', '采静止')) throw new Error('找不到「采静止」');
  await waitFor(`/静止采到/.test(document.querySelector('.imu-coarse')?.innerText || '')`, '静止采好', 20000);
  await fakeSet({ imu_pose: 'nose_down' });
  await sleep(500);
  if (!await clickHas('.imu-coarse button', '采前倾')) throw new Error('找不到「采前倾」');
  await waitFor(`!!document.querySelector('.imu-coarse input[type=checkbox]') || /交给主程序验证/.test(document.querySelector('.imu-coarse')?.innerText || '')`,
    '粗校算出方向、等确认', 25000);
  await js(`[...document.querySelectorAll('.imu-coarse input[type=checkbox]')].forEach((x) => { if (!x.checked) x.click(); })`);
  await fakeSet({ imu_verify_plan: 'ok' });        // 开发用剧本：主程序先看到摆正，再看到往前低头
  if (!await clickHas('.imu-coarse button', '交给主程序验证')) throw new Error('找不到「交给主程序验证」');
  // 验证成功后主程序里 verified 变成 true，粗校卡会收起：看 IMU 页顶部状态变成「方向已确认」。
  await waitFor(`/方向已确认/.test(document.querySelector('.sv-metrics')?.innerText || '')`,
    'verify-imu 成功', 40000);
  out.imu = await js(`[document.querySelector('.sv-metrics')?.innerText || '',
    document.querySelector('.imu-coarse')?.innerText || ''].filter(Boolean).join(' ／ ').replace(/\\s+/g, ' ').slice(0, 700)`);
  await shot('commit-imu-verified.png');
}

if (PHASE === 'servo') {
  log('舵机页：一键中位，然后交还主程序');
  await js(`location.hash = '#/servos'`);
  await waitFor(`/调舵机中/.test(document.querySelector('.sv-sub')?.innerText || '')`, '舵机页接管（演示舵机）', 20000);
  if (!await clickExact('.sv-page button', '一键校准')) throw new Error('找不到「一键校准」');
  await waitFor(`!!document.querySelector('.sv-modal')`, '中位校准预览', 15000);
  out.planRows = await js(`document.querySelectorAll('.sv-plan tbody tr').length`);
  if (!await clickHas('.sv-modal button', '确认，校准')) throw new Error('找不到「确认，校准」');
  await waitFor(`/校准完：成功 15 颗/.test(document.body.innerText)`, '15 颗中位校好', 40000);
  if (!await clickHas('.sv-handback button', '交还主程序')) throw new Error('找不到「交还主程序」');
  await waitFor(`!!document.querySelector('.sv-handback .two-step-ask')`, '交还二次确认', 5000);
  await sleep(900);
  await js(`document.querySelector('.sv-handback .two-step-ask')?.click()`);
  await waitFor(`!/调舵机中/.test(document.querySelector('.sv-sub')?.innerText || '')`, '交还完成', 30000);
  out.servo = await js(`document.querySelector('.sv-sub')?.innerText.replace(/\\s+/g, ' ')`);
  await shot('commit-servo-done.png');
  await js(`location.hash = '#/'`);
}

if (PHASE === 'commit' || PHASE === 'fail') {
  await js(`location.hash = '#/'`);
  await waitFor(`!!${card}`, '第 3 步「写进主程序」的卡片', 20000);
  await waitFor(`(() => { const c = ${card}; return c && c.querySelectorAll('.onb-checks li').length > 0; })()`, '准备情况清单', 20000);
  await waitFor(`(() => { const c = ${card}; const w = [...c.querySelectorAll('.onb-commit-acts button')]
    .find((b) => b.textContent.includes('写进主程序')); return w && !w.disabled; })()`, '「写进主程序」按钮可点', 25000);
  out.ready = await snapshot();
  const writeBtn = `[...document.querySelectorAll('[data-step="commit"] .onb-commit-acts button')]
    .find((b) => b.textContent.includes('写进主程序'))`;
  await js(`${writeBtn}.click()`);
  await waitFor(`!!document.querySelector('[data-step="commit"] .two-step-ask')`, '二次确认', 5000);
  out.confirmText = await js(`document.querySelector('[data-step="commit"] .two-step-ask')?.textContent`);
  await sleep(900);       // TwoStep 的 700 ms 保护
  await js(`document.querySelector('[data-step="commit"] .two-step-ask').click()`);
  // 写入很快时，回执会被最终结果直接替换（甚至第 3 步已经 ✓、卡片收起）：等到回执、进度卡或完成都行。
  await waitFor(`/已经在写|开始写/.test(document.querySelector('[data-step="commit"] .onb-commit-msg')?.innerText || '') ||
    !!document.querySelector('[data-step="commit"] .onb-commit-job') ||
    document.querySelector('[data-step="commit"] .onb-mark')?.getAttribute('aria-label') === '完成'`,
    '开始写的回执或最终结果', 20000);
  out.started = await snapshot();

  if (PHASE === 'fail') {
    // 假小助手会让假主程序重启一下：断线期间第 3 步的进度卡要单独显示
    let offline = null;
    const end = Date.now() + 25000;
    while (Date.now() < end) {
      const s = await js(`(() => { const c = document.querySelector('[data-step="commit"]'); if (!c) return null;
        return { text: c.innerText.replace(/\\s+/g, ' ').slice(0, 600), job: !!c.querySelector('.onb-commit-job'), msg: c.querySelector('.onb-commit-msg')?.innerText || null }; })()`);
      if (s && s.job && /主程序在重启|断线/.test(s.text)) { offline = s; break; }
      await sleep(200);
    }
    out.offline = offline;
    if (!offline) throw new Error('断线期间没看到第 3 步的进度卡');
    await shot('commit-fail-offline.png');
    await waitFor(`(() => { const m = document.querySelector('[data-step="commit"] .onb-commit-msg.bad');
      return /标定没通过主程序的检查/.test(m?.innerText || ''); })()`, '失败原因', 30000);
    // 回滚要把主程序重新拉成标定模式：等它回来、标定读得到，第 3 步才会从「读不到」变回「该做」。
    await waitFor(`document.querySelector('[data-step="commit"] .onb-mark')?.getAttribute('aria-label') === '该做'`,
      '主程序回来后第 3 步回到该做', 30000);
    out.wsCommit = await js(`(async () => {
      const w = new WebSocket(location.origin.replace('http', 'ws') + '/ws');
      const m = await new Promise((ok) => {
        const t = setTimeout(() => { try { w.close(); } catch (e) {} ok(null); }, 5000);
        w.onmessage = (e) => { const x = JSON.parse(e.data); if (x.t === 'state') { clearTimeout(t); w.close(); ok(x); } };
      });
      return m ? { robotd_ok: m.robotd_ok, posture: m.posture, mode: m.mode, phase: m.phase,
        job: m.commit && m.commit.job, commit_mode: m.commit && m.commit.mode } : null;
    })()`);
    out.failed = await snapshot();
    await shot('commit-fail-reason.png');
  } else {
    await waitFor(`document.querySelector('[data-step="commit"] .onb-mark')?.getAttribute('aria-label') === '完成'`,
      '第 3 步变成完成（假主程序切到运动模式）', 40000);
    await waitFor(`/运动模式/.test(document.querySelector('.topbar .meta')?.innerText || '')`, '顶栏显示运动模式', 15000);
    out.done = await snapshot();
    out.topbar = await js(`document.querySelector('.topbar .meta')?.innerText`);
    await shot('commit-done.png');
  }
}

if (PHASE === 'factory') {
  await waitFor(`!!${card}`, '第 3 步「写进主程序」的卡片', 20000);
  await waitFor(`(() => { const c = ${card}; return c && c.querySelectorAll('.onb-checks li').length > 0; })()`, '准备情况清单', 15000);
  out.factory = await snapshot();
  await shot('commit-factory.png');
  await js(`[...document.querySelectorAll('[data-step="commit"] .onb-commit-acts button')]
    .find((b) => b.textContent.includes('先看看要写什么'))?.click()`);
  await waitFor(`!!document.querySelector('[data-step="commit"] .onb-preview')`, '预览展开', 20000);
  out.preview = await js(`(() => {
    const p = document.querySelector('[data-step="commit"] .onb-preview');
    return { jointRows: p.querySelectorAll('.onb-preview-table tbody tr').length,
      imu: p.querySelector('.onb-preview-imu')?.innerText || '',
      toml: (p.querySelector('pre')?.textContent || '').slice(0, 4000) };
  })()`);
  await shot('commit-preview.png');
}

log('收尾');
out.errors = errors;
process.stdout.write(JSON.stringify(out));
await new Promise((r) => process.stdout.write('', r));
ws.close();
await fetch(`http://127.0.0.1:${CDP}/json/close/${page.id}`);
