// Interface do Microduck Studio. Não há etapa de compilação: Preact + htm (vendor/preact-htm.module.js) executam diretamente no navegador.
//
// A comunicação com o backend do Studio usa dois canais:
// - HTTP: /api/session, /api/login, /api/logout, /api/password, /api/logs e /api/diag;
// - WebSocket /ws: o backend envia hello / state / log / result, e a interface envia hb (sinal de vida, com visibilidade da página) e cmd (comando).
// O formato das mensagens está em software/studio/README.md, na seção de protocolo entre interface e backend.
import { html, render, Component, useState, useEffect, useRef, useCallback } from './vendor/preact-htm.module.js';
import { Duck3D } from './duck3d.js';
import { ServoPage, HandBackButton } from './servo.js';
import { ImuPage } from './imu.js';
import { PadPage, padActivity, padGo } from './pad.js';
import { BatteryCell } from './battery.js';
import { BatterySettings } from './settings-battery.js';
import { AiSettings } from './settings-ai.js';
import { UpdateSettings } from './settings-updates.js';
import { TuneSection, ModelSettings } from './tune.js';
import { WifiCard, WifiSettings, DuckAddresses } from './wifi.js';
import { TwoStep } from './confirm.js';
import { ModelsPage } from './models.js';
import { CameraPage, TofPage, SensorBandCells } from './sensors.js';

const STALE_GRAY_MS = 1000;   // Sem dados novos por mais de 1 s: valores ficam acinzentados.
const STALE_ALARM_MS = 3000;  // Sem dados novos por mais de 3 s: exibe um aviso; o botão de liberar servos continua disponível enquanto houver conexão com o Studio.

// ---------------- Conexão ----------------

class Link {
  constructor() {
    this.ws = null;
    this.seq = 0;
    this.pending = new Map();
    this.listeners = new Set();
    this.status = 'connecting';
    this.lastAt = 0;
    this.backoff = 1000;
    this._hb = null;
    this.padCapture = false;
    document.addEventListener('visibilitychange', () => this.heartbeat());
  }

  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit(m) { for (const fn of this.listeners) fn(m); }
  setStatus(s) { this.status = s; this.emit({ t: '_status', status: s }); }

  connect() {
    clearTimeout(this._retry);
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    let opened = false;
    this.setStatus('connecting');
    ws.onopen = () => {
      opened = true;
      this.backoff = 1000;
      this.setStatus('open');
      this.heartbeat();
      clearInterval(this._hb);
      this._hb = setInterval(() => this.heartbeat(), 1000);
    };
    ws.onmessage = (ev) => {
      if (this.ws !== ws) return;            // Ignore mensagens recebidas por uma conexão antiga.
      let m;
      try { m = JSON.parse(ev.data); } catch { return; }
      this.lastAt = performance.now();
      // Em uma aba em segundo plano, setInterval pode executar apenas uma vez por minuto. Responda aos sinais do servidor para evitar uma desconexão falsa.
      if (m.t === 'hb') this.heartbeat();
      if (m.t === 'result' && this.pending.has(m.id)) {
        this.pending.get(m.id)(m);
        this.pending.delete(m.id);
      }
      this.emit(m);
    };
    ws.onclose = async (ev) => {
      if (this.ws !== ws) return;            // Não altere os sinais de vida da conexão nova.
      clearInterval(this._hb);
      for (const done of this.pending.values()) done({ ok: false, error: 'A conexão com o Studio foi interrompida' });
      this.pending.clear();
      if (ev.code === 4401) { this.setStatus('auth'); return; }   // Sessão expirada.
      if (!opened) {
        // Se o handshake falhar, a sessão pode ter expirado. Versões antigas do Studio recusam a conexão nesta etapa, e o navegador mostra apenas 1006.
        try { if ((await api('/api/session', undefined, 2000)).status === 401) { this.setStatus('auth'); return; } } catch { /* Studio indisponível. */ }
        if (this.ws !== ws) return;          // O usuário pode ter reconectado durante a espera; deixe a conexão nova assumir.
      }
      this.setStatus('closed');
      this._retry = setTimeout(() => this.connect(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, 8000);
    };
  }

  /** Aguarda a conexão com o Studio, pois a página pode carregar antes dela após uma atualização. */
  whenOpen() {
    if (this.status === 'open') return Promise.resolve();
    return new Promise((resolve) => { const off = this.on((m) => { if (m.t === '_status' && m.status === 'open') { off(); resolve(); } }); });
  }

  reconnect() { this.backoff = 1000; try { this.ws && this.ws.close(); } catch { /* Já está fechado. */ } this.connect(); }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) { this.ws.send(JSON.stringify(obj)); return true; }
    return false;
  }

  // pad_visible indica se a área do controle está na tela. O backend usa essa informação para escolher entre 10 Hz e 1 Hz para as amostras do controle.
  // #/pad é uma âncora da visão geral; o endereço pode continuar nesse fragmento mesmo quando a área não está visível.
  heartbeat() {
    this.send({ t: 'hb', seq: ++this.seq, visible: document.visibilityState === 'visible', route: location.hash.replace(/^#/, '') || '/',
      pad_visible: padActivity.active || this.padCapture });
  }

  // O remapeamento de botões do controle apenas solicita uma amostra; não altera padActivity nem assume o controle remoto da página.
  setPadCapture(active) { this.padCapture = Boolean(active); this.heartbeat(); }

  cmd(name, args = {}, timeoutMs = 15000) {
    const id = `c${++this.seq}`;
    return new Promise((resolve) => {
      if (!this.send({ t: 'cmd', id, name, args })) { resolve({ ok: false, error: 'A conexão com o Studio foi interrompida' }); return; }
      this.pending.set(id, resolve);
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); resolve({ ok: false, error: 'O Microduck não respondeu (tempo esgotado)' }); }
      }, timeoutMs);
    });
  }
}

const link = new Link();
padActivity.bind(link);                  // Envia um sinal de vida assim que a área do controle entra ou sai da tela.

let csrf = '';   // Fornecido por /api/session; requisições POST que alteram dados devem enviá-lo em X-CSRF, junto à validação de Origin do backend.
async function api(path, body, timeoutMs = 10000, signal) {
  const opt = body === undefined ? { credentials: 'same-origin' }
    : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF': csrf }, body: JSON.stringify(body) };
  const ctl = new AbortController();
  const abort = () => ctl.abort();
  if (signal?.aborted) ctl.abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => ctl.abort(), timeoutMs);   // Instabilidades no Wi-Fi do celular podem deixar uma solicitação pendurada por dezenas de segundos.
  let r;
  let data = {};
  try {
    r = await fetch(path, { ...opt, signal: ctl.signal });
    try { data = await r.json(); } catch (error) { if (ctl.signal.aborted) throw error; }
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  return { status: r.status, ...data };
}

// ---------------- Utilitários ----------------

const fmt1 = (v) => (typeof v === 'number' && isFinite(v) ? v.toFixed(1) : '—');

