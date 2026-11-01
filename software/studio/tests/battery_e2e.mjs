// Teste ponta a ponta da bateria (battery-plan.md v2 §5 e §4): conecta ao Edge local sem interface (CDP) e abre o Studio (robotd simulado reproduz o segundo Microduck e o roteiro da bateria;
// o estimador do Studio avança 20 vezes mais rápido). Verifica os estados do indicador da bateria na Visão geral, os detalhes e as tarefas; depois altera os limites nas configurações,
// calibra a leitura e seleciona a fonte de bancada. Os resultados são enviados em JSON para stdout e conferidos por tests/test_battery_e2e.py.
// Execução isolada (inicie antes o robotd simulado, o Studio com STUDIO_BATTERY_SPEED=20 e o Edge sem interface):
//   node tests/battery_e2e.mjs --url http://127.0.0.1:18103/ --cdp 9353 --fake 17056 [--shots <diretório-de-capturas>]
// Node ≥ 22 (inclui WebSocket); não é necessário instalar pacotes.
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
  if (r.result?.exceptionDetails) throw new Error(`Erro na página: ${r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text}`);
  return r.result?.result?.value;
};
const cellText = () => js(`(document.querySelector('.bat-cell')?.innerText || '').replace(/\\s+/g, ' ').trim()`);
const waitFor = async (expr, what, timeout = 15000, every = 100) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(expr)) return true; await sleep(every); }
  throw new Error(`Tempo esgotado após ${timeout / 1000} s aguardando ${what}. Indicador da bateria: ${await cellText()} / tarefas: ${await js(`document.querySelector('.todo')?.innerText?.replace(/\\s+/g, ' ')`)}`);
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
// Captura os limites externos dos elementos em sels (a janela de detalhes usa posição absoluta e é capturada junto com o indicador).
async function shot(name, ...sels) {
  if (!SHOTS) return;
  const r = await js(`(() => { const rs = ${JSON.stringify(sels)}.map((s) => document.querySelector(s)).filter(Boolean).map((e) => e.getBoundingClientRect());
    if (!rs.length) return null;
    const l = Math.min(...rs.map((r) => r.left)), t = Math.min(...rs.map((r) => r.top)), R = Math.max(...rs.map((r) => r.right)), B = Math.max(...rs.map((r) => r.bottom));
    return { x: l + scrollX - 8, y: t + scrollY - 8, width: R - l + 16, height: B - t + 16 }; })()`);
  const res = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, ...(r ? { clip: { ...r, scale: 1 } } : {}) });
  writeFileSync(join(SHOTS, name), Buffer.from(res.result.data, 'base64'));
  log('captura', name);
}
const mode = (m) => `document.querySelector('.bat-cell')?.dataset.mode === ${JSON.stringify(m)}`;
const todoText = () => js(`(document.querySelector('.todo')?.innerText || '').replace(/\\s+/g, ' ')`);
// Com o estimador 20x, 10 s sem leitura equivalem a 0,5 s reais e reiniciam o cálculo. Isso limpa o histórico anterior de cinco minutos para começar com uma nova tensão.
async function restart(battery) {
  await fakeSet({ battery: { gone: true } });
  await waitFor(mode('no_data'), 'leitura de tensão indisponível', 8000);
  await fakeSet({ battery: { gone: false, sag: 0, ...battery } });
}

const out = { errors, steps: {} };

// ---- 1. Visão geral: repouso a 7,62 V ----
// Studio may have accumulated the recorded fixture's 7.54 V while Edge was
// starting. Explicitly clear that history before testing the scripted 7.62 V.
await fakeSet({ battery: { gone: true } });
await open('#/');
await waitFor(`!!document.querySelector('.bat-cell') && !!document.querySelector('.band-cpu')`, 'carregamento da Visão geral');
await waitFor(mode('no_data'), 'limpeza das amostras de bateria acumuladas durante a inicialização', 8000);
await fakeSet({ battery: { v: 7.62, sag: 0, gone: false } });
await waitFor(mode('calm'), 'leitura do indicador da bateria');
await sleep(400);
out.steps.calm = { text: await cellText(), cls: await js(`document.querySelector('.bat-cell').className`) };
await shot('battery-calm.png', '.band');

// ---- 2. Abra os detalhes para ver como o cálculo é feito ----
await js(`document.querySelector('.bat-hit').click()`);
await waitFor(`!!document.querySelector('.bat-pop')`, 'abertura dos detalhes');
out.steps.detail = { lines: await js(`[...document.querySelectorAll('.bat-pop li')].map((l) => l.textContent)`),
  expanded: await js(`document.querySelector('.bat-hit').getAttribute('aria-expanded')`) };
await shot('battery-detail.png', '.band', '.bat-pop');
await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
await waitFor(`!document.querySelector('.bat-pop')`, 'fechamento com Esc');

// ---- 3. Sem leitura → reinicia no estado “Estimando” ----
await fakeSet({ battery: { gone: true } });
await waitFor(mode('no_data'), 'leitura de tensão indisponível', 8000);
out.steps.nodata = { text: await cellText() };
await shot('battery-nodata.png', '.band');
await fakeSet({ battery: { gone: false, v: 7.40 } });
await waitFor(mode('estimating'), 'estado de estimativa em andamento', 8000, 40);
out.steps.estimating = { text: await cellText(), todo: await todoText() };
await shot('battery-estimating.png', '.band');

// ---- 4. Aviso amarelo: 7,40 V (cerca de 28%) ----
await waitFor(`document.querySelector('.bat-cell')?.classList.contains('warn')`, 'faixa amarela', 15000);
out.steps.warn = { text: await cellText(), todo: await todoText() };
await shot('battery-warn.png', '.band', '.todo');

