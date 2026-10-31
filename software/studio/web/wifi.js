// Cartão Conectar ao Wi-Fi na visão geral e seção Wi-Fi das configurações.
// Quando o ponto de acesso do Microduck está ativo, conecte o celular a ele, abra o Studio, selecione a rede doméstica e informe a senha. O Studio desativa o ponto de acesso antes de pedir a conexão a configd.
// O backend (studio/net.py) controla o ponto de acesso e as operações net.*. Esta interface permite selecionar redes, confirmar a troca e acompanhar a reconexão.
// openLines mostra como acessar o Studio após a troca de rede. DuckAddresses fornece endereços copiáveis na página Mais.
// Após solicitar a conexão, se a página perder contato com o Microduck, procure o novo endereço a cada 2 s por até 3 min carregando probe.svg em duck-xxxx e duck-xxxx.local.
// A lógica findUrls / probeImage / startFind é independente da interface e pode ser exercitada em Node por tests/wifi_find.mjs com um relógio simulado.
import { html, useState, useEffect } from './vendor/preact-htm.module.js';
import { ConfirmBox } from './confirm.js';

const CSS = `
.wifi-card { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.wifi-card h2 { margin: 0; font-size: 17px; font-weight: 600; }
.wifi-settings { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.wifi-settings h2 { margin: 0; font-size: 15px; font-weight: 600; }
.wifi-lead { margin: 0; font-size: 13px; line-height: 1.6; color: var(--text-2); }
.wifi-last-try { padding: 9px 12px; border-radius: 10px; background: #FFF1F1; box-shadow: inset 0 0 0 1px rgba(215, 0, 21, .18);
  color: var(--danger); font-size: 14px; line-height: 1.55; }
.wifi-list { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.wifi-net, .wifi-manual { border-radius: 12px; background: #F7F7FA; min-width: 0; overflow: hidden; }
.wifi-net.on { background: #EEF5FF; box-shadow: inset 0 0 0 1px rgba(0, 113, 227, .22); }
.wifi-net-head, .wifi-manual-head { width: 100%; min-height: 48px; padding: 8px 12px; border: 0; background: transparent;
  display: flex; align-items: center; gap: 10px; text-align: left; font-size: 16px; color: var(--text); }
.wifi-manual-head { color: var(--text-2); font-size: 14px; }
.wifi-name { flex: 1; min-width: 0; overflow-wrap: anywhere; line-height: 1.3; }
.wifi-name b { font-weight: 600; }
.wifi-sub { display: block; margin-top: 2px; font-size: 12px; color: var(--text-2); font-weight: 400; }
.wifi-badge { flex: none; font-size: 11px; padding: 1px 7px; border-radius: 999px; background: #E3F6EA; color: #1E7B3A; }
.wifi-lock { flex: none; font-size: 13px; opacity: .75; }
.wifi-bars { flex: none; width: 22px; height: 16px; display: inline-flex; align-items: flex-end; gap: 2px; }
.wifi-bars i { flex: 1; border-radius: 1px; background: #D5D5DB; height: 4px; }
.wifi-bars i:nth-child(2) { height: 7px; }
.wifi-bars i:nth-child(3) { height: 11px; }
.wifi-bars i:nth-child(4) { height: 15px; }
.wifi-bars i.on { background: var(--blue); }
.wifi-row-body { padding: 0 12px 12px; display: flex; flex-direction: column; gap: 8px; }
.wifi-psk-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.wifi-psk, .wifi-manual-name, .wifi-manual-psk { width: 100%; min-width: 0; height: 44px; padding: 0 12px;
  border: 1px solid #D2D2D7; border-radius: 10px; background: #FFF; color: var(--text); font: inherit; font-size: 16px; }
.wifi-show { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; color: var(--text-2); }
.wifi-btn { min-height: 40px; padding: 0 16px; border: 0; border-radius: 999px; background: #E5E5EA;
  color: var(--text); font: inherit; font-size: 14px; }
.wifi-btn.primary { background: var(--blue); color: #FFF; font-weight: 600; }
.wifi-btn:disabled { opacity: .45; }
.wifi-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.wifi-note { font-size: 13px; color: var(--text-2); line-height: 1.5; }
.wifi-msg { font-size: 13px; line-height: 1.5; color: var(--danger); }
.wifi-switching { padding: 12px 14px; border-radius: 12px; background: #FFF7EC; box-shadow: inset 0 0 0 1px #F5DDBF;
  font-size: 14px; line-height: 1.6; }
.wifi-switching b { display: block; margin-bottom: 4px; font-size: 15px; }
.wifi-switching p { margin: 2px 0 0; }
.wifi-now { display: flex; flex-direction: column; gap: 4px; font-size: 14px; line-height: 1.55; }
.wifi-now .big { font-size: 16px; font-weight: 600; }
.wifi-saved-row { display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 4px 0; border-top: 1px solid var(--line); }
.wifi-saved-row .wifi-name { font-size: 15px; }
.wifi-flow { margin-top: 4px; padding-top: 12px; border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; }
.wifi-open { margin: 4px 0 0; padding-left: 18px; font-size: 13px; line-height: 1.6; color: var(--text-2); }
.wifi-open li { overflow-wrap: anywhere; }
.wifi-finding .wifi-find-urls { font-size: 14px; color: var(--text); }
.wifi-finding .wifi-find-urls a { font-weight: 600; }
.duck-addr-row { display: flex; align-items: center; gap: 10px; min-height: 44px; padding: 4px 0; border-top: 1px solid var(--line); }
.duck-addr-row .wifi-name { font-size: 15px; }
.duck-addr-row .wifi-name a { overflow-wrap: anywhere; }
@media (max-width: 700px) {
  .wifi-card, .wifi-settings { padding: 14px 14px; }
  .wifi-net-head { min-height: 52px; padding: 10px 12px; }
  .wifi-btn { min-height: 44px; }
  .wifi-psk, .wifi-manual-name, .wifi-manual-psk { height: 46px; }
}
`;
if (typeof document !== 'undefined' && !document.getElementById('wifi-css')) {   // Os testes de localização executados no Node não têm document.
  const s = document.createElement('style');
  s.id = 'wifi-css';
  s.textContent = CSS;
  document.head.appendChild(s);
}