function useNow(ms = 250) {
  const [now, setNow] = useState(performance.now());
  useEffect(() => { const t = setInterval(() => setNow(performance.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}

function Badge({ kind }) {
  return html`<span class=${'badge ' + kind} aria-hidden="true">${kind === 'bad' ? '×' : '!'}</span>`;
}

// ---------------- Barra de segurança superior ----------------

// O estado do botão para liberar os servos vem de st.estop, enviado pelo Studio e calculado a partir da leitura de busStatus; não depende de o botão ter sido pressionado.
// Enquanto houver conexão com o Studio, o botão pode ser usado mesmo com dados antigos ou indisponíveis. Só é desativado quando a conexão cai.
// Intercepta a tecla de espaço ao pressionar e soltar. Interceptar somente o pressionamento permitiria ao navegador clicar no botão em foco ao soltar a tecla.
// A tecla não é interceptada quando o foco está em um campo de texto; nos demais controles, como caixas de seleção e listas, ela libera os servos.
const TEXT_TYPES = ['text', 'password', 'search', 'email', 'number', 'tel', 'url'];
const typing = (el) => !!el && (el.isContentEditable || el.tagName === 'TEXTAREA'
  || (el.tagName === 'INPUT' && TEXT_TYPES.includes((el.type || 'text').toLowerCase())));
// Ctrl, Alt ou Win + Espaço podem ser atalhos do sistema, como a troca do método de entrada; não os trate como comando para liberar os servos.
const plainSpace = (e) => e.code === 'Space' && !e.ctrlKey && !e.altKey && !e.metaKey;

function EStop({ st, live, open }) {
  const [sentAt, setSentAt] = useState(0);
  const [err, setErr] = useState(null);
  const fire = useCallback(async () => {
    if (performance.now() - sentAt < 200) return;           // Limita a repetição da tecla de espaço a 5 comandos por segundo.
    setSentAt(performance.now()); setErr(null);
    const r = await link.cmd('relax', {}, 7000);       // O backend pode levar até 3 + 0,1 + 3 s.
    if (!r.ok) setErr(r.reason || r.error || 'Não foi possível enviar o comando');
  }, [sentAt]);

  useEffect(() => {
    const down = (e) => {
      if (!plainSpace(e) || typing(e.target)) return;
      e.preventDefault(); e.stopPropagation();
      if (!e.repeat) fire();
    };
    const up = (e) => { if (plainSpace(e) && !typing(e.target)) { e.preventDefault(); e.stopPropagation(); } };
    window.addEventListener('keydown', down, true);
    window.addEventListener('keyup', up, true);
    return () => { window.removeEventListener('keydown', down, true); window.removeEventListener('keyup', up, true); };
  }, [fire]);

  const es = st?.estop || {};
  // A confirmação de que os servos foram liberados torna obsoleta a mensagem anterior de falha ou tempo esgotado.
  useEffect(() => { if (es.state === 'confirmed') setErr(null); }, [es.state]);
  const click = (e) => { e.currentTarget.blur(); fire(); };
  const note = (text) => (text ? html`<span class="why" role=${err ? 'alert' : undefined}>${text}</span>` : null);
  const fallback = st?.mode === 'commissioning' ? 'Desligue a alimentação' : 'Use o botão − do controle ou desligue a alimentação';
  if (!open) {
    // Sem conexão com o Studio, o comando não pode ser enviado.
    return html`<span class="estop-wrap">${note(fallback)}
      <button class="estop unavailable" disabled>Liberar servos · indisponível</button></span>`;
  }
  if (st?.servo_orphan) {
    // Se a sessão dos servos continuou aberta após a saída do Studio, robotd e o barramento ainda não estão sob controle; encaminhe para a página Servos.
    // Ao abrir essa página, o Studio assume o barramento. O comando de espaço também é enviado, e o backend orienta o usuário a assumir o controle.
    return html`<span class="estop-wrap">${note(err || 'Ainda pode haver servos mantendo força')}
      <button class="estop unavailable" onClick=${(e) => { e.currentTarget.blur(); location.hash = '#/servos'; }}
        title="A sessão dos servos continuou ativa após a última saída do Studio. Assuma o controle na página Servos para liberá-los.">Liberar servos · assumir na página Servos</button></span>`;
  }
  if (es.state === 'unavailable') {
    return html`<span class="estop-wrap">${note(err || es.why || fallback)}
      <button class="estop unavailable" onClick=${click}>Liberar servos · resultado incerto</button></span>`;
  }
  if (live && es.state === 'confirmed') {
    return html`<span class="estop-wrap">${note(err)}
      <button class="estop done" onClick=${click} title=${es.why}>Servos liberados ✓</button></span>`;
  }
  // Mesmo com dados desatualizados (!live), mantenha o botão vermelho disponível: o canal de liberação dos servos do Studio ainda pode funcionar.
  return html`<span class="estop-wrap">${note(err || (!live ? 'Estado desatualizado; ainda é possível tentar' : ''))}
    <button class="estop" onClick=${click} title="Libera os 15 servos. O Microduck ficará solto; segure-o.">
      ${es.state === 'pending' ? 'Liberando…' : 'Liberar servos'}<span class="kbd">Espaço</span></button></span>`;
}

function TopBar({ duck, st, live, age, open, hideEStop }) {
  // A barra superior mostra o modo atual (calibração de fábrica ou movimento após a gravação) e a postura. O modo de calibração não usa uma política de movimento.
  // Se o estado continuar em inicialização por mais de 30 s desde a conexão, informe isso; em alguns forks antigos a calibração permanece em configuring_bus.
  const postureText = st ? ({ starting: st.starting_long ? 'Continua iniciando' : 'Iniciando', absent: 'Programa principal parado', homing: 'Levantando',
    servo_session: 'Ajustando os servos' }[st.posture] || WAS[st.posture] || 'Estado desconhecido') : null;
  const modeText = !st ? 'Conectando'
    : st.mode === 'commissioning' ? (st.posture === 'commissioning' ? 'Modo de calibração' : `Calibração · ${postureText}`)
    : st.mode === 'motion' && st.posture !== 'absent' && st.posture !== 'servo_session' ? `Movimento · ${postureText}`
    : postureText;
  const pct = st?.battery?.pct;
  // Ao passar o mouse sobre o nome, exibe o IP atual e outros endereços, também disponíveis para cópia na página Mais.
  const net = st?.net;
  const addrTitle = net?.known ? [`IP ${net.ip_now || 'Desconhecido'}`, ...(net.urls || []).map((u) => u.url)].join('\n') : undefined;
  return html`<header class="topbar">
    <div class="duckid">
      <span class="dot" style=${{ background: duck?.color || '#0F7C80' }}></span>
      <span class="name" title=${addrTitle}>${duck?.label || 'Microduck'}</span>
      ${st?.servo_session ? html`<span class="sv-badge">Ajustando os servos</span>` : null}
      <span class="meta num">${live ? '' : `há ${Math.round(age / 1000)} s · `}${modeText}${typeof pct === 'number' ? ` · ${Math.round(pct)}%` : ''}</span>
    </div>
    <span class=${hideEStop ? 'estop-hidden' : ''}><${EStop} st=${st} live=${live} open=${open} /></span>
  </header>`;
}

// ---------------- Aviso da sessão dos servos (abaixo da barra superior; omitido na própria página Servos) ----------------
// A sessão permanece aberta ao sair da página Servos, mantendo os servos energizados, até o controle ser devolvido.
// Enquanto isso, o programa principal fica parado e o controle e os movimentos não funcionam. O aviso deve aparecer em todas as páginas e permitir voltar a Servos ou devolver o controle.
// O aviso fica fixo abaixo da barra superior e permanece visível ao rolar no celular. Os alertas sobre inicialização manual do programa ou falha ao reassumir aparecem em todas as páginas.
function ServoBar({ st, onServos }) {
  const ss = st?.servo_session;
  if (ss) {
    if (onServos) return null;
    const unk = ss.unknown ? ` · ${ss.unknown} sem leitura de torque (talvez também mantendo força)` : '';
    return html`<div class="banner warn servo-bar" role="status">
      <b>Ajustando servos · ${ss.holding ?? '?'} mantendo força${unk} · programa principal parado (controle e movimentos indisponíveis)</b>
      <span class="sb-acts"><a href="#/servos">Voltar à página Servos</a><${HandBackButton} link=${link} /></span>
      <span class="more sb-more">${ss.restored ? 'O Studio reiniciou e retomou a sessão anterior. ' : ''}Use o botão vermelho acima ou a barra de espaço para liberar os servos (Select do controle não funciona neste estado). Não inicie robotd manualmente; primeiro toque em “Devolver ao programa principal”.</span>
      ${st.servo_marker_error ? html`<span class="more sb-more">${st.servo_marker_error}</span>` : null}</div>`;
  }
  // Se o programa principal for iniciado manualmente durante a sessão, ele libera os servos e disputa a porta serial com o Studio. O Studio fecha o barramento sem enviar comandos.
  if (st?.servo_conflict_s != null) {
    return html`<div class="banner bad servo-bar" role="alert"><b>O programa principal foi iniciado manualmente: ele liberará todos os servos e disputará a porta serial com o Studio.</b>
      <span class="more sb-more">O Studio já fechou o barramento dos servos (sem enviar comandos). Não inicie robotd manualmente novamente; toque em “Devolver ao programa principal” nesta página.</span></div>`;
  }
  // O Studio saiu com uma sessão de servos ativa e não reassumiu o controle ao iniciar novamente.
  if (st?.servo_orphan) {
    return html`<div class="banner bad servo-bar" role="alert"><b>Talvez ainda haja servos mantendo força desde a última sessão. Assuma o controle na página Servos para liberá-los.</b>
      ${onServos ? null : html`<a href="#/servos">Assumir na página Servos</a>`}
      <span class="more sb-more">O Studio não retomou o controle ao reiniciar${st.servo_orphan.why ? ` (${st.servo_orphan.why})` : ''}; se houver urgência, desligue a alimentação.</span></div>`;
  }
  // Após devolver o controle, mantenha o aviso até o programa principal se conectar. O backend o remove quando a conexão é restabelecida.
  if (st?.servo_handback_s != null) {
    if (st.servo_giveback_error) {
      return html`<div class="banner bad servo-bar" role="alert"><b>Controle devolvido, mas o programa principal não iniciou.</b>
        <span class="more sb-more">${st.servo_giveback_error}${st.servo_giveback_hint ? `：${st.servo_giveback_hint}` : ''}</span></div>`;
    }
    return html`<div class="banner warn servo-bar" role="status"><b>Controle devolvido.</b>
      ${st.servo_helper ? html`<span class="more">Reiniciando o programa principal…</span>`
        : html`<span class="more">Este aviso desaparecerá quando o programa principal se conectar. Se continuar desconectado (porque foi parado manualmente), inicie-o no Microduck: <code>sudo systemctl start robotd</code></span>`}
      ${st.servo_handback_note ? html`<span class="more sb-more">${st.servo_handback_note}</span>` : null}</div>`;
  }
  return null;
}

// ---------------- Visão geral ----------------

// Textos do palco conforme a tabela de estados review-impl-plan I2. Os comandos para ficar em pé, caminhar e sentar estão na área do controle, logo abaixo.
// O botão para liberar os servos fica no canto superior direito e permanece visível; há outro no cartão do controle remoto.
const WAS = { holding: 'Em pé', policy: 'Em pé', walking: 'Caminhando', limp: 'Frouxo', sitting: 'Sentado', homing: 'Levantando' };
function stageCopy(st, live, name, age) {
  if (!st) return { h: `Conectando a ${name}…`, sub: 'Ligue o Microduck e conecte este dispositivo à mesma rede Wi-Fi.' };
  if (!live && st.posture !== 'absent') {
    return { h: `${name} não responde há ${Math.round(age / 1000)} s`, sub: `Antes da desconexão, o estado era ${WAS[st.posture] || 'desconhecido'}. O software não consegue controlá-lo agora.`, stale: true };
  }
  switch (st.posture) {
    case 'absent': return { h: 'O programa principal do Microduck não está em execução', sub: 'Pode estar reiniciando (cerca de 2 s). Atenção: parar o programa principal não alivia os servos; eles podem continuar aplicando força.', stale: true };
    case 'starting':
      // Após 30 s em inicialização, substitui a previsão de conclusão em 10 s por um atalho para os registros; forks antigos podem permanecer em configuring_bus durante a calibração.
      if (st.starting_long) {
        return { h: 'O programa principal continua indicando “Iniciando”', act: { href: '#/logs', label: 'Acessar Logs' },
          sub: st.start_error ? `Já se passaram ${st.starting_s} s; travou em: ${st.start_error}. Consulte em Logs a última mensagem do programa principal.`
            : `Já se passaram ${st.starting_s} s. O programa principal pode ter iniciado sem atualizar o estado (um problema de versões antigas) ou pode estar travado. Consulte a última mensagem do programa principal em Logs.` };
      }
      return { h: 'O programa principal está iniciando', sub: st.start_error ? `Travado em: ${st.start_error}` : 'Normalmente termina em até 10 s.' };
    case 'commissioning': return { h: 'Modo de calibração', sub: 'Na primeira configuração: faça a calibração inicial da IMU, centralize os servos com um toque e, na etapa 3, grave os dados no programa principal para mudar automaticamente ao modo de movimento.' };
    case 'limp': return { h: `${name} está sem força nos servos`, sub: 'Segure o robô com as duas mãos, role até “Controle” e toque em “Levantar” (ou pressione + no controle).' };
    case 'homing': return { h: 'Levantando…', sub: 'Segure-o; não solte.' };
    case 'holding': return { h: `${name} está em pé`, sub: 'Role até “Controle”, toque em “Começar a andar” (ou pressione + no controle) e mova o joystick.' };
    case 'policy': return { h: `${name} está em pé e pronto para caminhar`, sub: 'Mova o joystick para caminhar (o controle virtual fica abaixo); toque em “Parar (ficar em pé)” ou pressione + para voltar à postura em pé.' };
    case 'walking': return { h: 'Caminhando', sub: 'Solte o joystick para parar e permanecer em pé.' };
    case 'sitting': return { h: `${name} está sentado`, sub: 'Toque em “Levantar” no controle ou pressione para baixo no direcional.' };
    case 'servo_session': return { h: 'Ajustando os servos', sub: 'O programa principal está parado (controle e movimentos ficam indisponíveis). Os servos continuam mantendo a posição ao sair da página; toque em “Devolver ao programa principal” para liberar o controle.' };
    default: return { h: name, sub: 'Não foi possível identificar a postura atual.' };
  }
}

// No palco, a rolagem com a roda e um dedo no celular continua sendo da página. Duck3D desativa o zoom e a rotação com um dedo.
// No computador, arraste com o mouse; no celular, gire com dois dedos. O palco é mais baixo no celular para mostrar os indicadores e a lista inicial na primeira tela.
// O aviso de desconexão sobrepõe o palco sem empurrar os controles para baixo.
function Stage({ st, live, age, name }) {
  const canvasRef = useRef(null);
  const duckRef = useRef(null);
  const [msg, setMsg] = useState(null);
  const [moved, setMoved] = useState(false);     // Mostra o comando para centralizar a vista depois que o usuário a girar.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const phone = window.innerWidth < 700;   // No celular, centraliza o Microduck um pouco acima e reduz o tamanho para deixar espaço ao texto.
    const d = new Duck3D(canvasRef.current, phone ? { view: 'front34', centerX: 0.5, centerY: 0.34, fill: 0.6, pageScroll: true }
      : { view: 'front34', centerX: 0.61, pageScroll: true });
    duckRef.current = d;
    d.onUserMove = () => setMoved(true);
    d.load('model/').then(() => setReady(true)).catch((e) => setMsg(`Não foi possível carregar o modelo 3D: ${e.message}`));
    return () => d.dispose();
  }, []);

  useEffect(() => {
    if (!duckRef.current || !st) return;
    duckRef.current.setJoints(st.joints);
    duckRef.current.setGravity(st.gravity);
  }, [st]);

  const c = stageCopy(st, live, name, age);
  // Sem dados das articulações (null), trate o estado como desatualizado para não exibir a pose padrão como se fosse uma leitura atual.
  const jointsOld = st?.joints_age_ms == null || st.joints_age_ms > 1000;
  return html`<section class="stage stage-ov" aria-label="Estado atual do Microduck">
    ${/* A classe controla o aspecto acinzentado. Passar style ao canvas sobrescreveria touch-action:pan-y de duck3d e faria o gesto de dois dedos ampliar a página inteira. */ ''}
    <canvas ref=${canvasRef} class=${c.stale || jointsOld ? 'stage-stale' : ''}></canvas>
    ${!live && st ? html`<div class="banner bad stage-banner" role="alert"><${Badge} kind="bad" />
      <b>Sem conexão com ${name} · ${isFinite(age) ? Math.round(age / 1000) + ' s' : ''}</b><span class="more">O Microduck que estiver em pé vai parar e permanecer em pé.</span>
      <a href="#" onClick=${(e) => { e.preventDefault(); link.reconnect(); }}>Reconectar</a></div>` : null}
    <div class="copy">
      <h1>${c.h}</h1>
      <p class="sub">${c.sub}</p>
      ${c.act ? html`<div class="btns"><button class="btn2 stage-act" onClick=${(e) => { e.currentTarget.blur(); location.hash = c.act.href; }}>${c.act.label}</button></div>` : null}
      ${msg ? html`<span class="tip" role="alert">${msg}</span>` : c.tip ? html`<span class="tip">${c.tip}</span>` : null}
    </div>
    ${c.stale && isFinite(age) ? html`<span class="age num">há ${Math.round(age / 1000)} s</span>` : null}
    ${!ready ? html`<span class="sv-loading">Carregando modelo 3D…</span>` : null}
    ${moved ? html`<button class="reset-view" onClick=${(e) => { e.currentTarget.blur(); duckRef.current?.resetView(); setMoved(false); }}>Centralizar vista</button>` : null}
  </section>`;
}

// Indicador de temperatura da placa principal. Os campos estão em studio/state.py, cpu_view. Frequência reduzida aparece em vermelho; uma limitação sem relação com temperatura é descrita como tal.
// A partir de 80 °C, o indicador fica laranja e só volta ao normal abaixo de 77 °C. Se a leitura falhar, mostra “—” e o motivo; 80 °C é um limite informativo definido pelo projeto, não um erro.
function boardCell(cpu) {
  const mhz = (k) => (typeof k === 'number' ? Math.round(k / 1000) : '?');
  if (typeof cpu?.c !== 'number') return { big: '—', small: cpu?.why || 'Indisponível', kind: null };
  const studio = cpu.src === 'studio' ? ' · leitura feita pelo Studio' : '';
  if (cpu.throttled) return { big: Math.round(cpu.c), small: `Frequência reduzida: ${mhz(cpu.khz)} / ${mhz(cpu.max_khz)} MHz${studio}`, kind: 'bad' };
  if (cpu.hot) return { big: Math.round(cpu.c), small: `Temperatura alta (alerta a partir de 80 °C)${studio}`, kind: 'warn' };
  if (cpu.limited) return { big: Math.round(cpu.c), small: `Frequência limitada a ${mhz(cpu.khz)} MHz (sem relação com temperatura)${studio}`, kind: null };
  if (cpu.throttled == null) return { big: Math.round(cpu.c), small: `Não foi possível ler a frequência${studio}`, kind: null };
  return { big: Math.round(cpu.c), small: `Normal${studio}`, kind: null };
}

// O indicador do controle usa status/estop da amostra do controle, a mesma fonte do cabeçalho do controle e das etapas 3 e 4 da lista inicial.
// Só usa state.pad quando o backend do controle não está disponível, como no modo de bancada. A parada de emergência do controle é distinta do comando superior para liberar servos.
function padCell(st, pd) {
  if (!pd) {
    const p = st?.pad || {};
    return { word: !p.known ? 'Desconhecido' : p.connected ? 'Conectado' : 'Desconectado',
      small: !p.known ? 'Não foi possível ler o estado do controle' : p.connected ? `${p.name || 'Controle'}${p.estop_ok ? ' · parada de emergência do controle ativa' : ''}` : 'Emparelhar' };
  }
  const s = pd.status || {}, lv = pd.live || {}, es = pd.estop || {};
  const attached = lv.state === 'attached';
  const known = !!s.known || attached;
  const connected = !!s.active || attached;
  const name = s.active?.name || (attached ? lv.device?.name : null) || 'Controle';
  const esw = { ok: 'Parada de emergência do controle ativa ✓', unknown: 'Verificação da parada de emergência do controle incompleta', bad: 'Parada de emergência do controle inativa' }[es.state] || '';
  if (!known) return { word: 'Desconhecido', small: 'Não foi possível ler o estado do controle (configd)' };
  if (connected) return { word: 'Conectado', small: `${name}${esw ? ` · ${esw}` : ''}` };
  return { word: 'Desconectado', small: (s.pads || []).length ? 'Já emparelhado: ligue o controle para conectar automaticamente' : 'Emparelhar' };
}

// Mede a altura dos elementos fixos e grava os valores nas variáveis CSS da raiz: --bar-h para o aviso dos servos e --band-h para a faixa de indicadores.
// O cartão 3D do controle, a coluna da página Servos e a posição de rolagem da área do controle respeitam essas alturas. Elementos não fixos ou ocultos contam como 0.
function useStickyHeight(name) {
  const ro = useRef(null);
  return useCallback((el) => {
    const root = document.documentElement.style;
    ro.current?.disconnect();
    ro.current = null;
    const put = () => root.setProperty(name, el && getComputedStyle(el).position === 'sticky' ? `${el.offsetHeight}px` : '0px');
    put();
    if (el && typeof ResizeObserver !== 'undefined') {
      ro.current = new ResizeObserver(put);
      ro.current.observe(el);
    }
  }, [name]);
}

function Band({ st, pd, gray, onSame, sensorsActive }) {
  const bandRef = useStickyHeight('--band-h');
  const b = st?.battery || {}, s = st?.servos || {}, imu = st?.imu || {};
  const imuWord = { ok: 'Normal', unverified: 'Orientação não confirmada', frozen: 'Leituras congeladas', missing: 'Sem leitura' }[imu.status] || '—';
  const imuKind = { unverified: 'warn', frozen: 'bad', missing: 'bad' }[imu.status];
  const pct = typeof b.pct === 'number' ? Math.round(b.pct) : null;
  const cpu = boardCell(st?.cpu);
  const pad = padCell(st, pd);
  return html`<section class=${'band board' + (gray ? ' stale' : '')} aria-label="Estado" ref=${bandRef}>
    <${BatteryCell} b=${b} />
    <div>
      <span class="label">Servos</span>
      <span class="num" style="display:flex;align-items:baseline;gap:4px"><span class="big">${s.online ?? '—'}</span><span class="unit">/ ${s.total ?? 15}</span></span>
      <span class="small">${s.hottest ? `Mais quente: ${Math.round(s.hottest.c)} °C · ${s.hottest.name}` : '—'}</span>
    </div>
    <a href="#/imu">
      <span class="label">IMU</span>
      <span class="word">${imuKind ? html`<${Badge} kind=${imuKind} />` : null}${imuWord}</span>
      <span class="small">${{ unverified: 'Fique apenas em pé por enquanto', ok: 'Orientação confirmada' }[imu.status] || 'Calibrar'}</span>
    </a>
    <${SensorBandCells} api=${api} active=${sensorsActive} />
    <a href="#/pad" onClick=${(e) => onSame(e, '#/pad')}>
      <span class="label">Controle</span>
      <span class="word">${pad.word}</span>
      <span class="small">${pad.small}</span>
    </a>
    <div class=${'band-cpu' + (cpu.kind ? ` ${cpu.kind}` : '')}>
      <span class="label">Placa principal</span>
      <span class="num" style="display:flex;align-items:baseline;gap:4px"><span class="big">${cpu.big}</span>${cpu.big !== '—' ? html`<span class="unit">°C</span>` : null}</span>
      <span class="small">${cpu.kind ? html`<${Badge} kind=${cpu.kind} /> ` : null}${cpu.small}</span>
    </div>
  </section>`;
}

// ---------------- Lista inicial (seis etapas, conexão com o Microduck no cabeçalho e gravação no programa principal) ----------------
// O backend avalia as etapas em studio/onboard.py a cada 0,5 s; aqui apenas exibimos os dados. Estados: concluído, ignorado, pendente/refazer, não feito ou indisponível.
// A próxima etapa é o primeiro item pendente ou não feito (ob.next). Seu primeiro botão ganha destaque; as etapas seguintes continuam acessíveis.
// Cada linha oferece Fazer, Concluído e Pular. A confirmação em duas etapas é usada quando uma ação pode ter consequências, conforme mark.*.ask do backend.
// A segunda confirmação envia confirmed. Itens concluídos podem ser refeitos; itens marcados pelo usuário podem ser desfeitos. A lista concluída pode ser expandida; o estado fica em localStorage.

const ONB_MARK = { ok: '✓', skip: '↷', todo: '●', no: '○', unk: '?' };
const ONB_WORD = { ok: 'Concluído', skip: 'Ignorado', todo: 'Pendente', no: 'Não feito', unk: 'Indisponível' };
const ONB_OPEN_KEY = 'studio.onb.open';
const ONB_FROZEN = 'Durante o ajuste dos servos, a lista permanece congelada. As marcações de conclusão e de etapa ignorada só aparecem depois de devolver o controle ao programa principal.';
function fmtWhen(w) {
  if (w == null || w === '') return null;
  let d = null;
  if (typeof w === 'number') d = new Date(w * 1000);
  else if (typeof w === 'string') { const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(w); if (m) d = new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]); }
  if (!d || isNaN(d.getTime())) return String(w);
  if (d.getFullYear() < 2024) return 'Relógio incorreto (o Microduck está sem conexão)';
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function loadOnbOpen() { try { return localStorage.getItem(ONB_OPEN_KEY) === '1'; } catch { return false; } }
function saveOnbOpen(v) { try { localStorage.setItem(ONB_OPEN_KEY, v ? '1' : '0'); } catch { /* Modo privado. */ } }

function Onboard({ st, live }) {
  const ob = st?.onboarding;
  const [msg, setMsg] = useState(null);
  const [open, setOpen] = useState(loadOnbOpen);
  const [cprev, setCprev] = useState(null);       // Resultado da prévia: direção e limites de cada servo, orientação da IMU e TOML.
  const [cmsg, setCmsg] = useState(null);         // Mensagem da ação de prévia ou gravação.
  const [cbusy, setCbusy] = useState(false);
  const [copen, setCopen] = useState(false);      // Recolhe o cartão de gravação quando a etapa já foi feita ou não pode ser avaliada.
  const job = st?.commit?.job;                   // Progresso/resultado da gravação enviado pelo Studio; usado somente na etapa 3.
  // Quando o cartão de progresso aparece, ele substitui a confirmação temporária. O cartão de sucesso fecha após 2 minutos.
  useEffect(() => {
    if (job) setCmsg(null);
  }, [job?.phase, job?.ok, job?.finished]);
  // A gravação reinicia o programa principal e interrompe a conexão. Mostre o progresso e os erros da etapa 3 mesmo sem conexão.
  // O backend deixa de enviar o resultado de sucesso após 2 minutos, e o cartão desaparece.
  if (!live && job) {
    const title = job.phase === 'running' ? 'Gravar no programa principal' : (job.ok ? 'Gravação concluída' : 'Falha na gravação');
    return html`<section class="onb board" data-step="commit" aria-label="Progresso da gravação no programa principal">
      <div class="onb-h"><b>${title}</b><span class="quiet">O programa principal está reiniciando; a página está desconectada por enquanto.</span></div>
      <div class="onb-commit">
        ${job.phase === 'running'
          ? html`<div class="onb-commit-job" role="status"><span class="onb-spin">⋯</span>${job.msg || 'Gravando…'}</div>`
          : html`<div class=${'onb-commit-msg ' + (job.ok ? 'ok' : 'bad')}>${job.reason || job.msg || ''}</div>`}
        ${job.phase !== 'running' && !job.ok ? html`<p class="onb-tip">O assistente restaurará o arquivo de calibração e o modo anteriores; aguarde o retorno do programa principal para conferir a etapa 3.</p>` : null}
      </div>
    </section>`;
  }
  if (!live) return html`<section class="onb board"><div class="onb-h"><b>Lista de primeiros passos</b><span class="quiet">Verificação indisponível sem conexão</span></div></section>`;
  if (!ob) return html`<section class="onb board"><div class="onb-h"><b>Lista de primeiros passos</b><span class="quiet">Verificando…</span></div></section>`;
  const head = ob.header || {};
  if (head.kind === 'bench') return html`<section class="onb board"><div class="onb-h"><b>Lista de primeiros passos</b><span class="quiet">${head.text}</span></div></section>`;
  const done = ob.all_done && head.ok;
  const n = ob.skipped_n || 0;
  const m = ob.marked_n || 0;
  const counts = [n ? `ignoradas: ${n}` : '', m ? `marcadas como concluídas: ${m}` : ''].filter(Boolean).join('; ');
  const doneText = `As 6 etapas iniciais foram concluídas${counts ? ` (${counts})` : ''}`;
  const toggle = () => { const v = !open; setOpen(v); saveOnbOpen(v); };
  if (done && !open) {
    return html`<section class="onb board onb-done" aria-label="Lista de primeiros passos">
      <button class="onb-fold" aria-expanded="false" onClick=${toggle}><span class="onb-mark onb-ok">✓</span><b>${doneText}</b>
        <span class="onb-more">Expandir</span></button></section>`;
  }
  const op = async (args, okText) => {
    const r = await link.cmd('onboard.op', args, 8000);
    setMsg(r.ok ? (okText ? { ok: true, text: okText } : null) : { ok: false, text: r.reason || r.error || 'Não registrado' });
  };
  const go = async (a, row) => {
    setMsg(null);
    if (a.do === 'servos') location.hash = '#/servos';
    else if (a.do === 'imu') location.hash = '#/imu';
    else if (a.do === 'commit') {
      setCopen(true);
      setTimeout(() => document.querySelector('[data-step="commit"] .onb-commit')?.scrollIntoView({ block: 'center' }), 50);
    }
    else if (a.do === 'pad_wizard') padGo('wizard');
    else if (a.do === 'pad_known') padGo('known');
    else if (a.do === 'estop') padGo('estop');
    else if (a.do === 'remote') padGo('remote');
    else if (a.do === 'robotd' || a.do === 'logs') location.hash = '#/logs';   // Abre os registros para conferir a etapa do modo do programa principal.
  };
  // Etapa 3: calcula uma prévia (dry_run do assistente ou cálculo direto no Studio do computador) e, depois, grava. A gravação começa após o ack; o progresso fica em st.commit.job.
  const commitPreview = async () => {
    if (cprev) { setCprev(null); return; }
    setCmsg(null);
    const r = await link.cmd('calib.op', { op: 'preview' }, 20000);
    if (r.ok) setCprev(r.data || {});
    else setCmsg({ ok: false, text: r.reason || r.error || 'Não foi possível calcular' });
  };
  const commitRun = async () => {
    setCmsg(null);
    setCbusy(true);
    try {
      const r = await link.cmd('calib.op', { op: 'commit' }, 20000);
      if (!r.ok) setCmsg({ ok: false, text: r.reason || r.error || 'Não foi possível iniciar a gravação' });
      else setCmsg({ ok: true, text: 'Gravação iniciada. O programa principal será reiniciado; aguarde.' });
    } finally {
      setCbusy(false);
    }
  };
  const btn = (a, row, dark) => html`<button class=${dark ? 'btn-dark' : 'btn-light'} onClick=${() => go(a, row)}>${a.label}</button>`;
  const frozen = !!ob.frozen;               // Durante o ajuste dos servos, a lista fica congelada; marcar ou desfazer exige dois cliques e só aparece após devolver o controle.
  const fa = ob.frozen_ask || {};
  // Use TwoStep para Concluído/done ou Pular/skip quando o backend exigir duas confirmações (mark.*.ask) ou quando a lista estiver congelada; só a segunda envia confirmed.
  const markBtn = (row, kind, label, cls) => {
    const ask = (row.mark || {})[kind]?.ask || (frozen ? fa[kind] : null);
    const args = { op: kind, step: row.key };
    return ask ? html`<${TwoStep} label=${label} ask=${ask} cls=${'btn-light ' + cls} askCls="btn-light onb-skip-arm"
        onConfirm=${() => op({ ...args, confirmed: true })} />`
      : html`<button class=${'btn-light ' + cls} onClick=${() => op(args)}>${label}</button>`;
  };
  const undoBtn = (row) => {
    const args = { op: row.marked === 'skip' ? 'unskip' : 'undone', step: row.key };
    const label = row.marked === 'skip' ? 'Desfazer etapa ignorada' : 'Cancelar';
    return frozen ? html`<${TwoStep} label=${label} ask=${fa.undo || 'Tem certeza de que deseja cancelar?'} cls="btn-light onb-unskip" askCls="btn-light onb-skip-arm"
        onConfirm=${() => op({ ...args, confirmed: true })} />`
      : html`<button class="btn-light onb-unskip" onClick=${() => op(args)}>${label}</button>`;
  };
  return html`<section class=${'onb board' + (ob.frozen ? ' onb-frozen' : '')} aria-label="Lista de primeiros passos">
    <div class="onb-h">
      <b>Lista de primeiros passos</b>
      ${done ? html`<button class="onb-fold onb-fold-h" aria-expanded="true" onClick=${toggle}><span class="onb-mark onb-ok">✓</span>${doneText}
        <span class="onb-more">Recolher</span></button>`
        : head.ok ? html`<span class="onb-conn"><span class="onb-mark onb-ok">✓</span>Microduck conectado</span>`
        : html`<span class="onb-conn onb-conn-bad"><${Badge} kind=${head.kind === 'servo' || head.kind === 'connecting' || head.kind === 'bench' ? 'warn' : 'bad'} />
          ${head.text}${head.raw ? html`<small>Texto original: ${head.raw}</small>` : null}</span>`}
      ${ob.frozen ? html`<span class="onb-tip onb-noskip">${ONB_FROZEN}</span>` : null}
    </div>
    ${msg ? html`<div class=${'banner ' + (msg.ok ? 'warn' : 'bad')} role="status"><span>${msg.text}</span>
      <a href="#" onClick=${(e) => { e.preventDefault(); setMsg(null); }}>Entendi</a></div>` : null}
    <ol class="onb-rows">
      ${(ob.rows || []).map((r) => {
        const now = ob.next === r.key;
        const when = fmtWhen(r.when);
        const goA = { do: r.go, label: 'Fazer' };
        // Expande o cartão da etapa 3 somente na linha de gravação quando ela estiver pendente, em andamento, recém-concluída ou aberta para consulta/refação.
        // Recolhe o cartão quando a etapa estiver concluída, ignorada ou indisponível.
        const isCommit = r.key === 'commit' && (r.state === 'todo' || r.state === 'no' || copen || !!job || !!cmsg || !!cprev);
        let acts;
        if (r.marked) {
          // Para marcações feitas pelo usuário, oferece Refazer e Cancelar/Desfazer etapa ignorada.
          acts = html`<button class="btn-light onb-redo" onClick=${() => go(goA, r)}>Refazer</button>${undoBtn(r)}`;
        } else if (r.state === 'ok') acts = html`<button class="btn-light onb-redo" onClick=${() => go(goA, r)}>Refazer</button>`;
        else {
          // Três ações: Fazer (ou abrir a página de destino), Concluído e Pular. Se a etapa apontou um problema, a primeira ação vira Refazer.
          const first = (r.actions || []).length ? r.actions : [goA];
          acts = html`${first.map((a, i) => btn(r.found && i === 0 ? { ...a, label: 'Refazer' }
            : now && i === 0 ? { ...a, label: 'Fazer' } : a, r, now && i === 0))}${markBtn(r, 'done', 'Concluído', 'onb-donebtn')}${markBtn(r, 'skip', 'Pular', 'onb-skip')}`;
        }
        return html`<li class=${'onb-row onb-' + r.state + (now ? ' onb-now' : '')} key=${r.key} data-step=${r.key}>
          <span class=${'onb-mark onb-' + r.state} aria-label=${ONB_WORD[r.state] || 'Indisponível'}>${ONB_MARK[r.state] || '?'}</span>
          <span class="onb-body">
            <span class="onb-title"><b>${r.n} ${r.title}</b>${now ? html`<span class="onb-tag">Próxima etapa</span>` : null}${when && !r.marked ? html`<span class="onb-when num">${when}</span>` : null}</span>
            <span class="onb-text">${r.text}${r.marked ? ` (${when || 'horário desconhecido'})` : ''}</span>
            ${r.note ? html`<span class="onb-tip">${r.marked ? `Agora: ${r.note}` : r.note}</span>` : null}
            ${r.tip && r.state !== 'ok' && r.state !== 'skip' ? html`<span class="onb-tip">Dica: ${r.tip}</span>` : null}
            ${isCommit ? html`<div class="onb-commit">
              <div class="onb-commit-desc">${r.desc || ''}</div>
              ${(r.commit?.items || []).length ? html`<ul class="onb-checks">
                ${r.commit.items.map((it) => html`<li class=${it.ok ? 'ok' : 'bad'}>
                  <span class="onb-check-mark" aria-label=${it.ok ? 'Pronto' : 'Ainda não funciona'}>${it.ok ? '✓' : '×'}</span>
                  <span class="onb-check-body"><b>${it.label}</b><span>${it.text}</span></span>
                  ${!it.ok && it.action ? html`<button class="btn-light onb-check-go" onClick=${() => go(it.action, r)}>${it.action.label || 'Fazer'}</button>` : null}
                </li>`)}
              </ul>` : null}
              <div class="onb-commit-acts">
                <button class="btn-light" disabled=${cbusy} onClick=${commitPreview}>${cprev ? 'Ocultar prévia' : 'Ver prévia da gravação'}</button>
                ${/* Se a etapa 2 foi marcada, a segunda confirmação esclarece que a IMU será gravada com a orientação padrão. */ ''}
                <${TwoStep} label="Gravar no programa principal" ask=${r.commit?.imu_default ? 'Confirmar gravação da IMU com a orientação padrão?' : 'O programa principal será reiniciado e os servos serão liberados. Segure o Microduck.'}
                  cls="btn-dark" disabled=${!r.commit?.ready || cbusy}
                  title=${!r.commit?.ready ? 'Ainda há itens pendentes na lista acima.' : ''} onConfirm=${commitRun} />
              </div>
              ${cmsg ? html`<div class=${'onb-commit-msg ' + (cmsg.ok ? 'ok' : 'bad')}>${cmsg.text}</div>` : null}
              ${job && job.phase === 'running' ? html`<div class="onb-commit-job" role="status"><span class="onb-spin">⋯</span>${job.msg || 'Gravando…'}</div>` : null}
              ${job && job.phase !== 'running' && job.reason ? html`<div class=${'onb-commit-msg ' + (job.ok ? 'ok' : 'bad')}>${job.reason}</div>` : null}
              ${cprev ? html`<div class="onb-preview">
                <div class="onb-preview-imu"><b>IMU</b> ${cprev.imu?.label || ''} · ${cprev.imu?.text || ''}${cprev.imu?.default ? ` (orientação padrão: ${cprev.imu.default})` : ''}</div>
                <table class="onb-preview-table"><thead><tr><th>Articulação</th><th>Direção</th><th>Limites</th></tr></thead><tbody>
                  ${(cprev.joints || []).map((j) => html`<tr><td>${j.cn || j.name}</td><td>${j.direction > 0 ? '+1' : '−1'}</td><td class="num">${j.min_deg}° ~ ${j.max_deg}°</td></tr>`)}
                </tbody></table>
                <details class="onb-preview-toml"><summary>Arquivo que será gravado</summary><pre>${cprev.toml || ''}</pre></details>
              </div>` : null}
            </div>` : null}
          </span>
          <span class="onb-acts">${acts}</span>
        </li>`;
      })}
    </ol>
  </section>`;
}

// Evita repetir tarefas já explicadas na lista inicial, mas só quando a linha ou o cabeçalho realmente descrevem o mesmo problema.
// Se a lista indicar indisponibilidade, mantenha a tarefa pendente.
const TODO_IN_ONB = {
  starting: (ob) => ['starting', 'stuck_calib'].includes(ob.header?.kind),
  absent: (ob) => ob.header?.kind === 'absent',
  servo_session: (ob) => ob.header?.kind === 'servo',
  imu_unverified: (ob) => ['todo', 'no'].includes((ob.rows || []).find((r) => r.key === 'imu')?.state),
};
function Todo({ st, live }) {
  const ob = st?.onboarding;
  const all = (st?.todo || []).filter((it) => !(ob && TODO_IN_ONB[it.key] && TODO_IN_ONB[it.key](ob)));
  const items = all.slice(0, 2);
  const more = all.length - items.length;
  if (!live) return html`<section class="todo board"><span class="quiet">Verificação indisponível sem conexão</span></section>`;
  if (!items.length) {
    return html`<section class="todo board"><span class="quiet">Nenhuma tarefa pendente</span>
      <span class="when num">${st?.health_age_ms != null ? `verificado há ${Math.round(st.health_age_ms / 1000)} s` : ''}</span></section>`;
  }
  return html`<section class="todo board list">
    ${items.map((it) => html`<div class="item">
      <${Badge} kind=${it.level === 'error' ? 'bad' : 'warn'} />
      <span class="msg">${it.msg}</span>
      <span class="hint">${it.hint || ''}</span>
    </div>`)}
    ${more > 0 ? html`<a href="#/logs" style="font-size:13px">Ver mais ${more} ›</a>` : null}
  </section>`;
}

// Visão geral: cartão de Wi-Fi quando o ponto de acesso está ativo, palco, indicadores, lista inicial, tarefas pendentes e área do controle abaixo.
function Overview({ st, live, age, duck, pd, onSame, tune, sensorsActive }) {
  // Acrescenta um espaço após nomes de host em inglês antes do texto seguinte.
  const short = duck?.short || 'Microduck';
  const name = /[A-Za-z0-9]$/.test(short) ? short + ' ' : short;
  return html`<div class="overview">
    ${st?.net?.known && st.net.mode === 'hotspot'
      ? html`<${WifiCard} net=${st.net} link=${link} secure=${st?.auth?.has_password} />` : null}
    <${Stage} st=${st} live=${live} age=${age} name=${name} />
    <${Band} st=${st} pd=${pd} gray=${age > STALE_GRAY_MS} onSame=${onSame} sensorsActive=${sensorsActive} />
    <${Onboard} st=${st} live=${live} />
    <${Todo} st=${st} live=${live} />
    <${PadPage} st=${st} pad=${pd} link=${link} api=${api} previewActive=${sensorsActive} live=${live} />
    <${TuneSection} tune=${tune} />
  </div>`;
}

// ---------------- Registros ----------------

function Logs() {
  const [items, setItems] = useState([]);
  const [onlyBad, setOnlyBad] = useState(false);
  const [cat, setCat] = useState('');
  useEffect(() => {
    api('/api/logs?limit=300').then((r) => setItems(r.items || []));
    return link.on((m) => { if (m.t === 'log') setItems((xs) => [...xs.slice(-499), m.entry]); });
  }, []);
  const shown = items.filter((e) => (!onlyBad || e.level !== 'info') && (!cat || e.cat === cat));
  const cats = [...new Set(items.map((e) => e.cat))];
  const copy = () => navigator.clipboard && navigator.clipboard.writeText(shown.map((e) =>
    `${e.t} [${e.cat}]${e.level === 'info' ? '' : `[${e.level}]`} ${e.msg}${e.step ? ` · ${e.level === 'info' ? 'Etapa' : 'Travado em'}: ${e.step}` : ''}${e.raw ? ` · Texto original: ${e.raw}` : ''}${e.hint ? ` · Sugestão: ${e.hint}` : ''}`).join('\n'));
  return html`<div style="display:flex;flex-direction:column;gap:12px">
    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:12px">
      <h1 style="margin:0;font-size:28px;font-weight:600;flex:1">Logs</h1>
      <select value=${cat} onChange=${(e) => setCat(e.target.value)} aria-label="Filtrar por categoria">
        <option value="">Todas as categorias</option>${cats.map((c) => html`<option value=${c}>${c}</option>`)}
      </select>
      <label style="font-size:14px"><input type="checkbox" checked=${onlyBad} onChange=${(e) => setOnlyBad(e.target.checked)} /> Mostrar somente avisos e erros</label>
      <button onClick=${copy} style="height:34px;padding:0 14px;border:0;border-radius:999px;background:#E5E5EA">Copiar</button>
      <a class="logs-export" href="/api/diag" style="font-size:14px" title="Inclui o número de série do Microduck e o IP da rede local">Exportar pacote de diagnóstico (para pedir ajuda)</a>
    </div>
    <div class="board" style="padding:8px 16px;font-size:14px;line-height:1.7">
      ${shown.length ? shown.slice().reverse().map((e) => html`<div key=${e.n} style="padding:4px 0;border-top:1px solid var(--line)">
        <span class="num" style="color:var(--text-2)">${e.t}</span> <span style="color:var(--text-2)">[${e.cat}]</span>
        ${e.level === 'warn' ? html` <${Badge} kind="warn" />` : e.level === 'error' ? html` <${Badge} kind="bad" />` : ''} ${e.msg}
        ${e.step || e.raw || e.hint ? html`<div style="font-size:13px;color:var(--text-2)">
          ${e.step ? html`${e.level === 'info' ? 'Etapa' : 'Travado em'}: ${e.step}　` : ''}${e.raw ? html`Texto original: ${e.raw}　` : ''}${e.hint ? html`Sugestão: ${e.hint}` : ''}</div>` : null}
      </div>`) : html`<div style="color:var(--text-2)">Ainda não há registros.</div>`}
    </div>
  </div>`;
}

// A página recebe dez atualizações de estado por segundo, e Main é redesenhado. Os registros não dependem desse estado; evite redesenhar as 500 linhas a cada atualização.
class LogsPage extends Component {
  shouldComponentUpdate() { return false; }
  render() { return html`<${Logs} />`; }
}

// ---------------- Configurações ----------------

const STAGES = [['mid', 'Cinza médio (recomendado)'], ['graphite', 'Grafite'], ['light', 'Cinza claro']];
function applyStage(v) {
  if (v === 'mid') document.documentElement.removeAttribute('data-stage');
  else document.documentElement.setAttribute('data-stage', v);
}
function loadStage() { try { return localStorage.getItem('studio.stage') || 'mid'; } catch { return 'mid'; } }

function PasswordSettings({ hasPassword }) {
  const [pw, setPw] = useState('');
  const [again, setAgain] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    setErr(null); setMsg(null);
    if (pw.length < 6) { setErr('A senha deve ter pelo menos 6 caracteres'); return; }
    if (pw !== again) { setErr('As senhas não coincidem'); return; }
    setBusy(true);
    let r;
    try { r = await api('/api/password', { action: 'set', password: pw, confirm: again }); }
    catch { r = { error: 'Não foi possível conectar ao Microduck. Verifique a rede e tente novamente.' }; }
    setBusy(false);
    if (!r.ok) { setErr(r.status === 401 ? 'Sua sessão expirou. Atualize a página e entre novamente.' : (r.error || 'Não foi possível alterar a senha')); return; }
    setPw(''); setAgain(''); setMsg('Senha de acesso salva. Esta sessão do navegador continua ativa.');
  };
  const clear = async () => {
    setErr(null); setMsg(null);
    let r;
    try { r = await api('/api/password', { action: 'clear' }); }
    catch { r = { error: 'Não foi possível conectar ao Microduck. Verifique a rede e tente novamente.' }; }
    if (!r.ok) { setErr(r.status === 401 ? 'Sua sessão expirou. Atualize a página e entre novamente.' : (r.error || 'Não foi possível remover a senha')); return; }
    location.reload();
  };
  if (hasPassword == null) {
    return html`<div class="board password-settings" style="padding:16px 20px">
      <div style="font-size:15px;font-weight:600">Senha de acesso</div>
      <div style="font-size:13px;color:var(--text-2)">Carregando o estado da sessão…</div></div>`;
  }
  return html`<form class="board password-settings" style="padding:16px 20px;display:flex;flex-direction:column;gap:10px"
    onSubmit=${submit}>
    <div style="font-size:15px;font-weight:600">${hasPassword ? 'Senha de acesso' : 'Defina uma senha de acesso'}</div>
    <div style="font-size:13px;line-height:1.6;color:var(--text-2)">
      A senha do ponto de acesso é compartilhada. Depois de definir uma senha de acesso, quem se conectar ao ponto também precisará entrar para controlar o Microduck. Use pelo menos 6 caracteres.
      ${hasPassword ? 'A alteração encerra as sessões nos outros navegadores; esta sessão continuará ativa.' : ''}
    </div>
    <label style="display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--text-2)">
      ${hasPassword ? 'Nova senha' : 'Senha'}
      <input type="password" name="password" autocomplete="new-password" value=${pw} required minLength="6"
        onInput=${(e) => setPw(e.target.value)} style="height:40px;padding:0 10px;border:1px solid var(--line);border-radius:8px" />
    </label>
    <label style="display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--text-2)">
      Digite novamente
      <input type="password" name="confirm" autocomplete="new-password" value=${again} required minLength="6"
        onInput=${(e) => setAgain(e.target.value)} style="height:40px;padding:0 10px;border:1px solid var(--line);border-radius:8px" />
    </label>
    ${err ? html`<div role="alert" style="font-size:13px;color:var(--danger)">${err}</div>` : null}
    ${msg ? html`<div style="font-size:13px;color:var(--text-2)">${msg}</div>` : null}
    <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center">
      <button type="submit" disabled=${busy || !pw || !again}
        style="height:40px;padding:0 18px;border:0;border-radius:999px;background:var(--blue);color:#FFF;font-weight:600">
        ${busy ? 'Salvando…' : (hasPassword ? 'Alterar senha de acesso' : 'Definir senha de acesso')}</button>
      ${hasPassword ? html`<${TwoStep} label="Remover senha de acesso" ask="Tem certeza de que deseja removê-la?" onConfirm=${clear} />` : null}
    </div>
  </form>`;
}