// ---- 5. Aviso crítico vermelho: 7,15 V (cerca de 9%) ----
await restart({ v: 7.15 });
await waitFor(`document.querySelector('.bat-cell')?.classList.contains('bad') && /Restam cerca de/.test(document.querySelector('.todo')?.innerText || '')`, 'limite crítico', 15000);
out.steps.red = { text: await cellText(), todo: await todoText() };
await shot('battery-red.png', '.band', '.todo');

// ---- 6. Tensão muito baixa: a carga reduz a tensão para cerca de 6,8 V ----
await restart({ v: 7.60 });
await waitFor(mode('calm'), 'retomada das leituras');
await fakeSet({ battery: { sag: 0.8 } });
await waitFor(`/Tensão muito baixa/.test(document.querySelector('.todo')?.innerText || '')`, 'alerta de tensão muito baixa', 15000);
out.steps.lowvolt = { text: await cellText(), todo: await todoText(), badge: await js(`!!document.querySelector('.bat-cell .badge.bad')`) };
await shot('battery-lowvolt.png', '.band', '.todo');
await fakeSet({ battery: { sag: 0 } });

// ---- 7. Largura de celular: indicador e detalhes sem rolagem horizontal ----
await restart({ v: 7.62 });
await open('#/', 390, 844, true);
await waitFor(mode('calm'), 'leitura da bateria no celular');
await js(`document.querySelector('.bat-hit').click()`);
await waitFor(`!!document.querySelector('.bat-pop')`, 'abertura dos detalhes no celular');
out.steps.mobile = await js(`({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
  popRight: Math.round(document.querySelector('.bat-pop').getBoundingClientRect().right) })`);
await shot('battery-mobile.png', '.band', '.bat-pop');

// ---- 8. Configurações: seção da bateria ----
await open('#/settings');
await waitFor(`!!document.querySelector('.bset input[name=bat-preset]')`, 'seção da bateria nas configurações');
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
// Valor inválido: limite crítico de 28% (não fica pelo menos 5 pontos abaixo do limite de aviso de 30%).
await setNum('red_pct', 28);
await clickBtn('Salvar');
await waitFor(`/não está pelo menos 5% abaixo/.test(document.querySelector('.bset').innerText)`, 'recusa do valor inválido');
out.steps.bad = { msg: await bmsg() };
await setNum('red_pct', 20);
await clickBtn('Salvar');
await waitFor(`/Salvo e aplicado imediatamente/.test(document.querySelector('.bset').innerText)`, 'salvamento das configurações');
out.steps.saved = { msg: await bmsg(), logs: (await studioLogs()).filter((m) => /Limite crítico/.test(m)) };
// Medição da tensão da bateria: robô em repouso, sem torque (o robotd simulado já inicia sem torque)
await sleep(2500);
await setNum('Leitura do multímetro', 7.80);
await clickBtn('Calcular');
await waitFor(`/Aplicar esta calibração/.test(document.querySelector('.bset').innerText) || /Desative o torque/.test(document.querySelector('.bset').innerText)`, 'resultado da calibração');
out.steps.calc = { msg: await bmsg(), text: await js(`document.querySelector('.bset').innerText.replace(/\\s+/g, ' ')`) };
await shot('settings-calibrate.png', '.bset');
await clickBtn('Aplicar esta calibração');
await waitFor(`/Salvo e aplicado imediatamente/.test(document.querySelector('.bset').innerText) && /calibração \\+0\\.18 V/.test(document.querySelector('.bset').innerText)`, 'salvamento da calibração', 8000);
out.steps.calibrated = { now: await js(`document.querySelector('.bset .now').textContent`) };

// ---- 9. Fonte de bancada ----
await js(`document.querySelector('.bset input[value=bench]').click()`);
await sleep(200);
out.steps.benchForm = { text: await js(`document.querySelector('.bset').innerText.replace(/\\s+/g, ' ')`) };
await clickBtn('Salvar');
await waitFor(`/Salvo e aplicado imediatamente/.test(document.querySelector('.bset').innerText) && /Fonte de bancada.*exibe somente a tensão/.test(document.querySelector('.bset .now').textContent)`, 'seleção da fonte de bancada');
await shot('settings-bench.png', '.bset');
await open('#/');
await waitFor(mode('bench'), 'indicador da fonte de bancada na Visão geral');
await sleep(400);
out.steps.bench = { text: await cellText(), todo: await todoText() };
// Os detalhes abertos na etapa do celular ainda podem estar visíveis (a navegação só troca o endereço e mantém a Visão geral montada); abra-os apenas se necessário.
await js(`document.querySelector('.bat-pop') || document.querySelector('.bat-hit').click()`);
await waitFor(`!!document.querySelector('.bat-pop')`, 'detalhes da fonte de bancada');
out.steps.bench.lines = await js(`[...document.querySelectorAll('.bat-pop li')].map((l) => l.textContent)`);
await shot('battery-bench.png', '.band', '.bat-pop');
// Finalização: restaura a bateria de lítio 2S para não deixar a fonte de bancada selecionada.
await open('#/settings');
await waitFor(`!!document.querySelector('.bset input[value="2s_liion"]')`, 'página de configurações');
await js(`document.querySelector('.bset input[value="2s_liion"]').click()`);
await sleep(200);
await clickBtn('Salvar');
await waitFor(`/Salvo e aplicado imediatamente/.test(document.querySelector('.bset').innerText)`, 'restauração da bateria de lítio 2S');
out.logs = (await studioLogs()).filter((m) => /bateria|tensão|carga/i.test(m)).slice(-40);

process.stdout.write(JSON.stringify(out));
ws.close();
await fetch(`http://127.0.0.1:${CDP}/json/close/${page.id}`);
