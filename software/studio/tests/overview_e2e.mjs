// Teste de ponta a ponta da reorganização da visão geral (overview-merge-plan.md §5 e revisão O1–O18), usando o Edge sem interface (CDP).
// Abre a visão geral do Studio com dados simulados e verifica temperatura da placa, lista inicial e área do controle.
// Também testa navegação e rolagem com o analógico pressionado, a roda sobre o palco e gestos no celular; registra o que o robotd simulado recebeu.
// Os resultados são enviados como JSON para stdout e validados por tests/test_overview_e2e.py.
//
// --phase main executa o cenário principal; --phase done reinicia o Studio com as seis etapas registradas e confere a lista recolhida.
// Execução manual: inicie primeiro o robotd simulado, o Studio e o Edge sem interface; use portas livres.
//   node tests/overview_e2e.mjs --url http://127.0.0.1:18090/ --cdp 9343 --record <rd.jsonl> --fake 17022 --phase main [--shots <diretório de capturas>]
// Requer Node ≥ 22, que já inclui WebSocket; não precisa instalar pacotes.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import net from 'node:net';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('url');                 // http://127.0.0.1:porta/
const CDP = arg('cdp');
const REC = arg('record');
const FAKE = Number(arg('fake'));
const PHASE = arg('phase', 'main');
const SHOTS = arg('shots', '');
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => process.stderr.write(`[overview-e2e] ${a.join(' ')}\n`);

// ---------------- Registros do robotd simulado (somente comandos de movimento e som) ----------------
const POLL = new Set(['hello', 'robot.health', 'robot.busStatus', 'robot.policies', 'robot.busCommand', 'pad.status', 'system.info',
  'robot.subscribe', 'pad.bindings', 'fake.set']);