const SEC = { open: 'Aberta', wep: 'WEP', wpa_psk: 'WPA2', wpa3_sae: 'WPA3', enterprise: 'Autenticação empresarial' };
const secLabel = (sec) => SEC[sec] || (sec ? 'Criptografada' : '');
const pskFormatOk = (v) => v === '' || (v.length >= 8 && v.length <= 63) || /^[0-9a-fA-F]{64}$/.test(v);
const pskOk = (v) => v !== '' && pskFormatOk(v);

function Bars({ signal }) {
  const n = typeof signal === 'number' ? (signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1) : 0;
  return html`<span class="wifi-bars" title=${typeof signal === 'number' ? 'Sinal ' + signal : 'Sinal desconhecido'}
    aria-label=${typeof signal === 'number' ? 'Sinal ' + signal : 'Sinal desconhecido'}>
    ${[1, 2, 3, 4].map((i) => html`<i class=${i <= n ? 'on' : ''}></i>`)}</span>`;
}

function minutesSince(at) {
  if (typeof at !== 'number') return null;
  return Math.max(1, Math.round((Date.now() / 1000 - at) / 60));
}

// Instruções para abrir o Studio após trocar de rede, organizadas por dispositivo. Em alguns computadores Windows com o proxy Clash, duck-xxxx.local passa pelo proxy e retorna 502.
// O nome duck-xxxx pode ser resolvido via LLMNR e ignorado pelo proxy; o endereço IP funciona em qualquer dispositivo.
export function openLines(net) {
  const host = net.hostname || 'duck-xxxx';
  return [
    `Computador Windows: ${net.url_host || `http://${host}:8000/`} (funciona mesmo com o proxy ativado)`,
    `iPhone ou Mac: ${net.url_local || `http://${host}.local:8000/`}`,
    `Android ou se os endereços acima não funcionarem: localize ${host} na lista de dispositivos do roteador e abra o endereço IP`,
    'Se o computador estiver usando o modo TUN do Clash: configure a rede local (192.168.0.0/16) como conexão direta no Clash',
  ];
}

