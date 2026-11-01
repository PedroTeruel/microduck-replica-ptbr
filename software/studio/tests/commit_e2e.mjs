// Teste ponta a ponta do cenário de fábrica “Gravar no programa principal” (tarefa 13): percorre calibração até o modo de movimento no Edge local sem interface (CDP).
// O robotd simulado inicia com --mode commissioning --calib factory (sem calibração); tests/test_commit_e2e.py inicia o Studio com um script que substitui
// studio.helper.calib_commit por uma implementação simulada (o computador não tem o helper root).
//
// --phase factory: confira a preparação de fábrica, botões desativados, prévia expansível, direções, limites e TOML de cada servo.
// --phase mark: conclua a etapa 1 com confirmação dupla se a calibração estiver ausente; o item de zero dos servos na etapa 3 fica verde (tarefa 16).
// --phase imu: calibração inicial da IMU, amostras em repouso e inclinadas, cálculo de orientação e verificação pelo programa principal.
// --phase servo: centralize os servos com um clique (--servo-sim) e devolva o controle ao programa principal.
// --phase commit: grave a etapa 3; o helper simulado muda o robotd para motion + control e a interface mostra a etapa concluída e o modo de movimento.
// --phase fail: simule a rejeição da calibração; a página deve mostrar o motivo e preservar o progresso durante a desconexão.
// --phase stance0: no modo de calibração, desative os controles de postura da página IMU, explique o motivo e permita ir à etapa 3 (tarefa 17).
// --phase stance: no modo de movimento, os controles da página IMU devem enviar os mesmos comandos do cartão de controle (tarefa 17).
// Os resultados são enviados em JSON para stdout e verificados por tests/test_commit_e2e.py. Requer Node >= 22; sem dependências.
import { mkdirSync, writeFileSync } from 'node:fs';
import { createConnection } from 'node:net';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('url');
const CDP = arg('cdp');
const FAKE = Number(arg('fake-port'));
const PHASE = arg('phase', 'factory');
const SHOTS = arg('shots', '');
const CONTROL = arg('control-file', '');
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => process.stderr.write(`[commit-e2e] ${a.join(' ')}` + '\n');

// Interface de controle dos testes: envia fake.set ao robotd/configd simulado (mesmo objeto).
const fakeRpc = (method, params) => new Promise((resolve, reject) => {
  const s = createConnection({ host: '127.0.0.1', port: FAKE }, () => {
    s.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) + '\n');
  });
  let buf = '', done = false;
  const timer = setTimeout(() => { if (!done) { done = true; s.destroy(); reject(new Error('Tempo limite de fake.set')); } }, 5000);
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
const fakeSet = (params) => fakeRpc('fake.set', params);

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
  // Confirmação nativa do navegador (por exemplo, “O robô está deitado...?”): confirme como em overview_e2e e registre a pergunta.
  if (m.method === 'Page.javascriptDialogOpening') { dialogs.push(m.params.message); send('Page.handleJavaScriptDialog', { accept: true }); }
});
const dialogs = [];
const send = (method, params = {}) => new Promise((ok, fail) => {
  const i = ++id;
  const timer = setTimeout(() => {
    waiting.delete(i);
    fail(new Error(`CDP sem resposta após 15 s: ${method}`));
  }, 15000);
  waiting.set(i, { ok: (m) => { clearTimeout(timer); ok(m); }, fail: (e) => { clearTimeout(timer); fail(e); } });
  ws.send(JSON.stringify({ id: i, method, params }));
});
ws.addEventListener('close', () => {
  for (const w of waiting.values()) w.fail(new Error('Conexão de depuração do Edge encerrada'));
  waiting.clear();
});
ws.addEventListener('error', () => log('Erro no WebSocket CDP'));
const js = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(`Erro na página: ${r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text}`);
  return r.result?.result?.value;
};
const waitFor = async (expr, what, timeout = 12000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(expr)) return true; await sleep(100); }
  const now = await js(`[location.hash, document.querySelector('[data-step="commit"]')?.innerText?.slice(0, 600), document.querySelector('.onb-h')?.innerText, document.querySelector('.imu-coarse')?.innerText?.slice(0, 400), document.querySelector('.sv-sub')?.innerText].join(' ／ ')`);
  throw new Error(`Tempo esgotado após ${timeout / 1000} s aguardando ${what}. Conteúdo atual da página: ${now}. Erros: ${errors.slice(-4).join(' | ')}`);
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