// O acesso SSH permite corrigir problemas sem regravar o cartão. A imagem de fábrica aceita somente chaves e não inclui chaves de terceiros nem senha padrão.
// Defina uma senha nesta página antes de ativar o acesso; o backend também exige essa proteção.
function SshSettings({ hasPassword }) {
  const [ssh, setSsh] = useState(null);
  const [loadErr, setLoadErr] = useState(null);
  const [pw, setPw] = useState('');
  const [again, setAgain] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const load = async () => {
    let r;
    try { r = await api('/api/ssh', { action: 'status' }, 15000); } catch { r = { error: 'Não foi possível conectar ao Microduck' }; }
    if (r.ok) { setSsh(r.ssh); setLoadErr(null); } else setLoadErr(r.error || 'Não foi possível ler o estado do SSH');
  };
  useEffect(() => { load(); }, []);
  const on = ssh?.password_login === true;
  const keys = ssh?.key_list || [];
  const cmd = `ssh ${ssh?.user || 'radxa'}@${location.hostname}`;
  const call = async (body, okText) => {
    setErr(null); setMsg(null); setBusy(true);
    let r;
    try { r = await api('/api/ssh', body, 60000); } catch { r = { error: 'Não foi possível conectar ao Microduck. Verifique a rede e tente novamente.' }; }
    setBusy(false);
    if (!r.ok) { setErr(r.status === 401 ? 'Sua sessão expirou. Atualize a página e entre novamente.' : (r.error || 'Não foi possível concluir a operação')); return null; }
    if (r.ssh) setSsh(r.ssh);
    setMsg(typeof okText === 'function' ? okText(r) : okText);
    return r;
  };
  const submitPw = async (e) => {
    e.preventDefault();
    setErr(null); setMsg(null);
    if (pw.length < 8) { setErr('A senha do SSH deve ter pelo menos 8 caracteres'); return; }
    if (pw !== again) { setErr('As senhas não coincidem'); return; }
    const r = await call({ action: 'on', password: pw, confirm: again },
      on ? 'Senha do SSH alterada.' : 'Acesso por senha SSH ativado. Execute o comando acima no computador e informe a senha definida.');
    if (r) { setPw(''); setAgain(''); }
  };
  const submitKey = async (e) => {
    e.preventDefault();
    const r = await call({ action: 'add_key', key },
      (x) => (x.added ? 'Chave cadastrada. Execute o comando acima neste computador; não será necessário informar uma senha.' : 'Esta chave já estava cadastrada.'));
    if (r) setKey('');
  };
  const removeKey = (fp) => call({ action: 'remove_key', fp }, 'Chave removida.');
  const off = () => call({ action: 'off' }, 'Acesso SSH por senha desativado; somente chaves serão aceitas.');
  const copy = () => { try { navigator.clipboard.writeText(cmd); setMsg('Comando de acesso copiado.'); } catch { /* Se não for possível copiar, transcreva o comando. */ } };
  const input = 'height:40px;padding:0 10px;border:1px solid var(--line);border-radius:8px';
  const small = 'font-size:13px;line-height:1.6;color:var(--text-2)';
  const blue = 'height:40px;padding:0 18px;border:0;border-radius:999px;background:var(--blue);color:#FFF;font-weight:600';
  const pwState = ssh == null ? null : ssh.password_login === true ? 'Acesso por senha ativado'
    : ssh.password_login === false ? 'Somente por chave (acesso por senha desativado)' : 'Não foi possível verificar o acesso por senha';
  return html`<div class="board ssh-settings" style="padding:16px 20px;display:flex;flex-direction:column;gap:10px">
    <div style="font-size:15px;font-weight:600">Acesso remoto SSH</div>
    <div style=${small}>
      Acesse o Microduck pelo terminal do computador para alterar programas, consultar registros e trocar arquivos sem regravar o cartão. Por padrão, somente chaves são aceitas; não há senha padrão.
      Escolha uma opção: defina uma senha SSH ou cadastre a chave pública do computador.</div>
    <div class="ssh-now" style="font-size:14px">Estado: ${ssh == null ? (loadErr || 'Carregando…')
      : html`<b>${pwState}</b>, ${keys.length ? `chaves cadastradas: ${keys.length}` : 'nenhuma chave cadastrada'}${ssh.ssh_active === false ? '; serviço SSH não está em execução' : ''}`}</div>
    ${on || keys.length ? html`<div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center">
      <code class="num ssh-cmd" style="padding:6px 10px;background:#F2F2F7;border-radius:8px">${cmd}</code>
      <button type="button" onClick=${copy} style="height:34px;padding:0 14px;border:0;border-radius:999px;background:#E5E5EA">Copiar</button></div>
      <div style=${small}>No Windows, abra o PowerShell; no Mac, abra o Terminal. Execute o comando acima. Na primeira conexão, confirme digitando yes.</div>` : null}
    ${!hasPassword ? html`<div class="ssh-need-web-pw" role="note" style="font-size:13px;color:var(--warn, #B25000)">
      Defina uma senha de acesso acima antes de ativar o SSH ou cadastrar chaves. Sem ela, qualquer pessoa conectada ao ponto de acesso poderia abrir esta página e ativar o SSH.</div>` : null}
    ${err ? html`<div role="alert" style="font-size:13px;color:var(--danger)">${err}</div>` : null}
    ${msg ? html`<div class="ssh-msg" style="font-size:13px;color:var(--text-2)">${msg}</div>` : null}

    <form class="ssh-pw" onSubmit=${submitPw} style="display:flex;flex-direction:column;gap:10px;padding-top:8px;border-top:1px solid var(--line)">
      <div style="font-size:14px;font-weight:600">Opção 1: acesso por senha</div>
      <div style=${small}>Use pelo menos 8 caracteres e não use “microduck”. Esta senha também será usada pelo comando sudo no Microduck.</div>
      ${hasPassword ? html`
      <label style="display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--text-2)">
        ${on ? 'Nova senha SSH' : 'Senha SSH'}
        <input type="password" name="ssh-password" autocomplete="new-password" value=${pw} minLength="8" maxLength="64"
          onInput=${(e) => setPw(e.target.value)} style=${input} /></label>
      <label style="display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--text-2)">
        Digite novamente
        <input type="password" name="ssh-confirm" autocomplete="new-password" value=${again} minLength="8" maxLength="64"
          onInput=${(e) => setAgain(e.target.value)} style=${input} /></label>` : null}
      <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center">
        <button type="submit" class="ssh-on" disabled=${busy || !hasPassword || ssh == null || !pw || !again} style=${blue}>
          ${busy ? 'Salvando…' : (on ? 'Alterar senha SSH' : 'Ativar acesso SSH por senha')}</button>
        ${on ? html`<${TwoStep} label="Desativar acesso SSH por senha" ask="Tem certeza de que deseja desativá-lo?" onConfirm=${off} />` : null}
      </div>
    </form>

    <form class="ssh-key" onSubmit=${submitKey} style="display:flex;flex-direction:column;gap:10px;padding-top:8px;border-top:1px solid var(--line)">
      <div style="font-size:14px;font-weight:600">Opção 2: cadastrar uma chave (mais seguro e sem senha)</div>
      <div style=${small}>
        Se ainda não tiver uma chave, no Windows execute no PowerShell <code>ssh-keygen -t ed25519</code> e pressione Enter em todas as perguntas;
        Depois execute <code>type $env:USERPROFILE\\.ssh\\id_ed25519.pub</code> (no Mac: <code>cat ~/.ssh/id_ed25519.pub</code>),
        e cole abaixo a linha gerada. <b>Cole somente o arquivo .pub</b>; o outro arquivo contém a chave privada e não deve ser compartilhado.</div>
      ${keys.length ? html`<ul class="ssh-keys" style="margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:6px">
        ${keys.map((k) => html`<li key=${k.fp} style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:13px">
          <span>${k.comment || '(sem comentário)'}</span><code class="num" style="color:var(--text-2)">${k.type} ${k.fp.slice(0, 19)}…</code>
          ${hasPassword ? html`<${TwoStep} label="Remover" ask="Tem certeza de que deseja remover esta chave?" onConfirm=${() => removeKey(k.fp)} />` : null}</li>`)}
      </ul>` : null}
      ${hasPassword ? html`<textarea name="ssh-key" rows="3" value=${key} onInput=${(e) => setKey(e.target.value)}
        placeholder="ssh-ed25519 AAAA… nome do computador" style="padding:8px 10px;border:1px solid var(--line);border-radius:8px;font:13px/1.5 ui-monospace,monospace;resize:vertical"></textarea>` : null}
      <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center">
        <button type="submit" class="ssh-addkey" disabled=${busy || !hasPassword || !key.trim()} style=${blue}>Cadastrar esta chave</button>
      </div>
    </form>
  </div>`;
}