// ---------------- Localização do novo endereço após conectar ao Wi-Fi ----------------
export const FIND_EVERY_MS = 2000;           // Tenta novamente a cada 2 s.
export const FIND_GIVEUP_MS = 3 * 60 * 1000; // Desiste após 3 min.
export const FIND_PROBE_MS = 6000;           // Tempo máximo por tentativa; um endereço inacessível pode demorar a responder.
export const FIND_SILENT_MS = 5000;          // Considera a conexão interrompida após 5 s sem mensagens do Studio; o WebSocket pode demorar para detectar a falha.

/** Endereços procurados: http://<hostname>:<porta>/ e http://<hostname>.local:<porta>/; hostname vem de net.json e a porta corresponde a --listen. */
export function findUrls(net) {
  const host = (net && net.hostname) || 'duck-xxxx';
  const urls = [(net && net.url_host) || `http://${host}:8000/`, (net && net.url_local) || `http://${host}.local:8000/`];
  return urls.filter((u, i) => urls.indexOf(u) === i);
}

/** Testa um endereço carregando uma imagem pequena: retorna true ao carregar e false em caso de erro ou tempo esgotado. Imagens entre origens não exigem CORS; ?t= evita o cache. */
export function probeImage(url, timeoutMs = FIND_PROBE_MS) {
  return new Promise((resolve) => {
    const img = new Image();
    let done = false;
    const end = (ok) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      img.onload = null; img.onerror = null;
      resolve(ok);
    };
    const timer = setTimeout(() => end(false), timeoutMs);
    img.onload = () => end(true);
    img.onerror = () => end(false);
    img.src = `${url}probe.svg?t=${Date.now()}`;
  });
}

/** A cada every milissegundos, testa cada URL sem repetir uma tentativa em andamento. Ao encontrar um endereço, chama onFound e para.
 * Se não encontrar após giveUp milissegundos, chama onGiveUp e para. Retorna {stop}, usado quando a página reconecta ao endereço original. */
export function startFind({ urls, onFound, onGiveUp, probe = probeImage, every = FIND_EVERY_MS, giveUp = FIND_GIVEUP_MS,
  now = () => Date.now(), timers = { setTimeout: (f, ms) => setTimeout(f, ms), clearTimeout: (t) => clearTimeout(t) } }) {
  const t0 = now();
  const inFlight = new Set();
  let stopped = false;
  let timer = null;
  const stop = () => {
    stopped = true;
    if (timer != null) timers.clearTimeout(timer);
    timer = null;
  };
  const tick = () => {
    timer = null;
    if (stopped) return;
    if (now() - t0 >= giveUp) { stop(); if (onGiveUp) onGiveUp(); return; }
    for (const url of urls) {
      if (inFlight.has(url)) continue;
      inFlight.add(url);
      Promise.resolve().then(() => probe(url)).then((ok) => {
        inFlight.delete(url);
        if (ok === true && !stopped) { stop(); if (onFound) onFound(url); }
      }, () => { inFlight.delete(url); });
    }
    timer = timers.setTimeout(tick, every);
  };
  tick();
  return { stop, get stopped() { return stopped; } };
}

// Texto de confirmação; a primeira frase muda entre o cartão do ponto de acesso e a opção para trocar de rede nas configurações.
function confirmLines(net, ssid, variant) {
  const back = variant === 'switch'
    ? 'Se a conexão falhar, esta página será desconectada. O ponto de acesso voltará em seguida; reconecte o celular ao Microduck para ver o motivo.'
    : `Se a conexão falhar, o ponto de acesso voltará em seguida. Reconecte o celular a ${net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : 'este ponto de acesso do Microduck'} para ver o motivo.`;
  const first = variant === 'switch'
    ? `O Microduck será desconectado do Wi-Fi atual para conectar a “${ssid}”; esta página perderá a conexão.`
    : `O Microduck desativará o ponto de acesso e conectará a “${ssid}”. O celular será desconectado.`;
  return [first, 'Após a conexão, conecte o celular (ou computador) novamente ao Wi-Fi doméstico e abra o endereço adequado ao dispositivo:', ...openLines(net).map((l) => `· ${l}`), back];
}

