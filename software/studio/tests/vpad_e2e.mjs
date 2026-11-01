// Teste ponta a ponta do controle virtual: conecta ao Edge local sem interface (CDP), abre a página do controle no Studio (robotd simulado reproduz os dados da réplica 2),
// clica nos botões do desenho, arrasta os analógicos, usa o teclado e arrasta dois analógicos com dois dedos no celular; depois confere os registros do robotd simulado.
// Os resultados são enviados em JSON para stdout e verificados por tests/test_vpad_e2e.py. A página e o backend do Studio são reais; somente o robotd é simulado.
//
// Execução isolada (inicie antes o robotd simulado, o Studio e o Edge sem interface; use portas livres):
//   node tests/vpad_e2e.mjs --url http://127.0.0.1:18090/#/pad --cdp 9343 --record <rd.jsonl> --fake 17022 [--shots <diretório de capturas>]
// Node ≥ 22 (inclui WebSocket); não é necessário instalar pacotes.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import net from 'node:net';

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const URL_ = arg('url');
const CDP = arg('cdp');
const REC = arg('record');
const FAKE = Number(arg('fake'));
const SHOTS = arg('shots', '');
if (SHOTS) mkdirSync(SHOTS, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => process.stderr.write(`[vpad-e2e] ${a.join(' ')}\n`);

// ---------------- Registros do robotd simulado ----------------
// Ignora as consultas normais do Studio (estado, mapeamentos etc.); registra somente comandos de movimento e som.
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

// ---------------- CDP ----------------
// Abre uma nova aba para evitar que a área visível de outra sessão seja alterada.
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
  if (m.method === 'Page.javascriptDialogOpening') { errors.push(`Caixa de diálogo: ${m.params.message}`); send('Page.handleJavaScriptDialog', { accept: true }); }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; waiting.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(`Erro na página: ${r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text}`);
  return r.result?.result?.value;
};
const waitFor = async (expr, what, timeout = 6000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(expr)) return true; await sleep(100); }
  const now = await js(`[document.visibilityState, document.hasFocus(), document.querySelector('.pd-vbar')?.textContent, document.querySelector('.pd-pose')?.textContent,
    [...document.querySelectorAll('.pd-big')].map((b) => b.textContent).join(' | ')].join(' ／ ').replace(/\\s+/g, ' ')`);
  let fk = null;
  try { fk = (await fakeSet({})).result?.posture; } catch { /* robotd simulado indisponível */ }
  throw new Error(`Tempo esgotado após ${timeout / 1000} s aguardando ${what}. Conteúdo atual da página: ${now}; postura do robotd simulado: ${fk}`);
};
const vbar = () => js(`document.querySelector('.pd-vbar')?.textContent?.replace(/\\s+/g, ' ') || ''`);
// Centro do elemento, após rolá-lo para o meio da tela.
const box = (sel) => js(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null;
  e.scrollIntoView({ block: 'center', inline: 'nearest' }); const r = e.getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height }; })()`);
const key = (r) => `.pd-svg-live [data-role="${r}"]`;
const mouse = (type, x, y, buttons = 1) => send('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons, clickCount: 1 });
async function hold(sel, ms, during) {
  const b = await box(sel);
  if (!b) throw new Error(`Elemento não encontrado: ${sel}`);
  await mouse('mouseMoved', b.x, b.y, 0);
  await mouse('mousePressed', b.x, b.y);
  if (during) await during();
  await sleep(ms);
  await mouse('mouseReleased', b.x, b.y, 0);
}
// Arrasta o analógico: pressiona em (centro + off), move em etapas até +d, aguarda ms e solta.
async function drag(sel, d, ms, { off = [0, 0], during } = {}) {
  const b = await box(sel);
  const x0 = b.x + off[0], y0 = b.y + off[1];
  await mouse('mouseMoved', x0, y0, 0);
  await mouse('mousePressed', x0, y0);
  for (let i = 1; i <= 5; i++) { await mouse('mouseMoved', x0 + (d[0] * i) / 5, y0 + (d[1] * i) / 5); await sleep(20); }
  if (during) await during();
  await sleep(ms);
  await mouse('mouseReleased', x0 + d[0], y0 + d[1], 0);
}
async function shot(name, sel, toSel) {
  if (!SHOTS) return;
  let clip;
  if (toSel) {                                     // Captura do topo de sel até a base de toSel.
    const r = await js(`(() => { const a = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect();
      const b = document.querySelector(${JSON.stringify(toSel)}).getBoundingClientRect();
      return { x: a.x + scrollX - 8, y: a.y + scrollY - 8, width: a.width + 16, height: b.bottom - a.y + 16 }; })()`);
    clip = { ...r, scale: 1 };
  } else if (sel === 'full') {
    const h = await js('Math.ceil(document.documentElement.scrollHeight)');
    const w = await js('document.documentElement.clientWidth');
    clip = { x: 0, y: 0, width: w, height: h, scale: 1 };
  } else if (sel) {
    const r = await js(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); const r = e.getBoundingClientRect();
      return { x: r.x + scrollX - 8, y: r.y + scrollY - 8, width: r.width + 16, height: r.height + 16 }; })()`);
    clip = { ...r, scale: 1 };
  }
  const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: !!clip, ...(clip ? { clip } : {}) });
  writeFileSync(join(SHOTS, name), Buffer.from(r.result.data, 'base64'));
  log('captura de tela', name);
}
async function open(w, h, mobile) {
  // Uma nova aba do Edge sem interface pode ser considerada em segundo plano, fazendo a página informar visible:false e o Studio parar de enviar estados. Traz a aba à frente e simula o foco.
  await send('Page.bringToFront');
  await send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: mobile ? 2 : 1, mobile });
  await send('Emulation.setTouchEmulationEnabled', { enabled: !!mobile, maxTouchPoints: mobile ? 5 : 1 });
  await send('Page.navigate', { url: 'about:blank' });
  await sleep(300);
  await send('Page.navigate', { url: URL_ });
  await waitFor(`!!document.querySelector('.pd-svg-live [data-role="start"]')`, 'desenho do controle carregado');
  await waitFor(`/Ação de Start: [^—]/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'estado recebido pela página do controle');
  await sleep(600);
}

// Apenas para as duas capturas em modo espelhado: sem o padd no computador, o desenho não mostraria as entradas do controle físico. Quando window.__fakeLive está definido,
// substitui live nas mensagens {t:'pad'} por entradas simuladas do controle (altera somente a exibição; o backend consulta pad.status do configd simulado).
const INJECT = `(() => {
  const NWS = window.WebSocket;
  class W extends NWS {
    set onmessage(fn) {
      super.onmessage = (ev) => {
        let d = ev.data;
        if (window.__fakeLive && typeof d === 'string' && d.startsWith('{"t":"pad"')) {
          try { const m = JSON.parse(d); m.live = window.__fakeLive; d = JSON.stringify(m); } catch (e) { /* mantém a mensagem original */ }
        }
        fn({ data: d });
      };
    }
    get onmessage() { return super.onmessage; }
  }
  window.WebSocket = W;
})();`;
const FAKE_LIVE = JSON.stringify({ state: 'attached', last_ms: 20, other: [], buttons: { south: true, lt: true },
  axes: { lx: 0.45, ly: -0.7, rx: -0.6, ry: 0, lt: 0.8, rt: 0 },
  device: { name: 'Xbox Wireless Controller', kind: 'xbox', bus: 'Bluetooth', keys_unverified: false } });
await send('Runtime.enable');
await send('Page.enable');
await send('Page.addScriptToEvaluateOnNewDocument', { source: INJECT });
const out = { steps: {}, errors };
async function step(name, fn, settle = 500) {
  since();
  const extra = (await fn()) || {};
  await sleep(settle);
  out.steps[name] = { recs: since(), ...extra };
  log(name, out.steps[name].recs.length, 'registros');
}

// ================= Largura de computador =================
await open(1280, 900, false);
await shot('desktop-1-idle.png');
out.start0 = await vbar();

// O analógico é relativo: o ponto inicial do toque é o centro; apenas pressionar sem mover não desloca o robô (revisão 3 V2).
await step('stick_press_only', () => drag(key('ls'), [0, 0], 300, { off: [12, 0] }));
// Arrastar o analógico esquerdo para cima faz o robô andar (vx > 0); soltar envia um único comando 0.
await step('stick_drag', () => drag(key('ls'), [0, -40], 600));
// A: abaixa a cabeça para pegar um objeto (solicitação robot.do).
await step('key_a', () => hold(key('south'), 80), 700);
// Manter X pressionado: envia uma solicitação e depois notificações repetidas (rolagem contínua).
await step('x_hold', () => hold(key('west'), 800), 600);
// Manter LT pressionado abre a boca e mantém wheee; soltar fecha a boca e interrompe o som (captura enquanto o botão está pressionado).
await step('lt_hold', () => hold(key('lt'), 600, async () => {
  await sleep(250);
  const b = await box(key('ls'));
  await shot('desktop-2-pressed.png', '.pd-live', '.pd-vbar');
  return b;
}), 700);
// Tocar RT uma vez: emite um grasnado.
await step('rt_tap', () => hold(key('rt'), 120), 600);
// Y: modo cabeça; mover o analógico direito para cima inclina o pescoço (neck_pitch positivo); ao soltar, centraliza a cabeça; pressione Y novamente para voltar à caminhada.
await step('head', async () => {
  await hold(key('north'), 80);
  await waitFor(`/Analógicos: modo cabeça/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'modo cabeça ativado');
  await drag(key('rs'), [0, -40], 500, { during: () => shot('desktop-3-head.png', '.pd-live', '.pd-vbar') });
  await sleep(300);
  await hold(key('north'), 80);
  await waitFor(`/Analógicos: caminhada/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'modo caminhada restaurado');
  return { bar: await vbar() };
});
// B: modo corpo; mover o analógico esquerdo para baixo agacha (z < 0); ao soltar, volta ao centro sem sair do modo; pressione B novamente para sair (active:false).
await step('body', async () => {
  await hold(key('east'), 80);
  await waitFor(`/Analógicos: modo corpo/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'modo corpo ativado');
  await drag(key('ls'), [0, 40], 400);
  await sleep(300);
  await hold(key('east'), 80);
  await waitFor(`/Analógicos: caminhada/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'modo caminhada restaurado');
});
// Teclado: W não move antes de clicar no desenho; depois que a área do controle recebe foco, W move o robô; as setas não o movem (revisão 3 V2).
await step('keyboard_unfocused', async () => {
  await js('document.activeElement && document.activeElement.blur()');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87 });
  await sleep(300);
  await send('Input.dispatchKeyEvent', { type: 'keyUp', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87 });
});
await step('keyboard', async () => {
  const b = await box('.pd-svgzone');
  await mouse('mousePressed', b.x, b.y - b.h * 0.42);               // Clica na área vazia acima do desenho, não em um botão.
  await mouse('mouseReleased', b.x, b.y - b.h * 0.42, 0);
  const focused = await js(`document.activeElement?.classList.contains('pd-zone')`);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87 });
  await sleep(200);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87, autoRepeat: true });
  await sleep(250);
  await send('Input.dispatchKeyEvent', { type: 'keyUp', code: 'KeyW', key: 'w', windowsVirtualKeyCode: 87 });
  await sleep(300);
  const n = since();
  await send('Input.dispatchKeyEvent', { type: 'keyDown', code: 'ArrowUp', key: 'ArrowUp', windowsVirtualKeyCode: 38 });
  await sleep(300);
  await send('Input.dispatchKeyEvent', { type: 'keyUp', code: 'ArrowUp', key: 'ArrowUp', windowsVirtualKeyCode: 38 });
  return { focused, w_recs: n };
});
// Se a janela perder o foco enquanto o analógico estiver pressionado, o movimento para imediatamente e não recomeça enquanto ele continuar pressionado.
await step('blur', async () => {
  const b = await box(key('ls'));
  await mouse('mouseMoved', b.x, b.y, 0);
  await mouse('mousePressed', b.x, b.y);
  for (let i = 1; i <= 5; i++) { await mouse('mouseMoved', b.x, b.y - 8 * i); await sleep(20); }
  await sleep(400);
  const before = since();
  await js(`window.dispatchEvent(new Event('blur'))`);
  await sleep(150);
  const atBlur = since();
  await mouse('mouseMoved', b.x, b.y - 45);
  await sleep(500);
  const after = since();
  await mouse('mouseReleased', b.x, b.y - 45, 0);
  return { before, atBlur, after };
});
// Start: enquanto anda ou está pronto para andar, para e fica em pé; após o robotd simulado indicar que está parado em pé, começa a andar.
await step('start_stop', () => hold(key('start'), 80), 900);
await waitFor(`/Ação de Start: Começar a andar/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'Start passa a começar a andar');
await step('start_walk', () => hold(key('start'), 80), 900);
await waitFor(`/Ação de Start: Parar \(ficar em pé\)/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'Start passa a parar');
// Select no desenho = parada de emergência: desenergiza ao pressionar, sem esperar soltar.
await step('select', async () => {
  const b = await box(key('select'));
  await mouse('mouseMoved', b.x, b.y, 0);
  await mouse('mousePressed', b.x, b.y);
  await sleep(250);
  const whilePressed = since();
  await mouse('mouseReleased', b.x, b.y, 0);
  await waitFor(`!!document.querySelector('.estop.done')`, 'desenergização confirmada');
  return { whilePressed };
}, 400);
await fakeSet({ posture: 'policy' });
await sleep(2600);                                                     // Aguarda o período de proteção de 2 s após desenergizar.
// Direcional para cima: menos de 3 s não alterna; após 3 s envia robot.setMode. Primeiro o robotd simulado não tem o modelo de rodas; depois da instalação, alterna entre Rodas e Andar.
const vmsg = () => js(`document.querySelector('.pd-vmsg')?.textContent || ''`);
const duSays = (word) => `(document.querySelector('${key('du')} title')?.textContent || '').includes(${JSON.stringify(word)})`;
await step('dpad_up_short', () => hold(key('du'), 1000), 300);
out.du_short = await vmsg();
await step('dpad_up_refused', async () => {
  await hold(key('du'), 3400);
  await waitFor(`/modelo.*Rodas/.test(document.querySelector('.pd-vmsg')?.textContent || '')`, 'página informa que o modelo de rodas não está instalado');
}, 300);
await fakeSet({ roller_models: true });
await step('dpad_up_hold', async () => {
  await hold(key('du'), 3400);
  await waitFor(`/Alternou para modo de rodas/.test(document.querySelector('.pd-vmsg')?.textContent || '')`, 'página informa a mudança para o modo de rodas');
}, 300);
await waitFor(duSays('alternar para Andar'), 'direcional passa a alternar para Andar (robot.policies consultado a cada 2 s)');
await step('dpad_up_back', async () => {
  await hold(key('du'), 3400);
  await waitFor(`/Alternou para caminhada/.test(document.querySelector('.pd-vmsg')?.textContent || '')`, 'página informa a mudança para caminhada');
}, 300);
await fakeSet({ roller_models: false });
// Direcional para a direita: envia robot.rebootMotors ao pressionar, sem confirmação; em seguida, o robô relaxa o torque.
await step('dpad_right', async () => {
  await hold(key('dr'), 80);
  await waitFor(`/Reinicialização dos servos enviada/.test(document.querySelector('.pd-vmsg')?.textContent || '')`, 'página confirma o envio da reinicialização dos servos');
}, 300);
await fakeSet({ posture: 'policy' });
await sleep(2600);
// Ao sair da página com o modo corpo ativo, o modo deve ser encerrado (active:false). Como o controle também aparece na visão geral, #/ não conta como saída;
// abre a página de registros para sair de verdade. A reorganização da visão geral (O1) e a saída da área visível são cobertas em tests/overview_e2e.mjs.
await step('leave_page', async () => {
  await hold(key('east'), 80);
  await waitFor(`/Analógicos: modo corpo/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'modo corpo ativado');
  await drag(key('ls'), [0, -30], 300);
  await js(`location.hash = '#/logs'`);
  await sleep(600);
  await js(`location.hash = '#/pad'`);
  await waitFor(`/Ação de Start: [^—]/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'página do controle reaberta');
  await sleep(500);
});
// O analógico continua funcionando ao voltar à página do controle (drive open foi reativado após sair).
await step('back_again', () => drag(key('ls'), [0, -40], 400));
// Controle físico conectado (espelhamento): toques e arrastos no desenho não enviam comandos; Select ainda desenergiza.
await fakeSet({ pad_connected: true });
await waitFor(`!!document.querySelector('.pd-remote .banner') && /Controle físico conectado/.test(document.querySelector('.pd-remote')?.textContent || '')`, 'modo espelhado', 8000);
await step('mirror', async () => {
  await hold(key('south'), 80);
  await drag(key('ls'), [0, -40], 400);
  await hold(key('north'), 80);
  await hold(key('lt'), 300);
  const bar = await vbar();
  await js(`window.__fakeLive = ${FAKE_LIVE}`);
  await sleep(400);
  await shot('desktop-4-mirror.png', '.pd-live', '.pd-vbar');
  await js('window.__fakeLive = null');
  return { bar };
});
await step('mirror_select', async () => {
  await hold(key('select'), 100);
  await waitFor(`!!document.querySelector('.estop.done')`, 'desenergização confirmada no modo espelhado');
}, 400);
await fakeSet({ pad_connected: false, posture: 'policy' });
await waitFor(`!/Controle físico conectado/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'modo espelhado encerrado', 8000);
await sleep(2600);