function Settings({ st, tune }) {
  const [v, setV] = useState(loadStage());
  const pick = (x) => { setV(x); applyStage(x); try { localStorage.setItem('studio.stage', x); } catch { /* Modo privado. */ } };
  return html`<div style="display:flex;flex-direction:column;gap:16px;max-width:640px">
    <h1 style="margin:0;font-size:28px;font-weight:600">Configurações</h1>
    <${UpdateSettings} api=${api} csrf=${csrf} />
    <${AiSettings} api=${api} />
    <div class="board" style="padding:16px 20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center">
      <span style="font-size:15px;font-weight:600;flex:1">Registros e diagnóstico</span>
      <a class="settings-logs" href="#/logs" style="font-size:15px">Logs</a>
      <a class="settings-diag" href="/api/diag" style="font-size:15px" title="Inclui o número de série do Microduck e o IP da rede local">Exportar pacote de diagnóstico</a>
    </div>
    <${DuckAddresses} net=${st?.net} />
    <${WifiSettings} net=${st?.net} link=${link} />
    <${PasswordSettings} hasPassword=${st?.auth?.has_password} />
    <${SshSettings} hasPassword=${st?.auth?.has_password} />
    <${BatterySettings} link=${link} st=${st} />
    <${ModelSettings} tune=${tune} link=${link} />
    <div class="board" style="padding:16px 20px">
      <div style="font-size:15px;font-weight:600;margin-bottom:10px">Plano de fundo do palco</div>
      ${STAGES.map(([k, label]) => html`<label style="display:flex;align-items:center;gap:10px;height:40px">
        <input type="radio" name="stage" checked=${v === k} onChange=${() => pick(k)} /> ${label}</label>`)}
      <div style="font-size:13px;color:var(--text-2)">Afeta somente a exibição neste computador ou celular.</div>
    </div>
    <button onClick=${async () => { await api('/api/logout', {}); location.reload(); }}
      style="align-self:flex-start;height:40px;padding:0 18px;border:0;border-radius:999px;background:#E5E5EA">Sair</button>
  </div>`;
}