// Copia um endereço. Como o endereço local do Microduck usa HTTP, navigator.clipboard pode não estar disponível; nesse caso, seleciona um campo invisível e usa copy.
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* Tenta o método alternativo abaixo. */ }
  try {
    const t = document.createElement('textarea');
    t.value = text;
    t.setAttribute('readonly', '');
    t.style.position = 'fixed';
    t.style.opacity = '0';
    document.body.appendChild(t);
    t.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(t);
    return ok;
  } catch { return false; }
}

function LastTry({ net }) {
  const lt = net.last_try;
  if (!lt || lt.ok !== false) return null;
  const why = lt.reason_text || 'Não foi possível conectar';
  const ssid = net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : 'ponto de acesso do Microduck';
  return html`<div class="wifi-last-try" role="alert">Falha na última conexão com “${lt.ssid || 'esta rede Wi-Fi'}”: ${why}
    ${net.mode === 'hotspot' ? html`<div>O ponto de acesso voltará em seguida. Reconecte o celular a ${ssid} para ver o motivo.</div>` : null}</div>`;
}

function Switching({ net, ssid, variant }) {
  return html`<div class="wifi-switching" role="status">
    <b>Trocando de rede… o celular será desconectado em instantes.</b>
    ${confirmLines(net, ssid || 'esta rede Wi-Fi', variant).map((line) => html`<p>${line}</p>`)}
  </div>`;
}

// Considera desconectado quando a conexão com o Studio cai ou quando não há mensagens por 5 s.
const linkGone = (link) => link.status !== 'open' || (link.lastAt > 0 && performance.now() - link.lastAt > FIND_SILENT_MS);

// Depois que a página perde contato com o Microduck, procura o novo endereço a cada 2 s e navega até ele quando o encontra; após 3 min, mostra as instruções manuais.
function Finding({ net, find, variant }) {
  const ssid = find.ssid || 'esta rede Wi-Fi';
  if (find.phase === 'timeout') {
    return html`<div class="wifi-switching wifi-finding" role="status" data-phase="timeout">
      <b>Não foi possível encontrar o Microduck após 3 min. Abra o endereço manualmente.</b>
      ${confirmLines(net, ssid, variant).slice(1).map((line) => html`<p>${line}</p>`)}
    </div>`;
  }
  return html`<div class="wifi-switching wifi-finding" role="status" data-phase="finding">
    <b>O Microduck está se conectando a “${ssid}”…</b>
    <p>Conecte este dispositivo novamente a “${ssid}” (computadores conectados por cabo podem permanecer como estão). A página abrirá automaticamente quando encontrar o Microduck.</p>
    <ul class="wifi-open wifi-find-urls">${find.urls.map((u) => html`<li><a href=${u}>${u}</a>${/\.local[:/]/.test(u) ? ' (iPhone ou Mac)' : ' (computador Windows)'}</li>`)}</ul>
    <p>Se não encontrar, localize o IP de ${net.hostname || 'duck-xxxx'} na lista de dispositivos do roteador.</p>
  </div>`;
}