// ================= Largura de celular: 390 px =================
await open(390, 844, true);
out.phone = await js(`({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`);
await shot('phone-1-idle.png', 'full');
// Arrasta simultaneamente os dois analógicos com dois dedos (na tela de toque, pressione a área transparente .pd-ov-stick): esquerdo para cima (avançar), direito para a direita (virar).
await step('two_fingers', async () => {
  const [L, Rr] = await js(`(() => {
    const ls = document.querySelector('.pd-svgbox .pd-ov-stick[data-ov="ls"]');
    const rs = document.querySelector('.pd-svgbox .pd-ov-stick[data-ov="rs"]');
    ls.scrollIntoView({ block: 'center', inline: 'nearest' });
    const a = ls.getBoundingClientRect(), b = rs.getBoundingClientRect();
    return [{ x: a.x + a.width / 2, y: a.y + a.height / 2 }, { x: b.x + b.width / 2, y: b.y + b.height / 2 }];
  })()`);
  await sleep(650);                    // Ignora toques nos primeiros 0,5 s após a rolagem, evitando acionamentos durante a inércia (revisão O2 da visão geral).
  const pts = (dy, dx) => [{ x: L.x, y: L.y - dy, id: 1 }, { x: Rr.x + dx, y: Rr.y, id: 2 }];
  await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: pts(0, 0) });
  for (let i = 1; i <= 5; i++) { await send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: pts(9 * i, 9 * i) }); await sleep(30); }
  await sleep(500);
  await shot('phone-2-two-sticks.png', '.pd-svgzone');
  await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
});
// Toca em Y no celular para ativar o modo cabeça.
await step('phone_head', async () => {
  const b = await box(key('north'));
  await sleep(650);                    // Como acima: aguarda 0,5 s após a rolagem antes de tocar.
  await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: b.x, y: b.y, id: 3 }] });
  await sleep(80);
  await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await waitFor(`/Analógicos: modo cabeça/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'modo cabeça ativado no celular');
  await shot('phone-3-head.png', '.pd-live', '.pd-vbar');
  await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: b.x, y: b.y, id: 4 }] });
  await sleep(80);
  await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await waitFor(`/Analógicos: caminhada/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'modo caminhada restaurado no celular');
});
await fakeSet({ pad_connected: true });
await waitFor(`/Controle físico conectado/.test(document.querySelector('.pd-vbar')?.textContent || '')`, 'modo espelhado no celular', 8000);
await js(`window.__fakeLive = ${FAKE_LIVE}`);
await sleep(400);
await shot('phone-4-mirror.png', '.pd-live', '.pd-vbar');
await js('window.__fakeLive = null');
out.phone_mirror = await js(`({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`);
await fakeSet({ pad_connected: false });

process.stdout.write(JSON.stringify(out));
ws.close();
await fetch(`http://127.0.0.1:${CDP}/json/close/${page.id}`);