log('Edge conectado; carregando a página');
await send('Page.enable');
await send('Runtime.enable');
await send('Page.bringToFront');                                  // A página precisa estar em primeiro plano; em segundo plano, o Studio envia atualizações a 1 Hz e a lista considera a conexão perdida.
await send('Emulation.setFocusEmulationEnabled', { enabled: true });
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: `${BASE}#/` });
await sleep(800);

log('Página aberta');
const out = { phase: PHASE };
const card = `document.querySelector('[data-step="commit"] .onb-commit')`;
const snapshot = () => js(`(() => {
  const c = ${card};
  if (!c) return null;
  const checks = [...c.querySelectorAll('.onb-checks li')].map((li) => ({
    ok: li.classList.contains('ok'), text: li.innerText.replace(/\\s+/g, ' ').trim() }));
  const act = [...c.querySelectorAll('.onb-commit-acts button')];
  const write = act.find((b) => b.textContent.includes('Gravar no programa principal'));
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

// Controles de postura na página da IMU (tarefa 17): estado dos botões, texto explicativo e comandos enviados (intercepta WebSocket.send e registra apenas cmd).
const stance = () => js(`(() => { const c = document.querySelector('.imu-stance'); if (!c) return null;
  const b = (sel) => { const e = c.querySelector(sel); return e ? { text: e.textContent.trim(), disabled: e.disabled } : null; };
  return { stand: b('.imu-stand'), relax: b('.imu-relax'),
    now: c.querySelector('.imu-stance-now')?.innerText.replace(/\\s+/g, ' ').trim() || '',
    why: c.querySelector('.imu-stance-why')?.innerText.replace(/\\s+/g, ' ').trim() || null,
    goCommit: !!c.querySelector('.imu-go-commit'), text: c.innerText.replace(/\\s+/g, ' ').trim() }; })()`);
const recordSends = () => js(`(() => { if (window.__sent) { window.__sent.length = 0; return true; } window.__sent = [];
  const orig = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) {
    try { const m = JSON.parse(d); if (m.t === 'cmd') window.__sent.push({ name: m.name, args: m.args }); } catch (e) { /* não é JSON */ }
    return orig.call(this, d);
  };
  return true; })()`);
const sentStand = () => js(`(window.__sent || []).filter((m) => m.name === 'pad.op' && m.args && m.args.op === 'stand')`);
const remoteStand = `[...document.querySelectorAll('.pd-remote .pd-big')].find((x) => x.querySelector('b')?.textContent === 'Ficar em pé')`;

if (PHASE === 'ssh') {
  // Controle SSH da página Mais (10-21): o cartão informa que a imagem de fábrica aceita apenas chaves; sem helper root, a API relata isso sem erro.
  await js(`location.hash = '#/settings'`);
  await waitFor(`!!document.querySelector('.ssh-settings')`, 'cartão SSH na página Mais', 20000);
  await waitFor(`!/Carregando/.test(document.querySelector('.ssh-settings .ssh-now')?.innerText || 'Carregando')`, 'estado do SSH carregado', 20000);
  out.ssh = await js(`(() => { const c = document.querySelector('.ssh-settings');
    return { text: c.innerText.replace(/\\s+/g, ' ').trim(), now: c.querySelector('.ssh-now').innerText.trim(),
      onDisabled: c.querySelector('.ssh-on').disabled, needWebPw: !!c.querySelector('.ssh-need-web-pw'),
      inputs: c.querySelectorAll('input[type=password]').length }; })()`);
  await shot('settings-ssh.png');
}

if (PHASE === 'stance0') {
  // Também é possível ficar em pé no modo de calibração (10-21): confirme “Ativar postura”, envie imu.op hold (fork hold-home) e mostre a postura de calibração em pé;
  // “Desativar (liberar torque)” também funciona, envia o mesmo relax do botão superior e retorna ao estado de calibração sem torque.
  await js(`location.hash = '#/imu'`);
  await waitFor(`!!document.querySelector('.imu-stance')`, 'cartão de postura em pé da página IMU', 20000);
  await waitFor(`/Modo de calibração \(sem força\)/.test(document.querySelector('.imu-stance .imu-stance-now')?.innerText || '')`, 'cartão mostra modo de calibração sem força', 10000);
  await waitFor(`(() => { const b = document.querySelector('.imu-stance .imu-stand'); return !!b && !b.disabled; })()`,
    'botão de postura em pé habilitado no modo de calibração', 10000);
  out.stance = await stance();
  await shot('imu-stance-commissioning.png');
  await recordSends();
  await js(`document.querySelector('.imu-stance .imu-stand').click()`);
  await waitFor(`/Modo de calibração \(em pé\)/.test(document.querySelector('.imu-stance .imu-stance-now')?.innerText || '')`, 'postura em pé confirmada no modo de calibração', 15000);
  out.holdSent = await js(`(window.__sent || []).filter((m) => m.name === 'imu.op')`);
  out.dialogs = dialogs.slice();
  out.holding = await stance();
  await shot('imu-stance-commissioning-holding.png');
  await recordSends();
  await js(`document.querySelector('.imu-stance .imu-relax').click()`);
  await waitFor(`/Modo de calibração \(sem força\)/.test(document.querySelector('.imu-stance .imu-stance-now')?.innerText || '')`, 'torque desativado no modo de calibração', 15000);
  out.relaxSent = await js(`(window.__sent || []).filter((m) => m.name === 'relax')`);
  out.after = await stance();
}

if (PHASE === 'stance') {
  // Modo de movimento: sem torque, “Ativar postura” envia o mesmo comando “Levantar” do cartão de controle; “Desativar” equivale ao botão superior de liberação.
  await fakeSet({ mode: 'motion', calib: 'committed', posture: 'limp', restart: 0.4 });
  await sleep(3000);       // Nos primeiros 2 s após liberar o torque, comandos de movimento são recusados; o estado do controle atualiza a cada segundo.
  await js(`location.hash = '#/imu'`);
  await waitFor(`!!document.querySelector('.imu-stance')`, 'cartão de postura em pé da página IMU', 20000);
  await waitFor(`(() => { const b = document.querySelector('.imu-stance .imu-stand'); return !!b && !b.disabled; })()`,
    'botão de postura em pé habilitado no modo de movimento', 20000);
  out.before = await stance();
  await shot('imu-stance-motion.png');
  await recordSends();
  // Clique somente quando o botão estiver habilitado; aguarde na página para evitar que seja desativado entre a verificação e o clique.
  await js(`new Promise((ok) => { const t0 = Date.now(); const t = setInterval(() => {
    const b = document.querySelector('.imu-stance .imu-stand');
    if (b && !b.disabled) { clearInterval(t); b.click(); ok(true); } else if (Date.now() - t0 > 10000) { clearInterval(t); ok(false); } }, 50); })`);
  // O programa simulado pode não reproduzir a animação de levantar; valide que o comando enviado é o mesmo do cartão de controle.
  await waitFor(`(window.__sent || []).some((m) => m.name === 'pad.op' && m.args && m.args.op === 'stand')`, 'comando para ficar em pé enviado pelo cartão IMU', 5000);
  out.standSent = await sentStand();
  await waitFor(`/Em pé/.test(document.querySelector('.imu-stance .imu-stance-now')?.innerText || '')`,
    'comando para ficar em pé concluído; agora redefine o cenário do controle', 15000);
  out.standing = await stance();
  await fakeSet({ posture: 'limp' });
  await sleep(3000);       // Como acima, o backend recusa o comando para ficar em pé nos primeiros 2 s após liberar o torque; a interface pode ainda exibir o estado antigo.
  await js(`location.hash = '#/pad'`);
  try {
    await waitFor(`(() => { const b = ${remoteStand}; return !!b && !b.disabled; })()`, 'botão Ficar em pé habilitado no cartão de controle', 20000);
  } catch (e) {
    // Em falhas ocasionais com a suíte completa ou máquina ocupada, inclua o texto, estado e motivo de desativação de cada botão.
    const why = await js(`[...document.querySelectorAll('.pd-remote .pd-big')].map((x) => (x.querySelector('b')?.textContent || '?') + '|' + (x.disabled ? 'desativado' : 'habilitado') + '|' + (x.title || '')).join(' ; ')`);
    throw new Error(`${e.message} / botões do controle: ${why}`);
  }
  await recordSends();
  await js(`new Promise((ok) => { const t0 = Date.now(); const t = setInterval(() => {
    const b = ${remoteStand};
    if (b && !b.disabled) { clearInterval(t); b.click(); ok(true); } else if (Date.now() - t0 > 10000) { clearInterval(t); ok(false); } }, 50); })`);
  await waitFor(`(window.__sent || []).some((m) => m.name === 'pad.op' && m.args && m.args.op === 'stand')`, 'comando para ficar em pé enviado pelo cartão de controle', 5000);
  out.remoteSent = await sentStand();
  await js(`location.hash = '#/imu'`);
  await waitFor(`(() => { const b = document.querySelector('.imu-stance .imu-relax'); return !!b && !b.disabled; })()`, 'botão de desativação habilitado', 10000);
  await recordSends();
  await js(`document.querySelector('.imu-stance .imu-relax').click()`);
  await waitFor(`(window.__sent || []).some((m) => m.name === 'relax')`, 'comando para liberar os motores enviado', 5000);
  out.relaxSent = await js(`(window.__sent || []).filter((m) => m.name === 'relax')`);
}

if (PHASE === 'mark') {
  // Fábrica: o programa principal informa que os 15 servos não foram calibrados (hard). A etapa pode ser marcada com confirmação dupla (10-20).
  const servoRow = `document.querySelector('.onb-row[data-step="servo"]')`;
  const servoCheck = `[...(${card}?.querySelectorAll('.onb-checks li') || [])].find((li) => li.innerText.includes('Ponto zero dos servos'))`;
  await waitFor(`!!${servoRow} && !!${card} && !!(${servoCheck})`, 'preparação das etapas 1 e 3', 20000);
  out.before = await js(`({ row: ${servoRow}.querySelector('.onb-mark').getAttribute('aria-label'), check: (${servoCheck}).className })`);
  const doneBtn = `[...${servoRow}.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Concluído')`;
  if (!await js(`(() => { const b = ${doneBtn}; if (!b) return false; b.scrollIntoView({ block: 'center' }); b.click(); return true; })()`)) {
    throw new Error('Não foi possível encontrar o botão Concluído na etapa de ponto zero dos servos');
  }
  await waitFor(`!!${servoRow}.querySelector('.two-step-ask')`, 'segunda confirmação de Concluído com as consequências', 5000);
  out.ask = await js(`${servoRow}.querySelector('.two-step-ask').textContent`);
  out.afterOne = await js(`${servoRow}.querySelector('.onb-mark').getAttribute('aria-label')`);   // Um clique não confirma a ação.
  await shot('commit-mark-servo-ask.png');
  await sleep(900);                                                  // Proteção de 700 ms do TwoStep.
  await js(`${servoRow}.querySelector('.two-step-ask').click()`);
  await waitFor(`${servoRow}.querySelector('.onb-mark')?.getAttribute('aria-label') === 'Concluído'`, 'etapa 1 marcada como concluída', 10000);
  await waitFor(`(${servoCheck})?.classList.contains('ok')`, 'ponto zero dos servos aprovado na etapa 3', 10000);
  out.after = await js(`({ row: ${servoRow}.querySelector('.onb-mark').getAttribute('aria-label'),
    text: ${servoRow}.querySelector('.onb-text').textContent, check: (${servoCheck}).innerText.replace(/\\s+/g, ' ').trim() })`);
  await shot('commit-mark-servo-done.png');
}