export function WifiFlow({ net, link, variant = 'card' }) {
  const [scan, setScan] = useState({ networks: [], loading: true, error: null, cached: false, scan_at: null });
  const [sel, setSel] = useState(null);
  const [psk, setPsk] = useState('');
  const [show, setShow] = useState(false);
  const [manual, setManual] = useState(false);
  const [manualName, setManualName] = useState('');
  const [manualPsk, setManualPsk] = useState('');
  const [manualShow, setManualShow] = useState(false);
  const [confirm, setConfirm] = useState(null);        // {ssid, psk}
  const [trying, setTrying] = useState(null);
  const [switching, setSwitching] = useState(false);
  const [startedAt, setStartedAt] = useState(0);
  const [msg, setMsg] = useState(null);
  // Após solicitar a conexão, procura o novo endereço: {ssid, urls, phase}. Fases: wait (ainda conectado), finding (desconectado e procurando), timeout (não encontrado após 3 min).
  const [find, setFind] = useState(null);
  const [linkUp, setLinkUp] = useState(link.status === 'open');
  useEffect(() => link.on((m) => { if (m.t === '_status') setLinkUp(m.status === 'open'); }), []);
  const gone = !linkUp || linkGone(link);

  const rescan = async () => {
    setScan((s) => ({ ...s, loading: true, error: null }));
    const r = await link.cmd('net.op', { op: 'scan' }, 25000);
    if (!r.ok) {
      setScan({ networks: [], loading: false, error: r.reason || r.error || 'Não foi possível ler a lista de redes Wi-Fi.', cached: false, scan_at: null });
      return;
    }
    const d = r.data || {};
    setScan({ networks: Array.isArray(d.networks) ? d.networks : [], loading: false, error: null,
      cached: !!d.cached, scan_at: d.scan_at || null });
  };
  useEffect(() => {
    let alive = true;
    (async () => {
      await link.whenOpen();
      if (alive) await rescan();
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!switching && !find) return;
    const lt = net.last_try;
    // A solicitação terminou enquanto a conexão estava ativa, ou o processo já não está ocupado; não é necessário procurar o novo endereço.
    if ((lt && typeof lt.at === 'number' && startedAt && lt.at * 1000 >= startedAt - 2000)
      || (!net.busy && startedAt && Date.now() - startedAt > 12000)) { setSwitching(false); setFind(null); }
  }, [net.busy, net.last_try ? net.last_try.at : null]);

  // Se a conexão cair, procura o Microduck. Se voltar ao endereço original, o ponto de acesso provavelmente foi restaurado; pare a busca e aguarde o resultado.
  // Quando chegar last_try, o efeito acima recolhe o aviso, e LastTry mostra o motivo da falha. Uma suspensão temporária do celular não perde a busca.
  useEffect(() => {
    if (!find) return;
    if (gone && find.phase === 'wait') setFind({ ...find, phase: 'finding' });
    else if (!gone && find.phase !== 'wait') setFind({ ...find, phase: 'wait' });
  }, [gone, find]);
  useEffect(() => {
    if (!find || find.phase !== 'finding') return undefined;
    const f = startFind({
      urls: find.urls,
      onFound: (url) => { if (linkGone(link)) location.href = url; },     // Se o endereço original voltou, não navegue; deixe o efeito acima encerrar a busca.
      onGiveUp: () => setFind((x) => (x ? { ...x, phase: 'timeout' } : x)),
    });
    return () => f.stop();
  }, [find ? find.phase : null]);

  // A confirmação fica no fim do cartão; role até ela quando for exibida no celular.
  useEffect(() => {
    if (!confirm) return;
    const e = document.querySelector('.wifi-confirm-wrap');
    if (e && e.scrollIntoView) e.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [confirm]);

  const pick = (n) => {
    if (sel === n.ssid) { setSel(null); setPsk(''); return; }
    setSel(n.ssid); setPsk(''); setShow(false); setMsg(null);
  };
  const ask = (ssid, pass, locked = false) => {
    if (!ssid) { setMsg('Informe o nome da rede Wi-Fi.'); return; }
    if (locked && !pass) { setMsg('Esta rede Wi-Fi é protegida por senha. Informe a senha.'); return; }
    if (!pskFormatOk(pass)) { setMsg('A senha do Wi-Fi deve ter de 8 a 63 caracteres ou 64 dígitos hexadecimais.'); return; }
    setMsg(null);
    setConfirm({ ssid, psk: pass });
  };
  const start = async () => {
    if (!confirm) return;
    const { ssid, psk: pass } = confirm;
    setConfirm(null); setTrying(ssid); setStartedAt(Date.now()); setSwitching(true); setMsg(null);
    const wasOpen = link.status === 'open';
    setFind({ ssid, urls: findUrls(net), phase: 'wait' });
    const r = await link.cmd('net.op', { op: 'connect', ssid, psk: pass }, 20000);
    // Se o Studio recusar, já estiver desconectado ou continuar conectado sem responder, a solicitação não foi enviada. Se a conexão cair enquanto a resposta chega, a troca provavelmente começou; continue procurando o Microduck.
    if (!r.ok && (r.reason || !wasOpen || link.status === 'open')) {
      setSwitching(false); setFind(null); setMsg(r.reason || r.error || 'Não foi possível enviar a solicitação.');
    }
  };

  const nets = scan.networks || [];
  const ago = scan.cached ? minutesSince(scan.scan_at) : null;
  const busy = switching || net.busy === 'connecting' || (!!find && find.phase !== 'wait');
  return html`<div class="wifi-flow">
    ${find && find.phase !== 'wait' ? html`<${Finding} net=${net} find=${find} variant=${variant} />`
      : busy ? html`<${Switching} net=${net} ssid=${trying || (net.last_try && net.last_try.ssid)} variant=${variant} />` : null}
    ${scan.error ? html`<div class="wifi-msg">${scan.error}</div>` : null}
    <div class="wifi-list">
      ${nets.map((n) => {
        const on = sel === n.ssid;
        const open = n.security === 'open';
        const needs = !open;
        const can = open || pskOk(psk);
        return html`<div class=${'wifi-net' + (on ? ' on' : '')} data-ssid=${n.ssid}>
          <button class="wifi-net-head" type="button" aria-expanded=${on ? 'true' : 'false'} onClick=${() => pick(n)}>
            <${Bars} signal=${n.signal} />
            <span class="wifi-name"><b>${n.ssid}</b><span class="wifi-sub">${secLabel(n.security)}${n.saved ? ' · salva' : ''}</span></span>
            ${n.saved ? html`<span class="wifi-badge">Salva</span>` : null}
            ${open ? null : html`<span class="wifi-lock" title="${secLabel(n.security)}">🔒</span>`}
          </button>
          ${on ? html`<div class="wifi-row-body">
            ${needs ? html`<div class="wifi-psk-row">
              <input class="wifi-psk" type=${show ? 'text' : 'password'} value=${psk} autocomplete="new-password"
                placeholder="Senha do Wi-Fi doméstico" onInput=${(e) => setPsk(e.target.value)} />
              <label class="wifi-show"><input type="checkbox" checked=${show} onChange=${(e) => setShow(e.target.checked)} /> Mostrar senha</label>
            </div>${n.saved ? html`<div class="wifi-note">Rede salva; o Microduck solicita a senha a cada conexão, conforme o comportamento do assistente oficial de configuração.</div>` : null}`
              : html`<div class="wifi-note">Esta rede é aberta e não exige senha.</div>`}
            <div class="wifi-actions"><button class="wifi-btn primary wifi-connect" type="button" disabled=${!can || busy}
              onClick=${() => ask(n.ssid, needs ? psk : '', needs)}>Conectar</button></div>
          </div>` : null}
        </div>`;
      })}
    </div>
    <div class="wifi-manual">
      <button class="wifi-manual-head" type="button" aria-expanded=${manual ? 'true' : 'false'} onClick=${() => setManual(!manual)}>
        ${manual ? 'Recolher' : 'Outra rede (informar o nome manualmente)'}
      </button>
      ${manual ? html`<div class="wifi-row-body">
        <input class="wifi-manual-name" value=${manualName} placeholder="Nome da rede Wi-Fi" onInput=${(e) => setManualName(e.target.value)} />
        <input class="wifi-manual-psk" type=${manualShow ? 'text' : 'password'} value=${manualPsk}
          placeholder="Senha (deixe em branco para rede aberta)" autocomplete="new-password" onInput=${(e) => setManualPsk(e.target.value)} />
        <label class="wifi-show"><input type="checkbox" checked=${manualShow} onChange=${(e) => setManualShow(e.target.checked)} /> Mostrar senha</label>
        <div class="wifi-actions"><button class="wifi-btn primary wifi-manual-connect" type="button" disabled=${busy || !manualName}
          onClick=${() => ask(manualName, manualPsk)}>Conectar</button></div>
      </div>` : null}
    </div>
    <div class="wifi-actions">
      <button class="wifi-btn wifi-rescan" type="button" disabled=${scan.loading || busy} onClick=${rescan}>
        ${scan.loading ? 'Procurando redes…' : 'Procurar novamente'}</button>
      ${ago ? html`<span class="wifi-note">Última busca há ${ago} min</span>` : null}
    </div>
    ${msg ? html`<div class="wifi-msg">${msg}</div>` : null}
    ${confirm ? html`<div class="wifi-confirm-wrap"><${ConfirmBox} cls="wifi-confirm" lines=${confirmLines(net, confirm.ssid, variant)}
      confirmLabel=${'Desconectar e conectar a “' + confirm.ssid + '”'} onCancel=${() => setConfirm(null)} onConfirm=${start} /></div>` : null}
  </div>`;
}

export function WifiCard({ net, link, secure }) {
  if (!net || !net.known || net.mode !== 'hotspot') return null;
  return html`<section class="board wifi-card" aria-label="Conectar ao Wi-Fi">
    <h2>Conectar ao Wi-Fi</h2>
    <p class="wifi-lead">O ponto de acesso do Microduck está ativo (${net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : 'Microduck'}).
      Selecione o Wi-Fi doméstico e informe a senha. Depois que o Microduck se conectar, conecte o celular (ou computador) novamente à rede doméstica e abra:</p>
    <ul class="wifi-open">${openLines(net).map((l) => html`<li>${l}</li>`)}</ul>
    <${LastTry} net=${net} />
    <${WifiFlow} net=${net} link=${link} />
    ${secure === false ? html`<div class="wifi-note" role="note">A senha do ponto de acesso é compartilhada. Qualquer pessoa por perto pode se conectar e controlar o Microduck; antes de demonstrá-lo fora de casa, defina uma senha de acesso em “Mais”.</div>` : null}
  </section>`;
}

export function WifiSettings({ net, link }) {
  const [flow, setFlow] = useState(false);
  const [scan, setScan] = useState(null);
  const [forget, setForget] = useState(null);
  const [msg, setMsg] = useState(null);
  const load = async () => {
    const r = await link.cmd('net.op', { op: 'scan' }, 25000);
    setScan(r.ok ? (r.data || { networks: [] }) : { networks: [], error: r.reason || r.error });
  };
  useEffect(() => {
    if (!net || !net.known) return undefined;
    let alive = true;
    (async () => { await link.whenOpen(); if (alive) await load(); })();
    return () => { alive = false; };
  }, [net && net.known]);
  if (!net || !net.known) return null;
  const saved = (scan && scan.networks ? scan.networks : []).filter((n) => n.saved);
  const doForget = async (ssid) => {
    setForget(null); setMsg(null);
    const r = await link.cmd('net.op', { op: 'forget', ssid }, 15000);
    if (!r.ok) { setMsg(r.reason || r.error || 'Não foi possível remover a rede salva.'); return; }
    setMsg(r.data && r.data.removed === false ? `“${ssid}” já não estava salva no Microduck.` : `Rede “${ssid}” removida.`);
    load();
  };
  const current = net.mode === 'hotspot' ? 'Ponto de acesso do Microduck' : (net.ssid || 'Desconectado do Wi-Fi');
  return html`<div class="board wifi-settings" aria-label="Configurações de Wi-Fi">
    <h2>WiFi</h2>
    <${LastTry} net=${net} />
    <div class="wifi-now">
      <div class="big">Conectado a: ${current}</div>
      ${net.mode === 'hotspot' ? html`<div>Ponto de acesso: ${net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : '—'} · Senha: ${net.hotspot && net.hotspot.psk ? net.hotspot.psk : '—'}</div>`
        : net.mode === 'wifi' ? html`<div class="wifi-actions"><${Bars} signal=${net.signal} /><span>Sinal ${net.signal ?? '—'}</span><span>IP ${net.ip4 || '—'}</span></div>`
          : html`<div>O Wi-Fi está desconectado.</div>`}
      <div class="wifi-note">Os endereços para abrir o Studio estão em “Endereços do Microduck” acima; escolha o adequado ao dispositivo e copie.</div>
    </div>
    <div class="wifi-actions"><button class="wifi-btn primary" type="button" onClick=${() => setFlow(!flow)}>
      ${flow ? 'Recolher' : 'Trocar de rede Wi-Fi'}</button></div>
    ${flow ? html`<div class="wifi-flow"><${WifiFlow} net=${net} link=${link} variant="switch" /></div>` : null}
    <div>
      <div class="wifi-note">Redes salvas</div>
      ${scan && scan.error ? html`<div class="wifi-msg">${scan.error}</div>` : null}
      ${saved.length ? saved.map((n) => html`<div class="wifi-saved-row">
        <span class="wifi-name">${n.ssid}</span>
        ${n.ssid === net.ssid ? html`<span class="wifi-badge">Em uso</span>` : null}
        <button class="wifi-btn wifi-forget" type="button" data-ssid=${n.ssid}
          onClick=${() => n.ssid === net.ssid ? setForget(n.ssid) : doForget(n.ssid)}>Remover</button>
      </div>`) : html`<div class="wifi-note">${scan ? 'Ainda não há redes Wi-Fi salvas.' : 'Carregando…'}</div>`}
    </div>
    ${msg ? html`<div class="wifi-note">${msg}</div>` : null}
    ${forget ? html`<div class="wifi-confirm-wrap"><${ConfirmBox} cls="wifi-confirm"
      lines=${[`Ao remover “${forget}”, o Microduck será desconectado. Se não houver outra rede disponível, o ponto de acesso será ativado após 1 min.`]}
      confirmLabel="Remover" onCancel=${() => setForget(null)} onConfirm=${() => doForget(forget)} /></div>` : null}
  </div>`;
}

// Endereços do Microduck na página Mais. net.urls lista os endereços disponíveis: IP (ip4 de configd net.status; 10.42.0.1 no modo ponto de acesso), duck-xxxx e duck-xxxx.local.
export function DuckAddresses({ net }) {
  const [copied, setCopied] = useState(null);       // {url, ok}
  useEffect(() => {
    if (!copied) return undefined;
    const t = setTimeout(() => setCopied(null), 1500);
    return () => clearTimeout(t);
  }, [copied]);
  if (!net || !net.known) return null;
  const urls = net.urls || [];
  const copy = async (url) => setCopied({ url, ok: await copyText(url) });
  return html`<div class="board wifi-settings duck-addr" aria-label="Endereços do Microduck">
    <h2>Endereços do Microduck</h2>
    <p class="wifi-lead">${net.mode === 'hotspot' ? 'O ponto de acesso do Microduck está ativo; no celular conectado a ele, use o endereço IP.'
      : 'Conecte-se à mesma rede Wi-Fi do Microduck e escolha o endereço adequado ao dispositivo.'}</p>
    ${urls.map((u) => html`<div class="duck-addr-row" data-kind=${u.kind}>
      <span class="wifi-name"><a href=${u.url}>${u.url}</a><span class="wifi-sub">${u.note}</span></span>
      <button class="wifi-btn duck-addr-copy" type="button" onClick=${() => copy(u.url)}>
        ${copied && copied.url === u.url ? (copied.ok ? 'Copiado' : 'Não foi possível copiar; mantenha o endereço pressionado para copiá-lo') : 'Copiar'}</button>
    </div>`)}
    ${urls.some((u) => u.kind === 'ip') ? null
      : html`<div class="wifi-note">IP indisponível (Wi-Fi desconectado ou serviço de configuração sem resposta). Localize ${net.hostname || 'duck-xxxx'} na lista de dispositivos do roteador.</div>`}
    <div class="wifi-note">Se o endereço com nome não funcionar no Android, use o IP. Se o computador estiver no modo TUN do Clash, configure a rede local (192.168.0.0/16) como conexão direta no Clash.</div>
  </div>`;
}
