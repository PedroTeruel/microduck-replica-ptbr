// Teste ponta a ponta da configuração Wi-Fi (tarefa 10b): configd simulado grava net.json de hotspot, Studio real e Edge sem interface em largura de celular.
// Fluxo: cartão Wi-Fi aparece, escolha Home, informe senha incorreta, confirme, veja “Alternando” e o erro “Senha incorreta” na última tentativa.
// Os resultados são enviados em JSON para stdout e verificados por tests/test_wifi_e2e.py.
// Tarefa 17: após enviar a conexão, desconecte a página do robô; o cartão de busca consulta probe.svg de duck-fake e duck-fake.local a cada 2 s.
// Se a página reconectar ao endereço original, interrompa a busca e mantenha o motivo da falha; se encontrar o robô, navegue para o novo endereço.
// Simule a desconexão com um wrapper WebSocket injetado via Page.addScriptToEvaluateOnNewDocument: __cut redireciona novas conexões para uma porta fechada
// e encerra a conexão antiga. Como duck-fake não resolve, intercepte as sondagens via CDP Fetch e retorne erro ou uma imagem/página simulada.
// Execução isolada (inicie primeiro o robotd simulado, Studio e Edge sem interface):
//   node tests/wifi_e2e.mjs --url http://127.0.0.1:18091/ --cdp 9344 [--shots <diretório de capturas>]
// Requer Node >= 22 (WebSocket incluído); não precisa instalar pacotes.
import { writeFileSync, mkdirSync } from 'node:fs';
import { createServer } from 'node:net';
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
// Tarefa 17: intercepta as requisições duck-fake. probeMode=fail retorna “não encontrado”; found retorna uma imagem para duck-fake.local e uma página simulada após o redirecionamento.
const probes = [];
let probeMode = 'fail';
const PORT = new URL(BASE).port;
// Porta fechada para simular a desconexão: os novos WebSockets da página são direcionados para cá (não use uma porta como 9, bloqueada pelo navegador).
const DEAD = await new Promise((ok) => { const s = createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => ok(p)); }); });
const onPaused = (p) => {
  const url = p.request.url;
  probes.push(url);
  const svg = /\/probe\.svg\?t=\d+$/.test(url);
  if (probeMode === 'found' && url.startsWith(`http://duck-fake.local:${PORT}/`)) {
    const body = svg ? '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>' : '<!doctype html><title>found</title><p>found</p>';
    send('Fetch.fulfillRequest', { requestId: p.requestId, responseCode: 200,
      responseHeaders: [{ name: 'Content-Type', value: svg ? 'image/svg+xml' : 'text/html; charset=utf-8' }],
      body: Buffer.from(body).toString('base64') });
  } else {
    send('Fetch.failRequest', { requestId: p.requestId, errorReason: 'NameNotResolved' });
  }
};
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
  if (m.method === 'Fetch.requestPaused') onPaused(m.params);
  if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push(m.params.args.map((a) => a.value ?? a.description).join(' '));
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; waiting.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const js = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(`Erro na página: ${r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text}`);
  return r.result?.result?.value;
};
const waitFor = async (expr, what, timeout = 12000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await js(expr)) return true; await sleep(100); }
  const now = await js(`[location.hash, document.querySelector('.overview')?.innerText?.slice(0, 800),
    document.querySelector('.wifi-card')?.innerText?.slice(0, 500), document.querySelector('.wifi-last-try')?.innerText,
    document.querySelector('.wifi-msg')?.innerText].join(' ／ ')`);
  throw new Error(`Tempo esgotado após ${timeout / 1000} s aguardando ${what}. Conteúdo atual da página: ${now} / erros: ${JSON.stringify(errors)}`);
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
await send('Page.addScriptToEvaluateOnNewDocument', { source: `(() => {
  const Real = window.WebSocket;
  window.__ws = []; window.__cut = false;
  class Cuttable extends Real {
    constructor(url, p) { super(window.__cut ? 'ws://127.0.0.1:${DEAD}/cut' : url, p); window.__ws.push(this); }
  }
  window.WebSocket = Cuttable;
})()` });
await send('Fetch.enable', { patterns: [{ urlPattern: '*duck-fake*', requestStage: 'Request' }] });
await send('Page.navigate', { url: 'about:blank' });
await sleep(250);
await send('Page.navigate', { url: `${BASE}#/` });

const out = { errors };
await waitFor(`!!document.querySelector('.wifi-card')`, 'cartão Conectar ao Wi-Fi na visão geral', 15000);
await waitFor(`!!document.querySelector('.wifi-net[data-ssid="Home"]')`, 'rede Home na lista de redes');
out.card = await js(`({ text: document.querySelector('.wifi-card').innerText.replace(/\\s+/g, ' '),
  beforeOnboard: !!(document.querySelector('.wifi-card').compareDocumentPosition(document.querySelector('.onb'))
    & Node.DOCUMENT_POSITION_FOLLOWING),
  ssids: [...document.querySelectorAll('.wifi-net')].map((e) => e.dataset.ssid),
  nameTitle: document.querySelector('.topbar .name')?.title || '',
  sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`);