if (PHASE === 'imu-redo') {
  await js(`location.hash = '#/imu'`);
  await waitFor(`!![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.trim() === 'Recalibrar orientação' && !b.disabled)`,
    'opção de recalibrar continua disponível para a IMU salva', 10000);
  out.entryVisible = true;
  out.original = await fakeRpc('robot.busCommand', { action: 'calibration-status' });
  await recordSends();
  await clickExact('.imu-coarse button', 'Recalibrar orientação');
  out.beforeConfirm = await js(`(window.__sent || []).filter((m) => m.name === 'imu.op')`);
  await waitFor(`!!document.querySelector('.imu-coarse .two-step-ask')`, 'segunda confirmação necessária para recalibrar', 5000);
  await sleep(900);
  await js(`document.querySelector('.imu-coarse .two-step-ask').click()`);
  await waitFor(`/A recalibração ainda não terminou/.test(document.querySelector('.imu-coarse')?.innerText || '') &&
    !![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.includes('Coletar repouso') && !b.disabled)`, 'fluxo de calibração inicial retomado', 15000);
  out.active = await stance();
  await shot('imu-redo-active.png');
  // A atualização da página deve recuperar a sessão persistente e manter visível a montagem confirmada.
  await send('Page.reload');
  await waitFor(`/A recalibração ainda não terminou/.test(document.querySelector('.imu-coarse')?.innerText || '') &&
    !![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.includes('Coletar repouso') && !b.disabled)`, 'o fluxo continua disponível após atualizar a página', 15000);
  await recordSends();
  await fakeSet({ imu_pose: 'upright' });
  await clickHas('.imu-coarse button', 'Coletar repouso');
  await waitFor(`/leituras de repouso coletadas/.test(document.querySelector('.imu-coarse')?.innerText || '')`, 'leituras de repouso coletadas novamente', 15000);
  await fakeSet({ imu_pose: 'nose_down' });
  await waitFor(`!![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.includes('inclinação frontal') && !b.disabled)`, 'botão de coleta frontal habilitado');
  if (!await clickHas('.imu-coarse button', 'inclinação frontal')) throw new Error('A coleta da inclinação frontal não foi iniciada');
  await waitFor(`!!document.querySelector('.imu-coarse input[type=checkbox]')`, 'orientação de montagem recalculada', 20000);
  out.verifyInstruction = await js(`document.querySelector('.imu-coarse')?.innerText`);
  await js(`[...document.querySelectorAll('.imu-coarse input[type=checkbox]')].forEach((x) => { if (!x.checked) x.click(); })`);
  await fakeSet({ imu_pose: 'upright', imu_verify_plan: 'ok' });
  await waitFor(`!![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent === 'Solicitar validação do programa principal' && !b.disabled)`, 'botão de validação habilitado');
  if (!await clickHas('.imu-coarse button', 'Solicitar validação do programa principal')) throw new Error('A validação não foi enviada');
  await waitFor(`/Modo de movimento/.test(document.querySelector('.topbar')?.innerText || document.querySelector('header')?.innerText || '') &&
    !![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.trim() === 'Recalibrar orientação' && !b.disabled)`, 'nova orientação validada e modo de movimento restaurado', 45000);
  out.after = await fakeRpc('robot.busCommand', { action: 'calibration-status' });
  out.afterStance = await stance();
  out.motionCommands = await js(`(window.__sent || []).filter((m) => m.name === 'pad.op' || m.name === 'init' || (m.name === 'imu.op' && m.args.op === 'hold'))`);
  await shot('imu-redo-complete.png');
  // É possível cancelar uma segunda recalibração e restaurar exatamente a calibração salva.
  await clickExact('.imu-coarse button', 'Recalibrar orientação');
  await sleep(900);
  await js(`document.querySelector('.imu-coarse .two-step-ask').click()`);
  await waitFor(`/A recalibração ainda não terminou/.test(document.querySelector('.imu-coarse')?.innerText || '')`, 'segunda recalibração iniciada', 15000);
  await waitFor(`!![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent === 'Cancelar e restaurar parâmetros' && !b.disabled)`, 'botão de cancelamento habilitado');
  if (!await clickExact('.imu-coarse button', 'Cancelar e restaurar parâmetros')) throw new Error('O cancelamento não foi iniciado');
  await sleep(900);
  await js(`document.querySelector('.imu-coarse .two-step-ask').click()`);
  await waitFor(`/Modo de movimento/.test(document.querySelector('.topbar')?.innerText || '') &&
    !![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.trim() === 'Recalibrar orientação' && !b.disabled)`, 'modo anterior restaurado após o cancelamento', 15000);
  out.cancelled = await fakeRpc('robot.busCommand', { action: 'calibration-status' });
  out.recoveredPhases = [];
  for (const phase of ['entering', 'finishing', 'cancelling']) {
    await clickExact('.imu-coarse button', 'Recalibrar orientação');
    await sleep(900);
    await js(`document.querySelector('.imu-coarse .two-step-ask').click()`);
    await waitFor(`/A recalibração ainda não terminou/.test(document.querySelector('.imu-coarse')?.innerText || '') &&
      !![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.includes('Coletar repouso') && !b.disabled)`, 'recalibração iniciada');
    writeFileSync(CONTROL, JSON.stringify({ outcome: 'ok', redo_phase: phase }));
    await send('Page.reload');
    await waitFor(`/A recalibração ainda não terminou/.test(document.querySelector('.imu-coarse')?.innerText || '') &&
      !document.querySelector('.imu-coarse-steps') &&
      !![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent === 'Cancelar e restaurar parâmetros' && !b.disabled)`, `sessão ${phase} interrompida pode ser cancelada`, 6000);
    await clickExact('.imu-coarse button', 'Cancelar e restaurar parâmetros');
    await sleep(900);
    await js(`document.querySelector('.imu-coarse .two-step-ask').click()`);
    await waitFor(`/Modo de movimento/.test(document.querySelector('.topbar')?.innerText || '') &&
      !![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent === 'Recalibrar orientação' && !b.disabled)`, 'modo de movimento anterior restaurado');
    out.recoveredPhases.push(phase);
    writeFileSync(CONTROL, JSON.stringify({ outcome: 'ok' }));
  }
  // Instalações já confirmadas no modo de calibração também mantêm uma opção direta de validação.
  await fakeSet({ mode: 'commissioning', imu_pose: 'upright' });
  await waitFor(`/Modo de calibração/.test(document.querySelector('.topbar')?.innerText || '') &&
    !![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.trim() === 'Recalibrar orientação' && !b.disabled)`, 'opção de recalibração disponível no modo de calibração confirmado', 15000);
  await recordSends();
  await clickExact('.imu-coarse button', 'Recalibrar orientação');
  await sleep(900);
  await js(`document.querySelector('.imu-coarse .two-step-ask').click()`);
  await waitFor(`!![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.includes('Coletar repouso'))`, 'fluxo de calibração inicial reaberto', 5000);
  out.commissioningCommands = await js(`(window.__sent || []).filter((m) => m.name === 'imu.op')`);
}