function Later({ what }) {
  return html`<div class="board" style="padding:24px"><h1 style="margin:0 0 8px;font-size:28px;font-weight:600">${what}</h1>
    <p style="margin:0;color:var(--text-2)">Esta página será implementada em uma etapa futura.</p></div>`;
}

// ---------------- Estrutura da página ----------------

// #/ e #/pad mostram a mesma página (visão geral); #/pad aponta para a área do controle. Destaque Controle quando essa área estiver visível; caso contrário, destaque Visão geral.
// Ao clicar novamente no endereço atual, não ocorre hashchange; onSame faz a rolagem.
const OVERVIEW = (r) => r === '/' || r === '/pad';
function navCur(route, padInView) {
  return (r) => {
    if (r === '/pad') return OVERVIEW(route) && padInView ? 'page' : undefined;
    if (r === '/') return OVERVIEW(route) && !padInView ? 'page' : undefined;
    return route === r ? 'page' : undefined;
  };
}

function Nav({ route, padInView, onSame }) {
  const cur = navCur(route, padInView);
  const a = (href, r, text) => html`<a href=${href} aria-current=${cur(r)} onClick=${(e) => onSame(e, href)}>${text}</a>`;
  return html`<nav class="nav" aria-label="Navegação">
    <div class="nav-logo"><svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect width="26" height="26" rx="7" fill="#1D1D1F"></rect><path d="M6 14.5a7 6 0 0 1 14 0z" fill="#FFFFFF"></path><rect x="6" y="14.5" width="14" height="2.6" rx="1.3" fill="#F5B400"></rect><circle cx="16.2" cy="11.4" r="1.3" fill="#1D1D1F"></circle></svg>Studio</div>
    ${a('#/', '/', 'Visão geral')}
    ${a('#/pad', '/pad', 'Controle')}
    ${a('#/camera', '/camera', 'Câmera')}
    ${a('#/tof', '/tof', 'ToF')}
    ${a('#/servos', '/servos', 'Servos')}
    ${a('#/imu', '/imu', 'IMU')}
    ${a('#/models', '/models', 'Modelos')}
    ${a('#/logs', '/logs', 'Logs')}
    <span class="spacer"></span>
    ${a('#/settings', '/settings', 'Configurações')}
  </nav>`;
}