await shot('wifi-card-phone.png');

await click('.wifi-net[data-ssid="Home"] .wifi-net-head');
await waitFor(`!!document.querySelector('.wifi-psk')`, 'campo de senha expandido para Home');
await click('.wifi-net[data-ssid="Home-5G"] .wifi-net-head');
await waitFor(`!!document.querySelector('.wifi-net[data-ssid="Home-5G"] .wifi-psk')`, 'campo de senha expandido para rede criptografada salva');
out.expanded = await js(`({ pskType: document.querySelector('.wifi-psk')?.type,
  saved: document.querySelector('.wifi-net[data-ssid="Home-5G"] .wifi-badge')?.textContent,
  savedNote: document.querySelector('.wifi-net[data-ssid="Home-5G"] .wifi-note')?.textContent })`);
await click('.wifi-net[data-ssid="Home-5G"] .wifi-net-head');
await click('.wifi-net[data-ssid="Home"] .wifi-net-head');
await waitFor(`!!document.querySelector('.wifi-net[data-ssid="Home"] .wifi-psk')`, 'campo de senha expandido novamente para Home');
await setVal('.wifi-psk', 'wrongpass');
await click('.wifi-net[data-ssid="Home"] .wifi-connect');
await waitFor(`!!document.querySelector('.wifi-confirm')`, 'confirmação de troca de rede exibida');
out.confirm = await js(`document.querySelector('.wifi-confirm').innerText.replace(/\\s+/g, ' ')`);
await shot('wifi-confirm-phone.png');

await click('.wifi-confirm .btn-danger');
await waitFor(`/Trocando de rede/.test(document.querySelector('.wifi-switching')?.innerText || '')`, 'aviso de troca de rede exibido', 5000);
out.switching = await js(`document.querySelector('.wifi-switching').innerText.replace(/\\s+/g, ' ')`);
await shot('wifi-switching-phone.png');

await waitFor(`/Falha na última conexão com “Home”: Senha incorreta/.test(document.querySelector('.wifi-last-try')?.innerText || '')`, 'aviso de falha de conexão exibido', 15000);
out.lastTry = await js(`({ text: document.querySelector('.wifi-last-try').innerText.replace(/\\s+/g, ' '),
  color: getComputedStyle(document.querySelector('.wifi-last-try')).color,
  sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`);
await shot('wifi-last-try-phone.png');

// Na barra inferior do celular, Mais é o único acesso às configurações; dali, abra os logs e exporte o pacote de diagnóstico.
out.hotspotPasswordHint = await js(`document.querySelector('.wifi-card')?.innerText.includes('A senha do ponto de acesso é compartilhada')`);
await js(`[...document.querySelectorAll('.tabbar a')].find((a) => a.textContent.trim() === 'Mais').click()`);
await waitFor(`location.hash === '#/settings' && !!document.querySelector('.password-settings')`, 'abrir configurações pela barra inferior do celular');
out.mobile = await js(`({ navHidden: getComputedStyle(document.querySelector('.nav')).display === 'none',
  hasLogs: !!document.querySelector('.settings-logs'), hasDiag: !!document.querySelector('.settings-diag') })`);
await shot('settings-mobile-links.png');
// A seção “Endereços deste robô” da página Mais: no modo hotspot, o IP é 10.42.0.1; duck-xxxx e duck-xxxx.local também podem ser copiados.
await waitFor(`document.querySelectorAll('.duck-addr .duck-addr-row').length >= 3`, 'endereços do Microduck');
out.addr = await js(`({ rows: [...document.querySelectorAll('.duck-addr .duck-addr-row')].map((r) => ({ kind: r.dataset.kind,
    url: r.querySelector('a')?.textContent, copy: r.querySelector('.duck-addr-copy')?.textContent.trim() })),
  text: document.querySelector('.duck-addr').innerText.replace(/\\s+/g, ' '),
  sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`);
await click('.duck-addr .duck-addr-row .duck-addr-copy');
await sleep(300);
out.addr.copied = await js(`document.querySelector('.duck-addr .duck-addr-row .duck-addr-copy').textContent.trim()`);
await shot('settings-duck-addr-phone.png');
await click('.settings-logs');
await waitFor(`location.hash === '#/logs' && !!document.querySelector('.logs-export')`, 'abrir página de registros pelas configurações');
out.mobile.logs = await js(`document.querySelector('.logs-export')?.textContent`);
await js(`window.__diagHref = ''; document.addEventListener('click', (e) => {
  const a = e.target.closest && e.target.closest('a.logs-export');
  if (a) { e.preventDefault(); window.__diagHref = a.getAttribute('href'); }
}, { capture: true, once: true })`);
await click('.logs-export');
out.mobile.diagClicked = await js('window.__diagHref');