if (PHASE === 'imu' || PHASE === 'imu-hold') {
  log('Página IMU: calibração inicial');
  if (PHASE === 'imu-hold') {
    await fakeSet({ mode: 'commissioning', calib: 'factory', posture: 'commissioning', imu_pose: 'upright', restart: 0.4 });
  }
  await js(`location.hash = '#/imu'`);
  await waitFor(`!!document.querySelector('.imu-coarse')`, 'cartão de calibração inicial da IMU', 20000);
  if (PHASE === 'imu-hold') {
    await waitFor(`!![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.includes('Coletar repouso') && !b.disabled)`,
      'estado de calibração inicial de fábrica carregado novamente', 20000);
  }
  await js(`document.querySelector('.imu-stance .imu-relax').click()`);
  await sleep(500);
  if (PHASE === 'imu-hold') {
    await waitFor(`!!document.querySelector('.imu-stance .imu-stand') && !document.querySelector('.imu-stance .imu-stand').disabled`,
      'habilitação da postura em pé disponível para a calibração inicial', 10000);
    await js(`document.querySelector('.imu-stance .imu-stand').click()`);
    await waitFor(`/Modo de calibração \(em pé\)/.test(document.querySelector('.imu-stance .imu-stance-now')?.innerText || '')`,
      'robô estabilizado em pé para a calibração inicial', 15000);
    out.holdBefore = await fakeRpc('robot.busStatus', {});
  }
  out.start = await js(`document.querySelector('.imu-coarse')?.innerText.replace(/\\s+/g, ' ').slice(0, 500)`);
  if (!await clickHas('.imu-coarse button', 'Coletar repouso')) throw new Error('Botão Coletar repouso não encontrado');
  await waitFor(`/leituras de repouso coletadas/.test(document.querySelector('.imu-coarse')?.innerText || '')`, 'coleta de repouso concluída', 20000);
  await fakeSet({ imu_pose: 'nose_down' });
  await waitFor(`!![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent.includes('inclinação frontal') && !b.disabled)`,
    'coleta de repouso concluída; botão de inclinação frontal habilitado', 15000);
  if (!await clickHas('.imu-coarse button', 'inclinação frontal')) throw new Error('Botão de coleta frontal não encontrado');
  await waitFor(`!!document.querySelector('.imu-coarse input[type=checkbox]') || /Solicitar validação do programa principal/.test(document.querySelector('.imu-coarse')?.innerText || '')`,
    'orientação calculada; aguardando confirmação', 25000);
  await js(`[...document.querySelectorAll('.imu-coarse input[type=checkbox]')].forEach((x) => { if (!x.checked) x.click(); })`);
  await fakeSet({ imu_verify_plan: 'ok' });        // Roteiro de desenvolvimento: o programa principal primeiro detecta o robô nivelado e depois inclinado para frente.
  await waitFor(`!![...document.querySelectorAll('.imu-coarse button')].find((b) => b.textContent === 'Solicitar validação do programa principal' && !b.disabled)`, 'botão de validação da calibração inicial habilitado');
  if (!await clickHas('.imu-coarse button', 'Solicitar validação do programa principal')) throw new Error('Botão de validação não encontrado');
  // Após a verificação, verified fica true no programa principal e o cartão de calibração inicial recolhe; confira o estado no topo da página da IMU.
  await waitFor(`/Orientação confirmada/.test(document.querySelector('.sv-metrics')?.innerText || '')`,
    'verificação da IMU aprovada', 40000);
  out.imu = await js(`[document.querySelector('.sv-metrics')?.innerText || '',
    document.querySelector('.imu-coarse')?.innerText || ''].filter(Boolean).join(' ／ ').replace(/\\s+/g, ' ').slice(0, 700)`);
  if (PHASE === 'imu-hold') {
    out.holdAfter = await fakeRpc('robot.busStatus', {});
    await shot('commit-imu-hold-verified.png');
    // Redefine o cenário simulado independentemente dos cartões que permaneceram montados após a verificação.
    await fakeRpc('robot.relax', {});
    for (let attempt = 0; attempt < 50; attempt++) {
      out.cleaned = await fakeRpc('robot.busStatus', {});
      if (out.cleaned.torque_state === 'off') break;
      await sleep(100);
    }
  } else await shot('commit-imu-verified.png');
}