// O gerenciamento de modelos também fica acessível pela barra inferior do celular, na mesma ordem da barra lateral.
function TabBar({ route, padInView, onSame }) {
  const cur = navCur(route, padInView);
  const a = (href, r, text) => html`<a href=${href} aria-current=${cur(r)} onClick=${(e) => onSame(e, href)}>${text}</a>`;
  return html`<nav class="tabbar" aria-label="Navegação principal">
    ${a('#/', '/', 'Visão geral')}${a('#/pad', '/pad', 'Controle')}${a('#/camera', '/camera', 'Câmera')}${a('#/tof', '/tof', 'ToF')}${a('#/servos', '/servos', 'Servos')}${a('#/imu', '/imu', 'IMU')}${a('#/models', '/models', 'Modelos')}${a('#/settings', '/settings', 'Mais')}
  </nav>`;
}

// Executa uma verificação antes de sair de uma página. Na página Servos, sair devolve o controle ao programa principal e libera todos os servos.
export const leaveGuards = {};
function useRoute() {
  const get = () => (location.hash.replace(/^#/, '') || '/');
  const [r, setR] = useState(get());
  const cur = useRef(r);
  useEffect(() => {
    const f = () => {
      const next = get();
      const guard = leaveGuards[cur.current];
      if (next !== cur.current && guard && !guard()) { history.replaceState(null, '', '#' + cur.current); return; }
      cur.current = next;
      // Atualiza imediatamente se a área do controle está ativa. Ao mudar de página, envia drive off sem esperar a renderização ou o IntersectionObserver.
      padActivity.setRoute(next);
      setR(next);
      link.heartbeat();                   // Informa a mudança de página ao Studio imediatamente, sem esperar o próximo sinal de vida.
    };
    window.addEventListener('hashchange', f);
    return () => window.removeEventListener('hashchange', f);
  }, []);
  return r;
}

// Ao navegar, #/pad rola até a área do controle, respeitando a barra fixa; as demais páginas voltam ao início.
function scrollFor(route) {
  if (route === '/pad') {
    const el = document.getElementById('pad-block');
    if (el) { el.scrollIntoView({ block: 'start' }); return; }
  }
  window.scrollTo(0, 0);
}

const PAD_HEAVY = ['skills', 'actions', 'combos', 'sounds'];

function Main({ duck }) {
  const route = useRoute();
  const [st, setSt] = useState(null);
  const [sv, setSv] = useState(null);
  const [imu, setImu] = useState(null);
  const [tune, setTune] = useState(null);
  const [pd, setPd] = useState(null);
  const [stAt, setStAt] = useState(0);
  const [status, setStatus] = useState(link.status);
  const [padInView, setPadInView] = useState(padActivity.inView);
  const [navTick, setNavTick] = useState(0);
  const firstScroll = useRef(route === '/pad');       // Em #/pad, rola novamente quando chegarem o primeiro state e os dados do controle, pois a altura superior ainda pode mudar.
  const now = useNow(250);
  const barRef = useStickyHeight('--bar-h');

  useEffect(() => {
    const off = link.on((m) => {
      if (m.t === '_status') setStatus(m.status);
      else if (m.t === 'state') {
        // Quando a lista inicial não muda, o backend omite os dados dos estados seguintes (onboarding_same); reutilize o valor anterior.
        setSt((prev) => (m.onboarding_same && prev ? { ...m, onboarding: prev.onboarding } : m));
        setStAt(performance.now());
      }
      else if (m.t === 'servo') setSv(m);
      else if (m.t === 'imu') setImu(m);
      else if (m.t === 'tune') setTune(m);
      else if (m.t === 'pad') {
        // Quando listas extensas (ações, combinações, habilidades e sons) não mudam, o backend deixa de enviá-las em cada estado; reutilize os valores anteriores.
        setPd((prev) => {
          if (!m.lists_same || !prev?.motion) return m;
          const keep = Object.fromEntries(PAD_HEAVY.filter((k) => k in prev.motion).map((k) => [k, prev.motion[k]]));
          return { ...m, motion: { ...m.motion, ...keep } };
        });
      }
    });
    const offAct = padActivity.subscribe(({ inView }) => setPadInView(inView));
    // Se o usuário interagir com roda, toque ou teclado, não mova a página quando os primeiros dados chegarem.
    const stop = () => { firstScroll.current = false; };
    window.addEventListener('wheel', stop, { passive: true, once: true });
    window.addEventListener('touchstart', stop, { passive: true, once: true });
    window.addEventListener('keydown', stop, { once: true });
    link.connect();
    return () => { off(); offAct(); };
  }, []);

  // Ao mudar de página ou clicar novamente no item atual (navTick), role até o destino correspondente.
  useEffect(() => { scrollFor(route); }, [route, navTick]);
  useEffect(() => {
    if (firstScroll.current && st && pd && route === '/pad') {
      firstScroll.current = false;
      requestAnimationFrame(() => scrollFor('/pad'));
    }
  }, [!!st, !!pd]);
  // Um segundo clique no endereço atual não dispara hashchange; faça a rolagem manualmente.
  const onSame = (e, href) => {
    if ((location.hash || '#/') === href) { e.preventDefault(); setNavTick((n) => n + 1); }
  };

  if (status === 'auth') { location.reload(); return null; }
  // O atraso combina o tempo desde o último estado recebido pelo navegador e desde a última leitura do robotd pelo Studio.
  const age = st ? (now - stAt) + (st.robotd_age_ms || 0) : Infinity;
  const live = status === 'open' && age < STALE_ALARM_MS && st?.robotd_ok !== false;
  // Mantenha a visão geral montada mesmo quando estiver oculta para não recriar o modelo 3D a cada navegação; o three.js conserva objetos internos e o navegador limita contextos WebGL simultâneos.
  // A área do controle também permanece montada dentro da visão geral. padActivity determina se ela está ativa, não o fato de continuar montada.
  const overview = html`<div hidden=${!OVERVIEW(route)}><${Overview} st=${st} live=${live} age=${age} duck=${duck} pd=${pd} onSame=${onSame} tune=${tune} sensorsActive=${OVERVIEW(route)} /></div>`;
  let page = null;
  if (OVERVIEW(route)) page = null;
  else if (route === '/logs') page = html`<${LogsPage} />`;
  else if (route === '/camera') page = html`<${CameraPage} api=${api} />`;
  else if (route === '/tof') page = html`<${TofPage} api=${api} />`;
  else if (route === '/servos') page = html`<${ServoPage} sv=${sv} link=${link} leaveGuards=${leaveGuards} />`;
  else if (route === '/settings') page = html`<${Settings} st=${st} tune=${tune} />`;
  else if (route === '/models') page = html`<${ModelsPage} api=${api} csrf=${csrf} link=${link} live=${live} />`;
  else if (route === '/imu') page = html`<${ImuPage} st=${st} imu=${imu} link=${link} live=${live} age=${age} pd=${pd} />`;
  else page = html`<${Later} what="Esta página" />`;

  document.title = `${duck?.label || 'Microduck'} · Microduck Studio`;
  return html`<div class="shell">
    <${Nav} route=${route} padInView=${padInView} onSame=${onSame} />
    <main class="main">
      <${TopBar} duck=${duck} st=${st} live=${live} age=${age} open=${status === 'open'}
        hideEStop=${route === '/servos' && sv?.state === 'open'} />
      <div class="sticky-bar" ref=${barRef}><${ServoBar} st=${st} onServos=${route === '/servos'} /></div>
      ${overview}${page}
    </main>
    <${TabBar} route=${route} padInView=${padInView} onSame=${onSame} />
  </div>`;
}

function Login({ onDone, duck, noPassword }) {
  const [pw, setPw] = useState('');
  const [remember, setRemember] = useState(true);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    let r;
    try { r = await api('/api/login', { password: pw, remember }); } catch { r = { error: 'Não foi possível conectar ao Microduck. Verifique a rede e tente novamente.' }; }
    setBusy(false);
    if (r.ok) onDone(); else setErr(r.error || 'Falha ao entrar');
  };
  return html`<form class="login board" onSubmit=${submit} autocomplete="on">
    <h1>${duck?.label || 'Microduck Studio'}</h1>
    <input type="text" name="username" autocomplete="username" value="admin" hidden readOnly />
    <label>Senha de administrador
      <input type="password" name="password" autocomplete="current-password" value=${pw} onInput=${(e) => setPw(e.target.value)} required autoFocus />
    </label>
    <label class="row"><input type="checkbox" checked=${remember} onChange=${(e) => setRemember(e.target.checked)} /> Manter conectado (30 dias)</label>
    ${noPassword ? html`<div class="err">A senha de administrador ainda não foi definida. No Microduck, execute: <code>python3 -I run.py set-password</code></div>` : null}
    ${err ? html`<div class="err" role="alert">${err}</div>` : null}
    <button type="submit" disabled=${busy || !pw}>Entrar</button>
  </form>`;
}

function App() {
  const [sess, setSess] = useState(undefined);
  const [noPw, setNoPw] = useState(false);
  const [down, setDown] = useState(false);
  const load = () => api('/api/session')
    .then((r) => { setDown(false); csrf = r.csrf || ''; setNoPw(r.has_password === false); setSess(r.status === 200 ? r : null); })
    .catch(() => { setDown(true); setTimeout(load, 2000); });   // Se o Studio estiver reiniciando, tente novamente em 2 s.
  useEffect(() => { applyStage(loadStage()); load(); }, []);
  if (sess === undefined) {
    return down ? html`<div class="login board"><h1>Microduck Studio</h1><p>Não foi possível conectar ao Studio do Microduck. Tentando novamente…</p></div>` : null;
  }
  if (!sess) return html`<${Login} onDone=${load} duck=${null} noPassword=${noPw} />`;
  return html`<${Main} duck=${sess.duck} />`;
}

render(html`<${App} />`, document.getElementById('app'));