// Depois de definir a senha de login, a dica do cartão hotspot desaparece e a sessão deste navegador continua ativa.
// Envie as duas requisições pela página (mesma origem e sessão do navegador), não pelo Node.
out.passwordSet = await js(`(async () => {
  const sess = await (await fetch('/api/session')).json();
  const r = await fetch('/api/password', { method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF': sess.csrf },
    body: JSON.stringify({ action: 'set', password: 'phone-secret', confirm: 'phone-secret' }) });
  return r.status;
})()`);
await js(`location.hash = '#/'`);
await waitFor(`!!document.querySelector('.wifi-card') && !document.querySelector('.wifi-card').innerText.includes('A senha do ponto de acesso é compartilhada')`,
  'aviso do hotspot some após definir uma senha', 10000);
out.hotspotPasswordHintAfterSet = await js(`document.querySelector('.wifi-card').innerText.includes('A senha do ponto de acesso é compartilhada')`);

// ---- Tarefa 17: localizar o novo endereço do robô após enviar a conexão e perder o acesso à página. ----
const cut = () => js(`(() => { window.__cut = true; for (const w of window.__ws) { try { w.close(); } catch (e) { /* conexão já fechada */ } } return true; })()`);
const uncut = () => js(`(() => { window.__cut = false; return true; })()`);
const connectTo = async (ssid, psk) => {
  await click(`.wifi-net[data-ssid="${ssid}"] .wifi-net-head`);
  await waitFor(`!!document.querySelector('.wifi-net[data-ssid="${ssid}"] .wifi-connect')`, `${ssid} expandida`);
  if (psk) await setVal(`.wifi-net[data-ssid="${ssid}"] .wifi-psk`, psk);
  await waitFor(`!document.querySelector('.wifi-net[data-ssid="${ssid}"] .wifi-connect').disabled`, `botão Conectar de ${ssid} habilitado`);
  await click(`.wifi-net[data-ssid="${ssid}"] .wifi-connect`);
  await waitFor(`!!document.querySelector('.wifi-confirm')`, `confirmação de troca de ${ssid} exibida`);
  await click('.wifi-confirm .btn-danger');
  await waitFor(`!!document.querySelector('.wifi-switching')`, `aviso de troca de ${ssid} exibido`, 5000);
};
// A. Hotspot voltou: após desconectar, mostre o cartão de busca e consulte os dois endereços a cada 2 s; ao reconectar ao endereço original, recolha o cartão e mantenha o motivo da falha.
probeMode = 'fail';
await connectTo('Ghost', 'whatever1');
await cut();
const mark = probes.length;
await waitFor(`document.querySelector('.wifi-finding')?.dataset.phase === 'finding'`, 'cartão de localização exibido após desconexão', 8000);
await sleep(4500);
out.findA = await js(`(() => { const c = document.querySelector('.wifi-finding'); return {
  phase: c.dataset.phase, text: c.innerText.replace(/\\s+/g, ' '),
  links: [...c.querySelectorAll('a')].map((a) => a.getAttribute('href')),
  sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }; })()`);
out.findA.probes = probes.slice(mark);
await shot('wifi-finding-phone.png');
await uncut();
await waitFor(`!document.querySelector('.wifi-finding') && /Falha na última conexão com “Ghost”/.test(document.querySelector('.wifi-last-try')?.innerText || '')`,
  'página reconectada: cartão de localização oculto e motivo da falha exibido', 20000);
const atBack = probes.length;
await sleep(4500);
out.findBack = { finding: !!(await js(`!!document.querySelector('.wifi-finding')`)),
  lastTry: await js(`document.querySelector('.wifi-last-try')?.innerText.replace(/\\s+/g, ' ')`),
  probesAtBack: atBack, probesLater: probes.length };
// B. Encontrado: duck-fake.local responde e a página navega para ele.
probeMode = 'found';
await connectTo('Coffee', '');
await cut();
const end = Date.now() + 15000;
out.found = null;
while (Date.now() < end) {
  let href = null;
  try { href = await js('location.href'); } catch { /* redirecionamento em andamento */ }
  if (href && href.startsWith('http://duck-fake.local')) { out.found = { href, title: await js('document.title') }; break; }
  await sleep(200);
}
if (!out.found) throw new Error(`Não redirecionou para duck-fake.local em 15 s; requisições interceptadas: ${JSON.stringify(probes.slice(-6))}`);

process.stdout.write(JSON.stringify(out));
ws.close();
await fetch(`http://127.0.0.1:${CDP}/json/close/${page.id}`);