if (PHASE === 'servo') {
  log('Página de servos: calibração em lote e devolução ao programa principal');
  await js(`location.hash = '#/servos'`);
  await waitFor(`/Ajustando servos/.test(document.querySelector('.sv-sub')?.innerText || '')`, 'página de servos assumiu o barramento (servos simulados)', 20000);
  if (!await clickExact('.sv-page button', 'Calibrar seleção')) throw new Error('Botão Calibrar seleção não encontrado');
  await waitFor(`!!document.querySelector('.sv-modal')`, 'prévia da calibração de posição zero', 15000);
  out.planRows = await js(`document.querySelectorAll('.sv-plan tbody tr').length`);
  if (!await clickHas('.sv-modal button', 'Confirmar calibração de 15 servos')) throw new Error('Botão de confirmação da calibração não encontrado');
  await waitFor(`/Calibração concluída: 15 servos calibrados/.test(document.body.innerText)`, 'posição zero dos 15 servos calibrada', 40000);
  if (!await clickHas('.sv-handback button', 'Devolver ao programa principal')) throw new Error('Botão Devolver ao programa principal não encontrado');
  await waitFor(`!!document.querySelector('.sv-handback .two-step-ask')`, 'segunda confirmação da devolução', 5000);
  await sleep(900);
  await js(`document.querySelector('.sv-handback .two-step-ask')?.click()`);
  await waitFor(`!/Ajustando servos/.test(document.querySelector('.sv-sub')?.innerText || '')`, 'devolução do controle concluída', 30000);
  out.servo = await js(`document.querySelector('.sv-sub')?.innerText.replace(/\\s+/g, ' ')`);
  await shot('commit-servo-done.png');
  await js(`location.hash = '#/'`);
}