const recs = () => readFileSync(REC, 'utf-8').split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((r) => !POLL.has(r.method));
let mark = 0;
const since = () => { const all = recs(); const out = all.slice(mark); mark = all.length; return out.map(({ method, params, notify }) => ({ method, params, notify })); };
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
const dialogs = [];                  // Diálogos do navegador (sair da página dos servos não deve pedir confirmação)
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(m.params.args.map((a) => a.value ?? a.description).join(' '));
  if (m.method === 'Page.javascriptDialogOpening') { dialogs.push(m.params.message); send('Page.handleJavaScriptDialog', { accept: true }); }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; waiting.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(`Erro na página: ${r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text}`);
  return r.result?.result?.value;
};
const waitFor = async (expr, what, timeout = 8000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(expr)) return true; await sleep(100); }
  const now = await js(`[location.hash, scrollY, window.__pad && __pad.active, document.querySelector('.onb')?.innerText?.slice(0, 300),
    document.querySelector('.band')?.innerText?.replace(/\\s+/g, ' ')].join(' ／ ')`);
  throw new Error(`Tempo limite de ${timeout / 1000} s aguardando ${what}. Estado atual da página: ${now}`);
};
const box = (sel, scroll = true) => js(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null;
  ${scroll ? "e.scrollIntoView({ block: 'center', inline: 'nearest' });" : ''} const r = e.getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height, l: r.x, t: r.y }; })()`);
const key = (r) => `.pd-svg-live [data-role="${r}"]`;
const mouse = (type, x, y, buttons = 1, extra = {}) => send('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons, clickCount: 1, ...extra });
const touch = (type, pts) => send('Input.dispatchTouchEvent', { type, touchPoints: pts });
const sw = () => js(`({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`);
let VIEW = { w: 1440, h: 900, mobile: false };

async function setView(w, h, mobile) {
  VIEW = { w, h, mobile };
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: mobile ? 2 : 1, mobile });
  await send('Emulation.setTouchEmulationEnabled', { enabled: !!mobile, maxTouchPoints: mobile ? 5 : 1 });
}
async function open(hash, w, h, mobile) {
  // Uma nova aba do Edge sem interface pode ser considerada em segundo plano: traga-a para frente e simule o foco.
  await send('Page.bringToFront');
  await send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await setView(w, h, mobile);
  await send('Page.navigate', { url: 'about:blank' });
  await sleep(300);
  await send('Page.navigate', { url: `${BASE}${hash}` });
  await waitFor(`!!document.querySelector('.onb') && !!document.querySelector('#pad-block') && !!document.querySelector('.band-cpu')`, 'visão geral carregada');
  await waitFor(`/Ação de Start:|Controle físico conectado/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'estado do controle recebido');
  await sleep(800);
}
// Capturas: full inclui a página inteira; sel captura um elemento específico.
async function shot(name, sel) {
  if (!SHOTS) return;
  let clip;
  if (sel === 'full') {
    const orig = { ...VIEW };
    await js('window.scrollTo(0, 0)');
    await sleep(200);
    const h = await js('Math.ceil(document.documentElement.scrollHeight)');
    await setView(orig.w, h, orig.mobile);
    await sleep(900);                                 // Aguarda a renderização do pato 3D.
    const r = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(SHOTS, name), Buffer.from(r.result.data, 'base64'));
    await setView(orig.w, orig.h, orig.mobile);
    await sleep(300);
    log('captura', name);
    return;
  }
  if (sel) {
    const r = await js(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); const r = e.getBoundingClientRect();
      return { x: r.x + scrollX - 8, y: r.y + scrollY - 8, width: r.width + 16, height: r.height + 16 }; })()`);
    clip = { ...r, scale: 1 };
  }
  const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: !!clip, ...(clip ? { clip } : {}) });
  writeFileSync(join(SHOTS, name), Buffer.from(r.result.data, 'base64'));
  log('captura', name);
}
const moves = (rs) => rs.filter((r) => r.method === 'robot.move').map((r) => r.params);
const nonzero = (p) => Object.values(p).some((v) => typeof v === 'number' && Math.abs(v) > 1e-6);
const onbMarks = () => js(`[...document.querySelectorAll('.onb-row')].map((r) => r.querySelector('.onb-mark').textContent.trim())`);

// Para a revisão C7, atrasa 300 ms as respostas result do Studio e registra pad.op para simular Wi-Fi lento.
// O wrapper apenas observa o WebSocket; as mensagens do Studio permanecem iguais.
const INJECT = `(() => {
  const NWS = window.WebSocket;
  window.__sentOps = [];
  window.__delayResults = 0;
  class W extends NWS {
    send(d) {
      try { const m = JSON.parse(d); if (m.t === 'cmd' && m.name === 'pad.op') window.__sentOps.push({ at: performance.now(), op: m.args && m.args.op }); } catch (e) { /* Ignora mensagens que não são JSON. */ }
      return super.send(d);
    }
    set onmessage(fn) {
      super.onmessage = (ev) => {
        const d = ev.data;
        if (window.__delayResults && typeof d === 'string' && d.startsWith('{"t":"result"')) { setTimeout(() => fn({ data: d }), window.__delayResults); return; }
        fn(ev);
      };
    }
    get onmessage() { return super.onmessage; }
  }
  window.WebSocket = W;
})();`;
await send('Runtime.enable');
await send('Page.enable');
await send('Page.addScriptToEvaluateOnNewDocument', { source: INJECT });
const out = { phase: PHASE, errors, steps: {} };

if (PHASE === 'done') {
  // Reinicia o Studio com cinco etapas registradas (IMU ignorada) e controle físico conectado pelo configd simulado.
  await open('#/', 1440, 900, false);
  await js(`localStorage.removeItem('studio.onb.open')`);      // O perfil do Edge pode conter dados anteriores; comece com a lista recolhida.
  await open('#/', 1440, 900, false);
  await waitFor(`!!document.querySelector('.onb-done')`, 'lista recolhida em uma linha', 10000);
  out.done = await js(`document.querySelector('.onb-done').innerText.replace(/\\s+/g, ' ')`);
  await shot('onb-all-done.png', '.onb');
  await shot('skip-all-done-collapsed.png', '.onb');
  await js('window.scrollTo(0, 0)');
  await sleep(300);
  await shot('desktop-1440-all-done-viewport.png');
  // A linha recolhida pode ser expandida; confira as seis etapas, recolha novamente e verifique a persistência em localStorage.
  await js(`document.querySelector('.onb-done .onb-fold').click()`);
  await waitFor(`document.querySelectorAll('.onb-row').length === 6`, 'seis etapas expandidas');
  out.expanded = await js(`({ rows: document.querySelectorAll('.onb-row').length,
    redo: document.querySelectorAll('.onb-row.onb-ok .onb-redo').length, skip: document.querySelectorAll('.onb-row.onb-skip').length,
    head: document.querySelector('.onb-fold-h')?.innerText.replace(/\\s+/g, ' ') })`);
  await shot('skip-all-done-expanded.png', '.onb');
  await open('#/', 1440, 900, false);                           // Após atualizar, a lista continua expandida.
  out.expandedAfterReload = await js(`document.querySelectorAll('.onb-row').length`);
  await js(`document.querySelector('.onb-fold-h').click()`);
  await waitFor(`!!document.querySelector('.onb-done')`, 'lista recolhida');
  await open('#/', 1440, 900, false);
  out.collapsedAfterReload = await js(`!!document.querySelector('.onb-done') && document.querySelectorAll('.onb-row').length === 0`);
} else {
  // ================= Computador com 1440 px =================
  await open('#/', 1440, 900, false);
  out.desk = await js(`({ cells: document.querySelectorAll('.band > *').length, padActive: __pad.active,
    rows: document.querySelectorAll('.onb-row').length, now: document.querySelector('.onb-now .onb-title b')?.textContent,
    cpu: document.querySelector('.band-cpu').innerText.replace(/\\s+/g, ' '), nav: document.querySelector('.nav [aria-current]')?.textContent })`);
  out.desk.marks = await onbMarks();
  await shot('desktop-1440-full.png', 'full');
  await shot('onb-incomplete.png', '.onb');

  // A roda do mouse sobre o palco deve rolar a página, sem ampliar o 3D (revisão O2).
  await js('window.scrollTo(0, 0)');
  await sleep(200);
  const st = await box('.stage', false);
  await mouse('mouseMoved', st.x, st.y, 0);
  await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: st.x, y: st.y, deltaX: 0, deltaY: 400 });
  await sleep(500);
  out.wheel = await js('scrollY');

  // #/pad ancora a área do controle sob a barra fixa e destaca Controle na navegação (revisão O13).
  await js(`location.hash = '#/pad'`);
  await waitFor(`__pad.active`, '#/pad ativou a área do controle');
  await sleep(400);
  out.padNav = await js(`({ top: Math.round(document.getElementById('pad-block').getBoundingClientRect().top), active: __pad.active,
    nav: document.querySelector('.nav [aria-current]')?.textContent, topbar: Math.round(document.querySelector('.topbar').getBoundingClientRect().top),
    band: [Math.round(document.querySelector('.overview > .band').getBoundingClientRect().top), Math.round(document.querySelector('.overview > .band').getBoundingClientRect().bottom)],
    navTop: Math.round(document.querySelector('.nav').getBoundingClientRect().top) })`);
  await shot('pad-block-desktop.png');

  // Ao navegar com o analógico pressionado, pare imediatamente e envie drive off (revisão O1).
  const offs = async (why) => (await studioLogs()).filter((m) => m.includes(`Saiu da área do controle：${why}`)).length;
  const logs0 = await offs('Navegou para outra página (#/logs)');
  since();
  let b = await box(key('ls'));
  await mouse('mouseMoved', b.x, b.y, 0);
  await mouse('mousePressed', b.x, b.y);
  for (let i = 1; i <= 5; i++) { await mouse('mouseMoved', b.x, b.y - 8 * i); await sleep(20); }
  await sleep(400);
  const before = since();
  await js(`location.hash = '#/logs'`);
  await sleep(300);
  const atLeave = since();
  for (let i = 1; i <= 4; i++) { await mouse('mouseMoved', b.x + 3 * i, b.y - 45); await sleep(60); }
  await sleep(400);
  const after = since();
  await mouse('mouseReleased', b.x, b.y - 45, 0);
  const logs1 = await offs('Navegou para outra página (#/logs)');
  out.steps.route_leave = { before, atLeave, after, active: await js('__pad.active'), offLogged: logs1 > logs0 };

  // Repete o cenário ao rolar a área do controle para fora da tela com o analógico pressionado (revisão O1).
  await js(`location.hash = '#/pad'`);
  await waitFor(`__pad.active`, 'retorno à área do controle');
  await sleep(600);
  b = await box(key('ls'));
  await sleep(200);
  await mouse('mouseMoved', b.x, b.y, 0);
  await mouse('mousePressed', b.x, b.y);
  for (let i = 1; i <= 5; i++) { await mouse('mouseMoved', b.x, b.y - 8 * i); await sleep(20); }
  await sleep(400);
  const before2 = since();
  await js('window.scrollTo(0, 0)');
  await sleep(400);
  const atScroll = since();
  for (let i = 1; i <= 4; i++) { await mouse('mouseMoved', b.x, b.y - 45 - 3 * i); await sleep(60); }
  await sleep(400);
  const after2 = since();
  await mouse('mouseReleased', b.x, b.y - 45, 0);
  const logs2 = await offs('A seção de controle saiu da tela');
  out.steps.scroll_out = { before: before2, atScroll, after: after2, active: await js('__pad.active'), offLogged: logs2 > 0 };

  // Revisão C3: sair da área do controle enquanto W está pressionado interrompe o movimento; eventos de repetição não o retomam ao voltar.
  await js(`document.getElementById('pad-block').scrollIntoView({ block: 'start' })`);   // A rota continua em #/pad; role de volta à seção.
  await waitFor(`__pad.active`, 'retorno à área do controle pelo teclado');
  await sleep(700);
  const kz = await box('.pd-svgzone', false);
  await mouse('mouseMoved', kz.l + 6, kz.t + 6, 0);
  await mouse('mousePressed', kz.l + 6, kz.t + 6);
  await mouse('mouseReleased', kz.l + 6, kz.t + 6, 0);
  await sleep(200);
  const W = (repeat) => send('Input.dispatchKeyEvent', { type: 'keyDown', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87, autoRepeat: repeat });
  since();
  await W(false);
  for (let i = 0; i < 12; i++) { await sleep(50); await W(true); }
  await sleep(150);
  const kHeld = since();
  await js('window.scrollTo(0, 0)');
  await sleep(400);
  for (let i = 0; i < 8; i++) { await sleep(50); await W(true); }
  const kOut = since();
  await js(`document.getElementById('pad-block').scrollIntoView({ block: 'start' })`);
  await sleep(700);
  const kActive = await js('__pad.active');
  for (let i = 0; i < 14; i++) { await sleep(50); await W(true); }
  await sleep(300);
  const kBack = since();
  await send('Input.dispatchKeyEvent', { type: 'keyUp', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87 });
  await sleep(300);
  since();
  out.steps.kbd_repeat = { held: kHeld, out: kOut, back: kBack, activeBack: kActive,
    focus: await js(`!!document.activeElement?.closest?.('.pd-zone')`) };

  // Revisão C7: pressionar, soltar e pressionar uma ação antes da primeira resposta não pode manter action_hold após soltar.
  const hb = `[...document.querySelectorAll('.pd-hold')].find((x) => x.textContent.includes('cabeça') && !x.disabled)`;
  const hp = await js(`(() => { const e = ${hb}; if (!e) return null; e.scrollIntoView({ block: 'center' }); const r = e.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
  if (!hp) throw new Error('Nenhuma ação disponível para pressionar (C7)');
  await sleep(400);
  await js('window.__delayResults = 300; window.__sentOps = []');
  await mouse('mouseMoved', hp.x, hp.y, 0);
  await mouse('mousePressed', hp.x, hp.y);
  await sleep(80);
  await mouse('mouseReleased', hp.x, hp.y, 0);
  await sleep(80);
  await mouse('mousePressed', hp.x, hp.y);
  await sleep(900);
  const tRel = await js('performance.now()');
  await mouse('mouseReleased', hp.x, hp.y, 0);
  await sleep(2000);
  const ops = await js('window.__sentOps');
  await js('window.__delayResults = 0');
  out.steps.hold_race = { holdsDuring: ops.filter((o) => o.op === 'action_hold' && o.at < tRel).length,
    holdsAfter: ops.filter((o) => o.op === 'action_hold' && o.at > tRel + 50).length, ops: ops.map((o) => o.op).join(',') };
  await sleep(500);

  // O pato 3D deve ficar visível à esquerda do controle remoto ao rolar até a área do controle.
  await js(`(() => { const s = document.querySelector('#pd-remote').getBoundingClientRect(); window.scrollTo(0, scrollY + s.top - 150); })()`);
  await sleep(900);
  out.pad3d = await js(`(() => { const c = document.querySelector('.pd-3d canvas').getBoundingClientRect(); const s = document.querySelector('#pd-remote').getBoundingClientRect();
    const vis = Math.max(0, Math.min(c.bottom, innerHeight) - Math.max(c.top, 56));
    return { visFrac: +(vis / c.height).toFixed(2), left: c.right <= s.left, cRight: Math.round(c.right), sLeft: Math.round(s.left),
      sticky: getComputedStyle(document.querySelector('.pd-3d')).position,
      stackSticky: getComputedStyle(document.querySelector('.pd-left')).position,
      cameraBelow: document.querySelector('.inline-camera').getBoundingClientRect().top >= document.querySelector('.pd-3d').getBoundingClientRect().bottom,
      touch: getComputedStyle(document.querySelector('.pd-3d canvas')).touchAction }; })()`);
  await shot('pad-3d-desktop.png');
  // O 3D desenha quando está visível e pausa fora da tela (contagem de frames de duck3d).
  const f3d = () => js(`document.querySelector('.pd-3d canvas').__duck3d.frames`);
  const dirty3d = () => js(`document.querySelector('.pd-3d canvas').__duck3d.dirty = true`);
  let fa = await f3d();
  out.pad3d.drawsInView = false;
  for (let i = 0; i < 20 && !out.pad3d.drawsInView; i++) {          // Em máquinas ocupadas, aguarda até 4 s pela renderização.
    await dirty3d(); await sleep(200);
    out.pad3d.drawsInView = (await f3d()) > fa;
  }
  await js('window.scrollTo(0, 0)');
  await sleep(1000);
  fa = await f3d();
  for (let i = 0; i < 5; i++) { await dirty3d(); await sleep(100); }
  out.pad3d.drawsOutOfView = (await f3d()) > fa;
  out.pad3d.activeAtTop = await js('__pad.active');

  // A ação Fazer da lista inicial deve levar diretamente à seção correspondente (revisão O17).
  await js('window.scrollTo(0, 0)');
  await sleep(300);
  // Clique pelo DOM: a página pode se mover e deixar o botão Pular sob as coordenadas antigas.
  const clickBtn = async (rowKeyText, label) => {
    const ok = await js(`(() => { const row = [...document.querySelectorAll('.onb-row')].find((r) => r.innerText.includes(${JSON.stringify(rowKeyText)}));
      const btn = row && [...row.querySelectorAll('button')].find((x) => x.textContent.includes(${JSON.stringify(label)}));
      if (!btn) return false; btn.scrollIntoView({ block: 'center' }); btn.click(); return true; })()`);
    if (!ok) throw new Error(`A lista não contém a etapa “${rowKeyText}” com a ação “${label}”`);
    await sleep(700);
  };
  const inView = (sel) => `(() => { const e = document.querySelector('${sel}'); if (!e) return false; const r = e.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 56; })()`;
  await clickBtn('5 Testar parada de emergência', 'Fazer');
  try { await waitFor(inView('#pd-estop'), 'rolagem até o teste de parada de emergência', 3000); } catch { /* Registra o resultado observado abaixo. */ }
  out.goto = { estop: await js(`({ inView: ${inView('#pd-estop')}, focus: document.activeElement?.id })`) };
  await js('window.scrollTo(0, 0)');
  await sleep(300);
  await clickBtn('4 Parear controle', 'Fazer');
  try { await waitFor(inView('#pd-wizard'), 'rolagem até o assistente de pareamento', 3000); } catch { /* Registra o resultado observado abaixo. */ }
  out.goto.wizard = await js(`({ open: !!document.querySelector('#pd-wizard'), inView: ${inView('#pd-wizard')} })`);
  await js(`[...document.querySelectorAll('#pd-wizard button')].find((x) => x.textContent.includes('Fechar'))?.click()`);
  await js('window.scrollTo(0, 0)');
  await sleep(300);
  await clickBtn('2 Orientação da IMU', 'Fazer');
  out.goto.imu = await js('location.hash');
  await js(`location.hash = '#/'`);
  await sleep(500);

  // ================= Concluir / pular / cancelar / refazer =================
  await js('window.scrollTo(0, 0)');
  await sleep(300);
  const rowState = (step) => js(`(() => { const r = document.querySelector('.onb-row[data-step="${step}"]'); return r ? [...r.classList].find((c) => /^onb-(ok|skip|todo|no|unk)$/.test(c)) : null; })()`);
  const dblAt = async (expr) => {
    const b = await js(`(() => { const e = ${expr}; if (!e) return null; e.scrollIntoView({ block: 'center' }); const r = e.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
    if (!b) throw new Error(`Duplo clique: elemento não encontrado: ${expr}`);
    await sleep(200);
    // A página atualiza a cada 0,5 s; confirme que o botão continua sob as coordenadas antes de clicar.
    for (let i = 0; i < 20; i++) {
      const hit = await js(`(() => { const e = ${expr}; const at = document.elementFromPoint(${b.x}, ${b.y}); return !!e && !!at && (at === e || e.contains(at)); })()`);
      if (hit) break;
      Object.assign(b, await js(`(() => { const e = ${expr}; const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`));
      await sleep(50);
    }
    out.dblAtRects = await js(`(() => { const row = document.querySelector('.onb-row[data-step="estop"]'); const rc = (sel) => { const e = row && row.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width)]; }; return { done: rc('.onb-donebtn'), skip: rc('.onb-skip'), at: [${b.x}, ${b.y}] }; })()`);
    const mouse = (type, clickCount, buttons) => send('Input.dispatchMouseEvent', { type, x: b.x, y: b.y, button: 'left', buttons, clickCount });
    await mouse('mouseMoved', 0, 0);
    await mouse('mousePressed', 1, 1); await mouse('mouseReleased', 1, 0);
    await sleep(60);
    await mouse('mousePressed', 2, 1); await mouse('mouseReleased', 2, 0);
  };
  const rowBtn = async (step, label) => {
    const ok = await js(`(() => { const r = document.querySelector('.onb-row[data-step="${step}"]');
      const b = r && [...r.querySelectorAll('button')].find((x) => x.textContent.includes(${JSON.stringify(label)}) && !x.disabled);
      if (!b) return false; b.click(); return true; })()`);
    if (!ok) throw new Error(`Não foi possível clicar em “${label}” na etapa “${step}”`);
  };
  // Cada etapa pendente oferece três ações: Fazer, Concluído e Pular.
  out.threeButtons = await js(`[...document.querySelectorAll('.onb-row')].filter((r) => !r.classList.contains('onb-ok'))
    .map((r) => ({ step: r.dataset.step, labels: [...r.querySelectorAll('.onb-acts > button, .onb-acts .two-step > button:first-child')].map((b) => b.textContent.trim()) }))`);
  // Marque os servos como concluídos e pule a IMU; a etapa seguinte deve ser o pareamento.
  await rowBtn('servo', 'Concluído');
  await waitFor(`document.querySelector('.onb-row[data-step="servo"]')?.classList.contains('onb-ok')`, 'servos marcados como concluídos');
  out.marked = { text: await js(`document.querySelector('.onb-row[data-step="servo"] .onb-text').textContent`),
    buttons: await js(`[...document.querySelectorAll('.onb-row[data-step="servo"] .onb-acts button')].map((b) => b.textContent.trim())`) };
  await rowBtn('imu', 'Pular');
  await waitFor(`document.querySelector('.onb-row[data-step="imu"]')?.classList.contains('onb-skip')`, 'IMU marcada como ignorada');
  out.skip = { imu: await rowState('imu'), imuText: await js(`document.querySelector('.onb-row[data-step="imu"] .onb-text').textContent`),
    now: await js(`document.querySelector('.onb-now')?.dataset.step`), mark: await js(`document.querySelector('.onb-row[data-step="imu"] .onb-mark').textContent`) };
  await shot('skip-rows.png', '.onb');
  // Desfaça a etapa ignorada e confira o retorno ao estado pendente.
  await rowBtn('imu', 'Desfazer etapa ignorada');
  await waitFor(`document.querySelector('.onb-row[data-step="imu"]')?.classList.contains('onb-todo')`, 'IMU voltou ao estado pendente');
  out.unskip = { imu: await rowState('imu'), now: await js(`document.querySelector('.onb-now')?.dataset.step`) };
  // Refazer a etapa concluída de servos deve abrir a página correspondente.
  await rowBtn('servo', 'Refazer');
  await sleep(300);
  out.redoHash = await js('location.hash');
  await js(`location.hash = '#/'`);
  await waitFor(`/Microduck conectado/.test(document.querySelector('.onb-h')?.innerText || '') && !document.querySelector('.onb-frozen')`, 'controle devolvido e lista retomada', 20000);
  await sleep(500);
  // Cancele a conclusão para que os estados desconhecidos possam ser vistos no cenário seguinte.
  await rowBtn('servo', 'Cancelar');
  await waitFor(`document.querySelector('.onb-row[data-step="servo"]')?.classList.contains('onb-todo')`, 'marcação dos servos cancelada');
  out.undone = await rowState('servo');
  // Ignorar a parada de emergência exige duas confirmações em até 3 s e um controle físico conectado.
  await fakeSet({ pad_connected: true });
  await waitFor(`(() => { const r = document.querySelector('.onb-row[data-step="estop"]'); const b = r && [...r.querySelectorAll('button')].find((x) => x.textContent === 'Pular'); return b && !b.disabled; })()`,
    'etapa de parada de emergência disponível para pular', 10000);
  // Confirmação em duas etapas (D4): o primeiro botão permanece; o segundo exige intervalo mínimo de 700 ms e expira em 3 s.
  const estopSkipText = () => js(`(() => { const r = document.querySelector('.onb-row[data-step="estop"]');
    const a = r && r.querySelector('.two-step-ask'); return a ? a.textContent : r && r.querySelector('button.onb-skip')?.textContent; })()`);
  // Duplo clique real não pode ignorar a etapa. Registra o intervalo entre cliques e repete se exceder 700 ms.

  await js(`(() => { window.__clicks = []; document.addEventListener('click', (e) => window.__clicks.push(performance.now()), true); window.__targets = []; document.addEventListener('click', (e) => { const t = e.target; window.__targets.push((t.className || t.tagName) + ':' + (t.textContent || '').slice(0, 12)); }, true); window.__arms = []; new MutationObserver(() => { const a = !!document.querySelector('.onb-row[data-step="estop"] .two-step-ask'); if (window.__arms[window.__arms.length - 1]?.[1] !== a) { const row = document.querySelector('.onb-row[data-step="estop"]'); const rc = (sel) => { const e = row && row.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width)]; }; window.__arms.push([Math.round(performance.now()), a, rc('.onb-donebtn'), rc('.onb-skip'), rc('.two-step-ask'), getComputedStyle(row.querySelector('.two-step') || row).display]); } }).observe(document.body, { subtree: true, childList: true }); return true; })()`);
  for (let i = 0; i < 3; i++) {
    await js(`(() => { window.__clicks.length = 0; return true; })()`);
    await dblAt(`[...document.querySelectorAll('.onb-row[data-step="estop"] button')].find((x) => x.textContent === 'Pular')`);
    await sleep(300);
    const gap = await js(`window.__clicks.length >= 2 ? window.__clicks[1] - window.__clicks[0] : null`);
    out.estopDblGap = gap;
    out.estopArmed300 = await js(`!!document.querySelector('.onb-row[data-step="estop"] .two-step-ask')`);
    out.estopClicks = await js(`window.__clicks.slice()`);
    out.estopTargets = await js(`window.__targets.slice(-4)`);
    out.estopArms = await js(`window.__arms.slice(-6)`);
    const onSkip = await js(`window.__targets.slice(-2).every((t) => t.includes('onb-skip'))`);
    if (gap != null && gap < 600 && onSkip) break;
    await sleep(3500);
  }
  await sleep(1200);
  out.estopDbl = { state: await rowState('estop'), armed: await js(`!!document.querySelector('.onb-row[data-step="estop"] .two-step-ask')`) };
  await sleep(2500);
  await rowBtn('estop', 'Pular');
  await sleep(300);
  out.estopOnce = { text: await estopSkipText(), state: await rowState('estop'), skipStill: await js(`[...document.querySelectorAll('.onb-row[data-step="estop"] button.onb-skip')].map((b) => b.textContent)`) };
  await shot('skip-estop-confirm.png', '.onb-row[data-step="estop"]');
  await sleep(3300);
  out.estopTimeout = { text: await estopSkipText(), state: await rowState('estop') };
  await rowBtn('estop', 'Pular');
  await sleep(900);
  await rowBtn('estop', 'Confirmar');
  await waitFor(`document.querySelector('.onb-row[data-step="estop"]')?.classList.contains('onb-skip')`, 'etapa de parada de emergência ignorada');
  out.estopTwice = await rowState('estop');
  await rowBtn('estop', 'Desfazer etapa ignorada');
  await waitFor(`!document.querySelector('.onb-row[data-step="estop"]')?.classList.contains('onb-skip')`, 'etapa de parada de emergência restaurada');
  await fakeSet({ pad_connected: false });
  // Quando o programa principal não confirma a orientação da IMU, pular exige confirmação explícita das consequências.
  await fakeSet({ imu_verified: false });
  await waitFor(`document.querySelector('.onb-row[data-step="imu"]')?.classList.contains('onb-no')`, 'IMU não confirmada pelo programa principal', 10000);
  await rowBtn('imu', 'Pular');
  await sleep(300);
  out.imuBlocked = await js(`(() => { const r = document.querySelector('.onb-row[data-step="imu"]');
    return { disabled: r.querySelector('button.onb-skip').disabled, ask: r.querySelector('.two-step-ask')?.textContent || null,
      state: [...r.classList].find((c) => /^onb-(ok|skip|todo|no|unk)$/.test(c)) }; })()`);
  await shot('skip-imu-two-step.png', '.onb');
  await sleep(3300);                                                   // Sem confirmação, a pergunta expira em 3 s.
  out.imuBlocked.after = await rowState('imu');
  await fakeSet({ imu_verified: true });
  await waitFor(`!/Controle físico conectado/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'controle físico desconectado', 10000);
  await sleep(500);

  // ================= Computador com 1100 px: indicadores em 4 + 3 =================
  await open('#/', 1100, 900, false);
  out.d1100 = await js(`(() => { const c = [...document.querySelectorAll('.band > *')].map((e) => Math.round(e.getBoundingClientRect().top));
    return { tops: c, sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }; })()`);
  await shot('desktop-1100-full.png', 'full');

  // ================= Indicador de temperatura da placa: frequência reduzida, temperatura alta, indisponível =================
  await open('#/', 1440, 900, false);
  await fakeSet({ cpu: { c: 92.4, level: 4, max_level: 6, khz: 1008000, max_khz: 1800000 } });
  await waitFor(`/reduziu a frequência/.test(document.querySelector('.band-cpu').innerText)`, 'indicador da placa em vermelho', 8000);
  out.cpu = { throttled: await js(`({ text: document.querySelector('.band-cpu').innerText.replace(/\\s+/g, ' '), bad: document.querySelector('.band-cpu').classList.contains('bad'),
    todo: document.querySelector('.todo')?.innerText.replace(/\\s+/g, ' ') })`) };
  await shot('band-throttled.png', '.band');
  await shot('band-throttled-with-todo.png', '.overview');
  await fakeSet({ cpu: { c: 82.3, level: 0, khz: 1800000 } });
  await waitFor(`/temperatura alta/.test(document.querySelector('.band-cpu').innerText)`, 'indicador da placa em laranja', 8000);
  out.cpu.hot = await js(`document.querySelector('.band-cpu').innerText.replace(/\\s+/g, ' ')`);
  await shot('band-hot.png', '.band');
  await fakeSet({ errors: { 'robot.health': { code: -32603, message: 'health sem resposta (teste)' } } });
  await waitFor(`/Health sem atualização/.test(document.querySelector('.band-cpu').innerText)`, 'temperatura da placa indisponível', 15000);
  out.cpu.stale = await js(`document.querySelector('.band-cpu').innerText.replace(/\\s+/g, ' ')`);
  await shot('band-health-stale.png', '.band');
  await fakeSet({ errors: { 'robot.health': null }, cpu: { c: 76.875, level: 0, khz: 1800000 } });

  // ================= Celular com 390 px =================
  await open('#/', 390, 844, true);
  out.phone = await sw();
  // Revisão C6: o canvas mantém touch-action: pan-y; um dedo rola a página e dois dedos giram o pato.
  out.phoneCanvas = await js(`(() => { const c = document.querySelector('.stage-ov canvas'); return { computed: getComputedStyle(c).touchAction, inline: c.style.touchAction }; })()`);
  await shot('phone-390-full.png', 'full');
  await open('#/pad', 390, 844, true);
  out.phone_pad = await sw();
  await shot('phone-pad-block.png');
  // No celular, o cartão 3D fica acima do controle remoto, é mais baixo e não fica fixo.
  out.phone3d = await js(`(() => { const c = document.querySelector('.pd-3d'); const r = document.querySelector('#pd-remote');
    return { above: c.getBoundingClientRect().bottom <= r.getBoundingClientRect().top, h: Math.round(c.querySelector('.pd-3d-stage').getBoundingClientRect().height),
      sticky: getComputedStyle(c).position }; })()`);
  await js(`document.querySelector('.pd-3d').scrollIntoView({ block: 'center' })`);
  await sleep(900);
  await shot('pad-3d-phone.png');
  // Um gesto iniciado na área vazia do controle rola a página sem mover o analógico (revisão O2).
  const swipe = async (x, y, dy, stepMs = 30) => {
    await touch('touchStart', [{ x, y, id: 1 }]);
    for (let i = 1; i <= 4; i++) { await touch('touchMove', [{ x, y: y - (dy * i) / 4, id: 1 }]); await sleep(stepMs); }
    await touch('touchEnd', []);
  };
  await step('swipe_pad_blank', async () => {
    const r = await box('.pd-svgbox');
    await sleep(700);
    await swipe(r.x - r.w * 0.47, r.y, 90);          // Área vazia dentro do SVG, fora da zona do analógico.
  });
  // Um gesto iniciado em uma ação não a executa; manter o botão pressionado por 0,4 s executa.
  const holdBtn = `[...document.querySelectorAll('.pd-hold')].find((x) => x.textContent.includes('cabeça') && !x.disabled)`;
  const btnBox = async () => js(`(() => { const e = ${holdBtn}; if (!e) return null; e.scrollIntoView({ block: 'center' }); const r = e.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
  await step('swipe_action', async () => {
    const p = await btnBox();
    if (!p) throw new Error('Nenhuma ação disponível para pressionar');
    await sleep(700);
    await swipe(p.x, p.y, 70);
  }, 800);
  await step('hold_action', async () => {
    const p = await btnBox();
    await sleep(700);
    await touch('touchStart', [{ x: p.x, y: p.y, id: 2 }]);
    await sleep(500);
    await touch('touchEnd', []);
  }, 800);
  // Ignora pressionamentos iniciados até 0,5 s depois de uma rolagem inercial.
  await step('press_right_after_scroll', async () => {
    const p = await btnBox();
    await sleep(700);
    await js('window.scrollBy(0, 2)');
    await sleep(60);
    await touch('touchStart', [{ x: p.x, y: p.y - 2, id: 3 }]);
    await sleep(400);
    await touch('touchEnd', []);
  }, 800);
  // Um gesto iniciado no botão A não envia habilidade; um toque simples envia.
  await step('swipe_svg_a', async () => {
    const p = await box(key('south'));
    await sleep(700);
    await swipe(p.x, p.y, 70);
  }, 800);
  await step('tap_svg_a', async () => {
    const p = await box(key('south'));
    await sleep(700);
    await touch('touchStart', [{ x: p.x, y: p.y, id: 4 }]);
    await sleep(70);
    await touch('touchEnd', []);
  }, 1000);

  // ================= Estado desconhecido: configd indisponível e falha ao ler a calibração → ? =================
  // No modo de movimento, o programa principal informa a calibração após entrar na fase de controle.
  // Este cenário simula uma falha na solicitação calibration-status.
  await open('#/', 1440, 900, false);
  await fakeSet({ errors: { 'pad.status': { code: -32603, message: 'configd indisponível (teste)' },
                            'robot.busCommand': { code: -32603, message: 'falha ao ler a calibração (teste)' } }, restart: 0.3 });
  await waitFor(`(() => { const m = [...document.querySelectorAll('.onb-row .onb-mark')].map((e) => e.textContent.trim()); return m[0] === '?' && m[1] === '?' && m[2] === '?' && m[3] === '?'; })()`,
    'interrogações na lista inicial', 30000);
  out.unknown = await onbMarks();
  out.unknownText = await js(`document.querySelector('.onb').innerText.replace(/\\s+/g, ' ')`);
  await shot('onb-unknown.png', '.onb');
  await fakeSet({ errors: { 'pad.status': null, 'robot.busCommand': null }, restart: 0.3 });

  // ================= Página dos servos: sair com servos mantendo força não devolve o controle =================
  await open('#/', 1440, 900, false);
  await waitFor(`/Microduck conectado/.test(document.querySelector('.onb-h')?.innerText || '')`, 'programa principal reconectado', 15000);
  await fakeSet({ posture: 'holding' });                          // A página de servos não assume durante uma política ativa; estabilize a postura primeiro.
  await sleep(1500);
  await js(`location.hash = '#/servos'`);
  await waitFor(`/Ajustando os servos/.test(document.querySelector('.sv-sub')?.innerText || '')`, 'página de servos assumiu o controle simulado', 15000);
  // Outra conexão ativa o torque de dois servos; a sessão é compartilhada pelo Studio.
  await js(`(async () => { const w = new WebSocket(location.origin.replace('http', 'ws') + '/ws'); await new Promise((ok) => { w.onopen = ok; });
    w.send(JSON.stringify({ t: 'cmd', id: 'h1', name: 'servo.op', args: { op: 'torque', ids: [20, 21], on: 1 } }));
    await new Promise((z) => setTimeout(z, 800)); w.close(); })()`);
  await sleep(1500);
  const dialogs0 = dialogs.length;
  await js(`location.hash = '#/'`);
  await waitFor(`/2 mantendo força/.test(document.querySelector('.servo-bar')?.innerText || '')`, 'aviso dos servos em outra página', 10000);
  await js('window.scrollTo(0, 0)');
  await sleep(500);
  out.servoBar = { text: await js(`document.querySelector('.servo-bar').innerText.replace(/\\s+/g, ' ')`), dialogs: dialogs.length - dialogs0 };
  await shot('servo-hold-bar.png');
  // O aviso permanece visível ao rolar até a área do controle (revisão D6).
  await js(`document.getElementById('pd-remote').scrollIntoView({ block: 'center' })`);
  await sleep(600);
  out.servoBar.sticky = await js(`(() => { const r = document.querySelector('.servo-bar').getBoundingClientRect(); return { top: Math.round(r.top), visible: r.top >= 50 && r.bottom <= innerHeight }; })()`);
  out.servoBar.visualFits = await js(`(() => { const el=document.querySelector('.pd-left'), s=getComputedStyle(el); return s.position==='static' || el.getBoundingClientRect().height+parseFloat(s.top)+16<=innerHeight; })()`);
  // No celular, confira o aviso, o indicador no topo e o estado do controle remoto.
  await open('#/', 390, 844, true);
  await waitFor(`/2 mantendo força/.test(document.querySelector('.servo-bar')?.innerText || '')`, 'aviso dos servos no celular', 10000);
  await js(`document.getElementById('pd-remote').scrollIntoView({ block: 'center' })`);
  await sleep(800);
  out.servoBar.phone = await js(`(() => { const r = document.querySelector('.servo-bar').getBoundingClientRect(); const b = document.querySelector('.topbar .sv-badge');
    return { top: Math.round(r.top), h: Math.round(r.height), visible: r.top >= 50 && r.bottom <= innerHeight, badge: b ? getComputedStyle(b).display !== 'none' && b.textContent : null,
      remote: /Ajuste dos servos em andamento: o programa principal está pausado/.test(document.getElementById('pd-remote')?.innerText || ''),
      sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }; })()`);
  await shot('b3-phone-bar.png');
  // Após recarregar em outra página, a sessão e o aviso continuam ativos.
  await open('#/imu', 1440, 900, false);
  out.servoBar.afterReload = await js(`/2 mantendo força/.test(document.querySelector('.servo-bar')?.innerText || '')`);
  // A devolução ao programa principal exige duas etapas (revisão D4); duplo clique não pode confirmar.
  const handBtn = `[...document.querySelectorAll('.servo-bar button')].find((b) => b.textContent.includes('Devolver ao programa principal'))`;
  await dblAt(handBtn);
  await sleep(1500);
  out.servoBar.dbl = { stillOpen: await js(`/2 mantendo força/.test(document.querySelector('.servo-bar')?.innerText || '')`),
    armed: await js(`!!document.querySelector('.servo-bar .two-step-ask')`) };
  await sleep(2500);
  out.servoBar.dbl.disarmed = await js(`!document.querySelector('.servo-bar .two-step-ask')`);
  await js(`${handBtn}.click()`);
  await sleep(300);
  out.servoBar.armed = await js(`document.querySelector('.servo-bar .two-step-ask')?.textContent`);
  out.servoBar.stillOpen = await js(`/2 mantendo força/.test(document.querySelector('.servo-bar')?.innerText || '')`);
  await js(`document.querySelector('.servo-bar .two-step-ask').click()`);          // 300 ms ainda está dentro do intervalo mínimo de 700 ms.
  await sleep(200);
  out.servoBar.earlyIgnored = await js(`/2 mantendo força/.test(document.querySelector('.servo-bar')?.innerText || '') && !!document.querySelector('.servo-bar .two-step-ask')`);
  await sleep(400);
  // Simula a parada manual do programa principal; o robotd simulado recusa conexões por 8 s.
  await fakeSet({ restart: 8 });
  await sleep(300);                                                // Aguarda a desconexão antes de devolver o controle, evitando reconexão pela sondagem.
  await js(`document.querySelector('.servo-bar .two-step-ask').click()`);
  await waitFor(`/Controle devolvido/.test(document.querySelector('.servo-bar')?.innerText || '')`, 'aviso de controle devolvido', 12000);
  out.servoBar.after = await js(`document.querySelector('.servo-bar').innerText.replace(/\\s+/g, ' ')`);
  await shot('servo-handback-bar.png', '.servo-bar');
  await sleep(2500);
  out.servoBar.stillThere = await js(`/Controle devolvido/.test(document.querySelector('.servo-bar')?.innerText || '')`);   // O aviso permanece enquanto o programa principal está desconectado (revisão D12).
  await waitFor(`!document.querySelector('.servo-bar')`, 'aviso removido após reconexão do programa principal', 20000);
  out.servoBar.gone = true;
}

async function step(name, fn, settle = 500) {
  since();
  const extra = (await fn()) || {};
  await sleep(settle);
  out.steps[name] = { recs: since(), ...extra };
  log(name, out.steps[name].recs.length, 'registros');
}

process.stdout.write(JSON.stringify(out));
ws.close();
await fetch(`http://127.0.0.1:${CDP}/json/close/${page.id}`);