if (PHASE === 'commit' || PHASE === 'fail') {
  await js(`location.hash = '#/'`);
  await waitFor(`!!${card}`, 'cartão da etapa 3, gravação no programa principal', 20000);
  await waitFor(`(() => { const c = ${card}; return c && c.querySelectorAll('.onb-checks li').length > 0; })()`, 'lista de preparação exibida', 20000);
  await waitFor(`(() => { const c = ${card}; const w = [...c.querySelectorAll('.onb-commit-acts button')]
    .find((b) => b.textContent.includes('Gravar no programa principal')); return w && !w.disabled; })()`, 'botão de gravação habilitado', 25000);
  out.ready = await snapshot();
  const writeBtn = `[...document.querySelectorAll('[data-step="commit"] .onb-commit-acts button')]
    .find((b) => b.textContent.includes('Gravar no programa principal'))`;
  await js(`${writeBtn}.click()`);
  await waitFor(`!!document.querySelector('[data-step="commit"] .two-step-ask')`, 'segunda confirmação da gravação', 5000);
  out.confirmText = await js(`document.querySelector('[data-step="commit"] .two-step-ask')?.textContent`);
  await sleep(900);       // Proteção de 700 ms do TwoStep.
  await js(`document.querySelector('[data-step="commit"] .two-step-ask').click()`);
  // Se a gravação for rápida, o resultado final pode substituir a confirmação (a etapa 3 pode até estar concluída e recolhida); aguarde a confirmação, o cartão de progresso ou a conclusão.
  await waitFor(`/Preparando para gravar|Gravando arquivo/.test(document.querySelector('[data-step="commit"] .onb-commit-msg')?.innerText || '') ||
    !!document.querySelector('[data-step="commit"] .onb-commit-job') ||
    document.querySelector('[data-step="commit"] .onb-mark')?.getAttribute('aria-label') === 'Concluído'`,
    'confirmação de início, cartão de progresso ou resultado final', 20000);
  out.started = await snapshot();

  if (PHASE === 'fail') {
    // O helper simulado reinicia o programa principal; o cartão de progresso da etapa 3 deve continuar visível durante a desconexão.
    let offline = null;
    const end = Date.now() + 25000;
    while (Date.now() < end) {
      const s = await js(`(() => { const c = document.querySelector('[data-step="commit"]'); if (!c) return null;
        return { text: c.innerText.replace(/\\s+/g, ' ').slice(0, 600), job: !!c.querySelector('.onb-commit-job'), msg: c.querySelector('.onb-commit-msg')?.innerText || null }; })()`);
      if (s && s.job && /programa principal está reiniciando|página está desconectada/.test(s.text)) { offline = s; break; }
      await sleep(200);
    }
    out.offline = offline;
    if (!offline) throw new Error('O cartão de progresso da etapa 3 não apareceu durante a desconexão');
    await shot('commit-fail-offline.png');
    await waitFor(`(() => { const m = document.querySelector('[data-step="commit"] .onb-commit-msg.bad');
      return /A calibração não passou na validação do programa principal/.test(m?.innerText || ''); })()`, 'motivo da falha', 30000);
    // O rollback reinicia o programa principal em modo de calibração; aguarde a reconexão e a leitura da calibração antes de validar a etapa 3.
    await waitFor(`document.querySelector('[data-step="commit"] .onb-mark')?.getAttribute('aria-label') === 'Pendente'`,
      'etapa 3 volta a ficar pendente após o retorno do programa principal', 30000);
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
    await waitFor(`document.querySelector('[data-step="commit"] .onb-mark')?.getAttribute('aria-label') === 'Concluído'`,
      'etapa 3 concluída após a mudança simulada para o modo de movimento', 40000);
    await waitFor(`/Modo de movimento/.test(document.querySelector('.topbar .meta')?.innerText || '')`, 'modo de movimento exibido no topo', 15000);
    out.done = await snapshot();
    out.topbar = await js(`document.querySelector('.topbar .meta')?.innerText`);
    await shot('commit-done.png');
  }
}

if (PHASE === 'factory') {
  await waitFor(`!!${card}`, 'cartão da etapa 3, gravação no programa principal', 20000);
  await waitFor(`(() => { const c = ${card}; return c && c.querySelectorAll('.onb-checks li').length > 0; })()`, 'lista de preparação exibida', 15000);
  out.factory = await snapshot();
  await shot('commit-factory.png');
  await js(`[...document.querySelectorAll('[data-step="commit"] .onb-commit-acts button')]
    .find((b) => b.textContent.includes('Ver prévia da gravação'))?.click()`);
  await waitFor(`!!document.querySelector('[data-step="commit"] .onb-preview')`, 'prévia expandida', 20000);
  out.preview = await js(`(() => {
    const p = document.querySelector('[data-step="commit"] .onb-preview');
    return { jointRows: p.querySelectorAll('.onb-preview-table tbody tr').length,
      imu: p.querySelector('.onb-preview-imu')?.innerText || '',
      toml: (p.querySelector('pre')?.textContent || '').slice(0, 4000) };
  })()`);
  await shot('commit-preview.png');
}

log('Finalização');
out.errors = errors;
process.stdout.write(JSON.stringify(out));
await new Promise((r) => process.stdout.write('', r));
ws.close();
await fetch(`http://127.0.0.1:${CDP}/json/close/${page.id}`);
