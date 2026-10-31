// Seção do controle integrado à visão geral (§1.2 do plano de reorganização): estado, pareamento (assistente visual), teste de parada de emergência,
// controle virtual (botões clicáveis) e controle remoto pela web. #/pad é a âncora desta seção na visão geral.
//
// Os dados vêm do backend studio/pad.py em {t:'pad', …} (10 Hz quando a seção está visível; 1 Hz nos demais casos).
// A página envia comandos por link.cmd('pad.op', {op, …}):
//   watch                       informa que a seção está visível; após 0,3 s, envia a cada 2 s; após 6 s sem sinal, o backend reduz a consulta do padd
//   refresh / scan / pair / cancel / forget / keys_done / wizard_reset   ações do assistente de pareamento
//   estop_test {action}         testa a parada de emergência: start / cancel
//   drive {open, seq}           entrou na seção (libera o estado “saiu”, sem tomar o controle); on:false sai; on:true assume o controle
//                               a seção está ativa quando a rota é / ou /pad, a página está visível e esta seção está na tela (padActivity)
//   sticks {mode,lx,ly,rx,ry,seq}  eixos dos dois analógicos virtuais, de -1 a 1; x aumenta para a direita e y para baixo; backend converte para robot.move / head / pose
//   stop {seq}                  ao soltar, envia zero, recentraliza cabeça ou corpo; o backend descarta quadros anteriores ao stop
//   mode {mode, seq}            modos drive / head / body, pelos botões Y / B do desenho
//   mode {mode, hb:true}        mantém o modo de cabeça/corpo ativo; o backend sai após 3 s sem sinal; não reativa um modo já encerrado
//   keys {held, down, seq}      botões LT / RT / X; envia ao pressionar/soltar e renova a cada 0,15 s enquanto pressionado
//   key {key, src:'svg'}        pressionamento dos botões A / X / LB / RB / direcional para baixo, conforme pad.bindings
//   start {expect, src:'svg'}   botão Start; o backend rejeita se o estado atual não corresponder ao esperado
//   reboot {src:'svg'}          direcional para a direita reinicia os servos; envia imediatamente, sem confirmação, após aliviar o corpo todo
//   drive_mode {expect, src:'svg'}  manter o direcional para cima por 3 s alterna caminhada e modo rodas
//   stand / walk / walk_stop / sit   levantar / caminhar / parar em pé / sentar; o backend valida a postura novamente
//   skill {name} / sound {tag}       habilidade oficial (robot.do) / som (robot.sound)
//   action_start / action_hold / action_stop  ações e sequências só continuam enquanto o botão estiver pressionado
//                                press é o identificador deste pressionamento; o backend só renova a ação correspondente (revisão C7)
// Select no desenho usa o mesmo link.cmd('relax') do botão superior e pode ser pressionado a qualquer momento (revisão V3).
// As funções dos botões seguem o padd do fork; os nomes acompanham as inscrições do controle.
// Controle virtual: a página envia quadros completos e cede espaço quando há um controle físico conectado.
import { html, useState, useEffect, useRef, useCallback } from './vendor/preact-htm.module.js';
import { Duck3D } from './duck3d.js';
import { InlineCamera } from './sensors.js';
import { MotionStudio } from './motion-studio.js';
import { AudioInteraction } from './audio-interaction.js';

const SEND_MS = 100;        // Envia 10 quadros/s enquanto o analógico está pressionado; ao soltar envia zero. Sem sinal por 0,5 s, o robô para (deadman do robotd).
const WATCH_MS = 2000;
const HOLD_MS = 150;        // Renova ações e botões pressionados a cada 0,15 s; o backend para após 0,45 s sem sinal
const MODE_HB_MS = 1000;    // Renova os modos de cabeça/corpo a cada segundo
const MODE_GRACE_MS = 800;  // Após Y / B, por este intervalo prevalece o modo da página, antes da atualização do backend
const DRIVE_HOLD_MS = 3000; // Manter o direcional para cima por 3 s alterna caminhada/rodas (padd:247–252; evita acionamento acidental)
const KEY_STALE_MS = 1000;  // O navegador repete eventos de tecla pressionada; sem evento por 1 s, considera solta
const BUSY_MS = 3000;       // Desativa os botões de levantar/caminhar/sentar até a postura mudar ou passarem 3 s
const DZ = 0.1;             // Zona morta dos analógicos; valores menores viram zero (padd:184–187)
const STICK_TRAVEL = 40;    // Distância arrastada no desenho (400 unidades de largura) para atingir o máximo
const WATCH_SETTLE_MS = 300;   // A seção precisa ficar visível por 0,3 s antes de ativar watch
const TAP_MS = 120;         // Toque sem movimento nem cancelamento por este tempo conta como pressionamento
const TAP_MOVE_PX = 8;      // A partir deste movimento, considera que o usuário está rolando a página
const SCROLL_GUARD_MS = 500;   // Ignora toques durante 0,5 s após a rolagem
const STICK_GRAB = 30;      // Raio inicial do analógico para toque; não alcança os botões ao redor
let SEQ = 0;
const nextSeq = () => ++SEQ;

// ---------------- Seção do controle ativa quando a rota é / ou /pad, a página está visível e a seção aparece na tela ----------------
// A seção continua montada dentro da visão geral, mesmo quando fica oculta. Por isso, a limpeza antes ligada à montagem/desmontagem
// agora depende de active: ao sair, solta todos os controles, envia drive {on:false} e heartbeat; ao voltar, envia drive {open}.
// app.js atualiza a rota sincronamente em hashchange, sem esperar o IntersectionObserver, que pode notificar a mudança com atraso.
const ACT = { route: location.hash.replace(/^#/, '') || '/', visible: document.visibilityState === 'visible',
  inView: false, active: false, subs: new Set(), link: null };
function actRecompute(why) {
  const a = (ACT.route === '/' || ACT.route === '/pad') && ACT.visible && ACT.inView;
  const changed = a !== ACT.active;
  ACT.active = a;
  for (const fn of ACT.subs) {
    try { fn({ active: a, inView: ACT.inView, changed }, why); } catch (e) { console.error('Falha em uma inscrição da seção de controle', e); }
  }
  if (changed && ACT.link) ACT.link.heartbeat();   // Informa o backend imediatamente: 10 Hz ↔ 1 Hz (o emissor de app.py verifica pad_visible)
}
export const padActivity = {
  get active() { return ACT.active; },
  get inView() { return ACT.inView; },
  bind(link) { ACT.link = link; },
  setRoute(route) { ACT.route = route || '/'; actRecompute(`Navegou para outra página (#${ACT.route})`); },
  setInView(v) { if (v !== ACT.inView) { ACT.inView = v; actRecompute('A seção de controle saiu da tela'); } },
  subscribe(fn) { ACT.subs.add(fn); return () => ACT.subs.delete(fn); },
};
document.addEventListener('visibilitychange', () => { ACT.visible = document.visibilityState === 'visible'; actRecompute('A página foi para o segundo plano'); });
window.__pad = padActivity;          // Depuração e testes e2e: indica se a seção de controle está ativa

// A ação “Ir” da lista inicial navega diretamente até o assistente, teste de emergência, controles pareados ou controle remoto.
const GO = new Set();
export function padGo(what) { for (const fn of GO) fn(what); }

// Proteção contra toques acidentais: a visão geral é rolável e contém controles que agem ao toque.
let lastScrollAt = -1e9;
window.addEventListener('scroll', () => { lastScrollAt = performance.now(); }, { passive: true, capture: true });
const scrolledRecently = () => performance.now() - lastScrollAt < SCROLL_GUARD_MS;
const isTouch = (e) => e.pointerType === 'touch' || e.pointerType === 'pen';
// No toque, só considera pressionado (press) se não houver movimento por TAP_MS nem cancelamento do navegador; soltar/cancelar libera (release).
// Se soltar antes de TAP_MS, conta como toque simples (tap); movimento ou cancelamento não faz nada, pois indica rolagem.
// Não chama preventDefault: o navegador pode rolar a página e emitir pointercancel. Retorna uma função para cancelar.
function touchHold(e, { press, release, tap }) {
  const pid = e.pointerId, x0 = e.clientX, y0 = e.clientY;
  let phase = 'pending';
  const off = () => {
    clearTimeout(timer);
    window.removeEventListener('pointermove', mv, true);
    window.removeEventListener('pointerup', up, true);
    window.removeEventListener('pointercancel', cc, true);
  };
  const mv = (ev) => {
    if (ev.pointerId !== pid || phase !== 'pending') return;
    if (Math.hypot(ev.clientX - x0, ev.clientY - y0) >= TAP_MOVE_PX) { phase = 'gone'; off(); }
  };
  const up = (ev) => {
    if (ev.pointerId !== pid) return;
    const was = phase; phase = 'gone'; off();
    if (was === 'pending' && tap) tap(); else if (was === 'held' && release) release();
  };
  const cc = (ev) => {
    if (ev.pointerId !== pid) return;
    const was = phase; phase = 'gone'; off();
    if (was === 'held' && release) release();
  };
  const timer = setTimeout(() => { if (phase !== 'pending') return; phase = 'held'; window.removeEventListener('pointermove', mv, true); press(); }, TAP_MS);
  window.addEventListener('pointermove', mv, true);
  window.addEventListener('pointerup', up, true);
  window.addEventListener('pointercancel', cc, true);
  return () => { if (phase === 'held' && release) release(); phase = 'gone'; off(); };
}

// ---------------- Modelos de controle: nomes dos botões, desenho e instruções de pareamento ----------------

const KINDS = {
  xbox: {
    label: 'Controle Xbox', layout: 'xbox',
    names: { south: 'A', east: 'B', west: 'X', north: 'Y', lb: 'LB', rb: 'RB', lt: 'LT', rt: 'RT', select: 'Exibir', start: 'Menu', home: 'Xbox', l3: 'Pressionar analógico esquerdo', r3: 'Pressionar analógico direito' },
    how: ['Pressione o botão Xbox rapidamente para ligar (não o mantenha pressionado: isso desliga o controle).', 'Pressione o pequeno botão de pareamento ao lado da porta USB-C até a luz do Xbox piscar rapidamente. A luz lenta indica que está ligado, mas não em pareamento.', 'O controle Xbox memoriza apenas um dispositivo. Se já foi pareado com computador ou celular e não pareia, remova-o primeiro daquele dispositivo.'],
  },
  ps: {
    label: 'Controle PS5 / PS4', layout: 'ps',
    names: { south: '×', east: '○', west: '□', north: '△', lb: 'L1', rb: 'R1', lt: 'L2', rt: 'R2', select: 'Create', start: 'Options', home: 'PS', l3: 'L3', r3: 'R3' },
    how: ['Mantenha Create e PS pressionados ao mesmo tempo até a faixa de luz piscar rapidamente.', 'O controle PlayStation ainda não foi testado oficialmente no robô. Depois de parear, pressione cada botão abaixo para conferir se está mapeado corretamente.'],
  },
  switch: {
    label: 'Tipo Switch Pro (inclui G50 Pro)', layout: 'switch',
    names: { south: 'B', east: 'A', west: 'Y', north: 'X', lb: 'L', rb: 'R', lt: 'ZL', rt: 'ZR', select: '−', start: '+', home: 'Home', l3: 'Pressionar analógico esquerdo', r3: 'Pressionar analógico direito' },
    how: ['No G50 Pro, coloque primeiro a chave traseira na posição S (modo Switch).', 'Mantenha pressionado o botão Sync ao lado da porta USB-C superior até as luzes começarem a piscar.'],
  },
  generic: {
    label: 'Outro controle', layout: 'xbox',
    names: { south: 'Baixo', east: 'Direita', west: 'Esquerda', north: 'Cima', lb: 'L1', rb: 'R1', lt: 'L2', rt: 'R2', select: 'Select', start: 'Start', home: 'Home', l3: 'L3', r3: 'R3' },
    how: ['Siga o manual para ativar o pareamento (em geral, a luz pisca rapidamente).', 'Se houver seletor de modo (Android / iOS / Switch / X-input), escolha Switch ou X-input. O modo Android costuma mapear os botões incorretamente.'],
  },
};
const kindOf = (k) => KINDS[k] || KINDS.generic;

// Funções dos botões conforme o padd do fork. role indica a posição: south é o botão inferior do grupo à direita.
// does descreve o controle físico; web indica diferenças no controle virtual; off explica por que um botão aparece desativado.
const ROLLER_NOTE = '(tem outra função no modo de rodas)';
const FUNCS = [
  { role: 'ls', group: 'main', name: () => 'Analógico esquerdo', does: 'Caminhada: avançar, recuar e deslocar para os lados · Cabeça: virar e inclinar a cabeça · Corpo: agachar e elevar',
    web: 'No controle virtual, arraste a partir do ponto pressionado; ao soltar, o analógico volta ao centro' },
  { role: 'rs', group: 'main', name: () => 'Analógico direito', does: 'Caminhada: virar · Cabeça: inclinar o pescoço e a cabeça · Corpo: inclinar para frente, trás e lados' },
  { role: 'start', group: 'main', does: 'Deitado/sentado: energiza e retorna à postura em pé; em pé: começa a caminhar; caminhando: para e volta a ficar em pé',
    web: 'No controle virtual, a ação depende da postura atual (descrita abaixo). Sentado, levanta suavemente; caminhando, para e retorna à postura em pé.' },
  { role: 'select', group: 'main', does: 'Toque curto ao soltar: desenergiza como parada de emergência; segure o robô e pressione Start para levantá-lo novamente', danger: 'Manter por 2 s: senta, desenergiza e desliga',
    web: 'No controle virtual, desenergiza ao pressionar, como o botão superior. Não desliga o robô.' },
  { role: 'dd', group: 'main', name: () => 'Direcional para baixo', does: 'Alterna entre sentar e levantar', bind: 'dpad_down', web: 'Sentado, levanta; em pé, senta' },
  { role: 'south', group: 'skill', does: 'Abaixar a cabeça para pegar um objeto (ground pick)', bind: 'a' },
  { role: 'west', group: 'skill', does: 'Cambalhota para frente; mantenha pressionado para repetir', bind: 'x' },
  { role: 'lb', group: 'skill', does: 'Chute com a perna esquerda', bind: 'lb' },
  { role: 'rb', group: 'skill', does: 'Chute com a perna direita', bind: 'rb' },
  { role: 'rt', group: 'skill', does: 'Abre o bico e grasna (pode usar em pé, sem caminhar)' },
  { role: 'lt', group: 'skill', does: 'Abre o bico; enquanto pressionado, emite “wheee” continuamente' },
  { role: 'north', group: 'mode', does: 'Modo cabeça: analógicos controlam a cabeça; pressione novamente para voltar à caminhada', imu: true },
  { role: 'east', group: 'mode', does: 'Modo corpo: analógicos inclinam e agacham o corpo; pressione novamente para voltar à caminhada' },
  { role: 'dr', group: 'other', name: () => 'Direcional para a direita', does: 'Reinicia todos os servos após uma proteção contra sobrecarga; primeiro desenergiza o corpo',
    web: 'No controle virtual, reinicia imediatamente, sem confirmação. O robô ficará solto; segure-o.' },
  { role: 'du', group: 'other', name: () => 'Direcional para cima', does: 'Manter por 3 s alterna caminhada e modo de rodas (se instaladas). Um sinal sonoro indica caminhada e dois, rodas; retorna à postura em pé antes de alternar',
    web: 'Também é preciso manter por 3 s; soltar antes cancela. O firmware rejeita se o modelo de rodas não estiver instalado.' },
  { role: 'dl', group: 'other', name: () => 'Direcional para a esquerda', does: 'Sem função ao caminhar; no modo de rodas, manter por 2 s alterna se A agacha ou vira', off: `Sem função ao caminhar ${ROLLER_NOTE}` },
  { role: 'home', group: 'other', does: 'Não tem função no robô; é o botão liga/desliga do controle', off: 'Sem função' },
  { role: 'l3', group: 'other', does: 'Sem função ao caminhar; no modo de rodas, testa como levantar após uma queda', off: `Sem função ao caminhar ${ROLLER_NOTE}` },
  { role: 'r3', group: 'other', does: 'Sem função', off: 'Sem função' },
];
const FUNC = Object.fromEntries(FUNCS.map((f) => [f.role, f]));
// Botões posicionais do desenho → identificadores do backend
const ROLE_BIND = { south: 'a', west: 'x', lb: 'lb', rb: 'rb', dd: 'dpad_down' };
const ROLE_HELD = { lt: 'lt', rt: 'rt', west: 'x' };
const MODE_CN = { drive: 'caminhada', head: 'modo cabeça', body: 'modo corpo' };
const DRIVE_CN = { walk: 'caminhada', roller: 'modo de rodas' };
const SKILL_CN = { ground_pick: 'pegar objeto', roulade: 'cambalhota', kick_left: 'chute esquerdo', kick_right: 'chute direito', sit_toggle: 'sentar ↔ levantar', roller_stand: 'levantar no modo de rodas' };
// Mapeamentos padrão oficiais (robotd-params lib.rs:175–215 e pad_drive.DEFAULT_BIND); prevalecem as alterações de robotd em pad.bindings.
const DEFAULT_BIND = { a: 'ground_pick', x: 'roulade', lb: 'kick_left', rb: 'kick_right', dpad_down: 'sit_toggle' };
const BIND_ROLE = { a: 'south', x: 'west', lb: 'lb', rb: 'rb', dpad_down: 'dd' };

const STEP_ICON = { ok: '✓', fail: '×', bad: '×', doing: '', todo: '', skip: '–', unk: '?' };
const fmtMs = (ms) => (ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const cx = (...xs) => xs.filter(Boolean).join(' ');

// ---------------- Desenho do controle ----------------

// Start e Select ficam separados para evitar acionamentos acidentais; as áreas clicáveis são maiores que os desenhos (pd-hit).
const LAYOUT = {
  xbox: { ls: [120, 100], dpad: [158, 152], face: [282, 100], rs: [243, 152], select: [172, 98], start: [228, 98], home: [200, 70] },
  switch: { ls: [120, 100], dpad: [158, 152], face: [282, 100], rs: [243, 152], select: [170, 82], start: [230, 82], home: [214, 112] },
  ps: { ls: [158, 156], dpad: [118, 100], face: [282, 100], rs: [242, 156], select: [150, 64], start: [250, 64], home: [200, 118], touch: true },
};
// Rótulos ao redor dos botões: [x, y, alinhamento]. Os três formatos têm posições próprias para evitar sobreposição.
// Em telas estreitas, o CSS oculta os demais rótulos e mantém Start e Select.
const NOTES = {
  xbox: { select: [170, 119], start: [236, 119], x: [253, 85], dr: [185, 137, 'start'], dd: [158, 190] },
  switch: { select: [170, 64], start: [230, 64], x: [256, 85], dr: [185, 137, 'start'], dd: [158, 190] },
  ps: { select: [135, 68, 'end'], start: [250, 52], x: [250, 85], dr: [147, 104, 'start'], dd: [104, 134] },
};
const HIT_W = 34, HIT_H = 28;      // Área clicável de Start / Select nas coordenadas do desenho
const BODY = 'M128 44C96 44 70 52 56 74C40 100 26 150 22 190C19 222 38 240 60 240C80 240 92 226 104 206C114 190 124 180 144 180L256 180C276 180 286 190 296 206C308 226 320 240 340 240C362 240 381 222 378 190C374 150 360 100 344 74C330 52 304 44 272 44C240 44 226 52 200 52C174 52 160 44 128 44Z';
// Dois botões em cada lado superior: LB / RB junto à borda e gatilhos LT / RT acima e mais para fora.
const SHOULDER = { l: { x: 80, w: 72 }, r: { x: 248, w: 72 } };            // y 26–50, parte inferior coberta pela carcaça
const TRIGGER = { l: { x: 62, w: 62 }, r: { x: 276, w: 62 } };             // y -10–18
const SH_Y = 26, SH_H = 24, TR_Y = -10, TR_H = 28;

// ctl é o controlador virtual fornecido por useVpad. Sem ele, o desenho é apenas ilustrativo.
// No modo espelhado, os botões exibidos vêm do controle físico; caso contrário, vêm dos botões virtuais pressionados.
function GamepadSvg({ kind, live, seen, ctl, keys }) {
  const k = kindOf(kind);
  const L = LAYOUT[k.layout] || LAYOUT.xbox;
  const b = live?.buttons || {};
  const ax = live?.axes || {};
  const on = (r) => !!b[r];
  const was = (r) => !!(seen && seen.includes(r));
  const N = NOTES[k.layout] || NOTES.xbox;
  // Para botões remapeáveis, usa a função enviada em motion.keys; se não houver, usa o mapeamento padrão.
  const does = (role) => {
    const row = keys?.[ROLE_BIND[role]];
    if (row && typeof row.does === 'string' && row.does) return row.does;
    const skill = DEFAULT_BIND[ROLE_BIND[role]];
    return SKILL_CN[skill] || skill || '';
  };
  const noteAt = (text, [x, y, anchor = 'middle'], extra) => html`<text class=${cx('pd-key-note', extra)} x=${x} y=${y} text-anchor=${anchor} aria-hidden="true">${text}</text>`;
  // Botões ativos recebem role e aria-label; ctl trata os eventos. Os desativados exibem o motivo no título.
  const act = (r) => {
    if (!ctl) return { info: null, props: {} };
    const info = ctl.info(r);
    const f = FUNC[r];
    const name = f?.name ? f.name() : k.names[r] || r;
    const say = `${name}：${info.ok ? info.does : info.why}`;
    return { info, say, props: {
      role: 'button', 'aria-label': say, 'aria-disabled': info.ok ? 'false' : 'true', 'data-role': r,
      onPointerDown: (e) => ctl.down(r, e), onPointerUp: (e) => ctl.up(r, e), onPointerCancel: (e) => ctl.up(r, e),
      onLostPointerCapture: (e) => ctl.up(r, e), onContextMenu: (e) => e.preventDefault(),
    } };
  };
  const tip = (a) => (a.info ? html`<title>${a.say}</title>` : null);
  // No modo espelhado, não deixa os botões cinza: o controle físico continua sendo exibido.
  const offc = (a) => a.info && !a.info.ok && !ctl.mirror && 'pd-key-off';
  const cls = (r, a, extra) => cx('pd-key', on(r) && 'pd-on', was(r) && 'pd-seen', r === 'select' && 'pd-estop',
    a.info && 'pd-press', offc(a), extra);
  const scale = (e) => (e.currentTarget.ownerSVGElement || e.currentTarget).getBoundingClientRect().width / 400;
  const stick = (r, [x0, y0], x, y, press) => {
    const t = 12;
    const a = act(r);
    const side = r === 'ls' ? 'l' : 'r';
    // Com mouse, qualquer ponto da base funciona. No toque, só vale a área transparente sobre o centro; tocar na base inicia a rolagem.
    const sp = ctl ? { role: 'button', 'aria-label': a.say, 'data-role': r, onContextMenu: (e) => e.preventDefault(),
      onPointerDown: (e) => ctl.stickDown(side, e, scale(e) * STICK_TRAVEL, false), onPointerMove: (e) => ctl.stickMove(side, e),
      onPointerUp: (e) => ctl.stickUp(side, e), onPointerCancel: (e) => ctl.stickUp(side, e),
      onLostPointerCapture: (e) => ctl.stickUp(side, e) } : {};
    return html`<g class=${cx('pd-stick', on(press) && 'pd-on', was(r) && 'pd-seen', a.info && 'pd-press', offc(a))} ...${sp}>
      <circle class="pd-stick-base" cx=${x0} cy=${y0} r="27"></circle>
      <circle class="pd-stick-cap" cx=${x0 + clamp(x || 0, -1, 1) * t} cy=${y0 + clamp(y || 0, -1, 1) * t} r="17"></circle>
      <text x=${x0} y=${y0 + 44} class="pd-cap">${r === 'ls' ? 'L' : 'R'}</text>
      ${ctl ? html`<circle class="pd-hit" cx=${x0} cy=${y0} r="34"></circle>` : null}${tip(a)}
    </g>`;
  };
  const face = ([x0, y0]) => [['north', 0, -23], ['south', 0, 23], ['west', -23, 0], ['east', 23, 0]].map(([r, dx, dy]) => {
    const a = act(r);
    return html`<g class=${cls(r, a)} ...${a.props}>
      <circle cx=${x0 + dx} cy=${y0 + dy} r="11.5"></circle>
      <text x=${x0 + dx} y=${y0 + dy + 4}>${k.names[r]}</text>${tip(a)}</g>`;
  });
  const dkey = (r, x, y, w, h) => {
    const a = act(r);
    return html`<g class=${cls(r, a)} ...${a.props}><rect x=${x} y=${y} width=${w} height=${h} rx="3"></rect>${tip(a)}</g>`;
  };
  const dpad = ([x0, y0]) => html`<g>
    ${dkey('du', x0 - 7, y0 - 25, 14, 18)}${dkey('dd', x0 - 7, y0 + 7, 14, 18)}
    ${dkey('dl', x0 - 25, y0 - 7, 18, 14)}${dkey('dr', x0 + 7, y0 - 7, 18, 14)}
    <rect class="pd-dpad-mid" x=${x0 - 7} y=${y0 - 7} width="14" height="14"></rect></g>`;
  // Os gatilhos preenchem de baixo para cima conforme a pressão; gatilhos digitais (Switch ZL / ZR) ficam totalmente preenchidos.
  const trig = (r, side) => {
    const { x, w } = TRIGGER[side];
    const v = clamp(ax[r] ?? (on(r) ? 1 : 0), 0, 1);
    const pressed = on(r) || v > 0.5;
    const a = act(r);
    // O rótulo permanece legível sobre o preenchimento parcial e fica branco quando o gatilho está totalmente pressionado.
    return html`<g class=${cx('pd-key', 'pd-trig', pressed && 'pd-on', was(r) && 'pd-seen', v > 0.95 && 'pd-trig-hi', a.info && 'pd-press', offc(a))} ...${a.props}>
      <rect x=${x} y=${TR_Y} width=${w} height=${TR_H} rx="9"></rect>
      ${v > 0.02 ? html`<rect class="pd-fill" x=${x} y=${TR_Y + TR_H * (1 - v)} width=${w} height=${TR_H * v} rx=${v > 0.3 ? 9 : 3}></rect>` : null}
      <text x=${x + w / 2} y=${TR_Y + 18}>${k.names[r]}</text>${tip(a)}</g>`;
  };
  const shoulder = (r, side) => {
    const { x, w } = SHOULDER[side];
    const a = act(r);
    return html`<g class=${cls(r, a, 'pd-shoulder')} ...${a.props}>
      <rect x=${x} y=${SH_Y} width=${w} height=${SH_H} rx="10"></rect>
      <text x=${x + w / 2} y=${SH_Y + 12.5}>${k.names[r]}</text>${tip(a)}</g>`;
  };
  const small = (r, [x0, y0], text) => {
    const a = act(r);
    return html`<g class=${cls(r, a)} ...${a.props}><rect x=${x0 - 13} y=${y0 - 7} width="26" height="14" rx="7"></rect>
      <text x=${x0} y=${y0 + 3.5} class="pd-small">${text}</text>
      ${ctl ? html`<rect class="pd-hit" x=${x0 - HIT_W / 2} y=${y0 - HIT_H / 2} width=${HIT_W} height=${HIT_H} rx="8"></rect>` : null}${tip(a)}</g>`;
  };
  const home = () => {
    const a = act('home');
    return html`<g class=${cls('home', a)} ...${a.props}><circle cx=${L.home[0]} cy=${L.home[1]} r="10"></circle>${tip(a)}</g>`;
  };
  const mode = ctl?.mode && ctl.mode !== 'drive' ? MODE_CN[ctl.mode] : null;
  // Áreas HTML transparentes sobre o desenho: no celular, a figura permite rolagem vertical; os centros dos analógicos e Select não rolam.
  // Essas áreas recebem toque porque o suporte a touch-action em elementos SVG varia entre navegadores.
  // As posições são convertidas de viewBox 0 -16 400 266 para percentuais; também funcionam com mouse.
  const pct = (x, y, w, h) => ({ left: `${(x / 400) * 100}%`, top: `${((y + 16) / 266) * 100}%`, width: `${(w / 400) * 100}%`, height: `${(h / 266) * 100}%` });
  const travel = (e) => (e.currentTarget.parentElement.getBoundingClientRect().width / 400) * STICK_TRAVEL;
  const ovStick = (r, [x0, y0]) => {
    const side = r === 'ls' ? 'l' : 'r';
    return html`<span class="pd-ov pd-ov-stick" data-ov=${r} aria-hidden="true" style=${pct(x0 - STICK_GRAB, y0 - STICK_GRAB, STICK_GRAB * 2, STICK_GRAB * 2)}
      onContextMenu=${(e) => e.preventDefault()}
      onPointerDown=${(e) => ctl.stickDown(side, e, travel(e), true)} onPointerMove=${(e) => ctl.stickMove(side, e)}
      onPointerUp=${(e) => ctl.stickUp(side, e)} onPointerCancel=${(e) => ctl.stickUp(side, e)}
      onLostPointerCapture=${(e) => ctl.stickUp(side, e)}></span>`;
  };
  const [sx, sy] = L.select;
  return html`<div class="pd-svgbox">
    <svg class=${cx('pd-svg', ctl && 'pd-svg-live')} viewBox="0 -16 400 266" role=${ctl ? 'group' : 'img'}
    aria-label=${ctl ? `${k.label}: botões clicáveis, como no controle físico` : `Ilustração de ${k.label}; os botões pressionados ficam escuros`} onContextMenu=${ctl ? (e) => e.preventDefault() : undefined}>
    ${trig('lt', 'l')}${trig('rt', 'r')}
    ${shoulder('lb', 'l')}${shoulder('rb', 'r')}
    <path class="pd-body" d=${BODY}></path>
    ${L.touch ? html`<rect class="pd-touch" x="168" y="54" width="64" height="40" rx="8"></rect>` : null}
    ${mode ? html`<g class="pd-modetag"><rect x="164" y="22" width="72" height="20" rx="10"></rect><text x="200" y="36">${mode}</text></g>` : null}
    ${stick('ls', L.ls, ax.lx, ax.ly, 'l3')}
    ${stick('rs', L.rs, ax.rx, ax.ry, 'r3')}
    ${dpad(L.dpad)}
    ${face(L.face)}
    ${small('select', L.select, k.names.select.length > 2 ? '' : k.names.select)}
    ${small('start', L.start, k.names.start.length > 2 ? '' : k.names.start)}
    ${home()}
    ${noteAt('Abrir o bico', [56, 7, 'end'])}
    ${noteAt('Abrir o bico · grasnar', [344, 7, 'start'])}
    ${noteAt(does('lb'), [74, 41, 'end'])}
    ${noteAt(does('rb'), [326, 41, 'start'])}
    ${noteAt('Modo cabeça', [282, 60])}
    ${noteAt('Modo corpo', [321, 104, 'start'])}
    ${noteAt(does('south'), [321, 129, 'start'])}
    ${noteAt(does('west'), N.x)}
    ${noteAt('Levantar / iniciar', N.start, 'pd-key-note-main')}
    ${noteAt('Desenergizar (emergência)', N.select, 'pd-key-note-main pd-note-danger')}
    ${noteAt('Reiniciar servos', N.dr)}
    ${noteAt(does('dd'), N.dd)}
    </svg>
    ${ctl ? html`${ovStick('ls', L.ls)}${ovStick('rs', L.rs)}
      <span class="pd-ov pd-ov-select" data-ov="select" aria-hidden="true" style=${pct(sx - HIT_W / 2, sy - HIT_H / 2, HIT_W, HIT_H)}
        onContextMenu=${(e) => e.preventDefault()} onPointerDown=${(e) => ctl.down('select', e)}
        onPointerUp=${(e) => ctl.up('select', e)} onPointerCancel=${(e) => ctl.up('select', e)}></span>` : null}
  </div>`;
}

// ---------------- Guia dos botões, conforme as inscrições do controle ----------------

function KeyName({ f, k }) {
  const n = f.name ? f.name() : k.names[f.role];
  return html`<span class="pd-chip">${n}</span>`;
}

function Legend({ kind, live, bindings, imuHead }) {
  const k = kindOf(kind);
  const b = live?.buttons || {};
  const ax = live?.axes || {};
  const moved = (r) => (r === 'ls' ? Math.hypot(ax.lx || 0, ax.ly || 0) > 0.25 : r === 'rs' ? Math.hypot(ax.rx || 0, ax.ry || 0) > 0.25
    : r === 'lt' || r === 'rt' ? (ax[r] || 0) > 0.3 : false);
  const bound = (f) => {
    const x = f.bind && (bindings || []).find((y) => y.button === f.bind);
    if (!x || !x.overridden) return null;
    return x.skill ? `Alterado para: ${SKILL_CN[x.skill] || x.skill}${x.error ? ` (${x.error})` : ''}` : 'Este botão foi desativado';
  };
  // Com [pad_imu_head_control] no robotd.toml e um controle com giroscópio, Y faz a cabeça acompanhar a orientação do controle físico.
  // O navegador não recebe a orientação do controle: no controle virtual, Y sempre ativa o modo de cabeça pelos analógicos.
  const does = (f) => {
    if (f.imu && imuHead) return 'Controle físico: a cabeça acompanha sua orientação (requer giroscópio); os analógicos continuam controlando a caminhada. Pressione novamente para manter a cabeça nessa posição.';
    return bound(f) || f.does;
  };
  const web = (f) => (f.imu ? (imuHead ? 'Controle virtual: os analógicos controlam a cabeça (o navegador não recebe a orientação do controle físico)' : imuHead == null ? 'Controle virtual: os analógicos controlam a cabeça; não foi possível ler a configuração do giroscópio no controle físico' : null)
    : f.off ? `Controle virtual desativado (${f.off})` : f.web);
  const row = (f) => html`<div class=${cx('pd-row', (b[f.role] || moved(f.role)) && 'pd-on')}>
    <${KeyName} f=${f} k=${k} />
    <span class="pd-does">${does(f)}${f.danger ? html`<br /><b class="pd-danger">${f.danger}</b>` : null}
      ${web(f) ? html`<small class="pd-web">${web(f)}</small>` : null}</span>
  </div>`;
  const group = (g) => FUNCS.filter((f) => f.group === g).map(row);
  return html`<div class="pd-legend">
    <div class="pd-legend-h">Controles principais</div>${group('main')}
    <div class="pd-legend-h">Habilidades</div>${group('skill')}
    <div class="pd-legend-h">Alternar função dos analógicos</div>${group('mode')}
    <details class="pd-other"><summary>Outros botões</summary>${group('other')}</details>
    ${k.layout === 'switch' ? html`<p class="pd-note">Nos controles Switch, A e B ficam em posições opostas às do Xbox. A tabela usa a posição: o botão inferior do grupo à direita executa a função A; no controle está marcado ${k.names.south}. Ainda é preciso conferir no robô.</p>` : null}
    ${live?.device?.keys_unverified ? html`<p class="pd-note">As posições de X e Y do controle Xbox são estimadas e ainda não foram conferidas no robô. Se X acender Y na figura, avise-nos.</p>` : null}
    ${live?.other?.length ? html`<p class="pd-note">Botões pressionados que não aparecem na tabela: ${live.other.join(', ')}. O padd pode não reconhecê-los; provavelmente são extras deste controle.</p>` : null}
  </div>`;
}

// ---------------- Cabeçalho: modelo, conexão e estado da parada de emergência ----------------

function Summary({ pad }) {
  const s = pad?.status || {};
  const live = pad?.live || {};
  const act = s.active;
  const es = pad?.estop || {};
  const name = act ? act.name || 'Controle' : live.state === 'attached' ? live.device?.name || 'Controle' : null;
  const mark = es.state === 'ok' ? html`<span class="pd-ok">Ativa ✓</span>`
    : es.state === 'unknown' ? html`<span class="pd-unk">Não verificada ?</span>` : html`<span class="pd-bad">Inativa ×</span>`;
  if (!s.known && live.state !== 'attached') return html`<span class="pd-sum">${s.error ? 'Não foi possível ler o estado do controle' : 'Lendo o estado do controle…'}${' · Parada do controle'}${mark}</span>`;
  const tail = name ? ' · conectado' : (s.pads || []).length ? ` · ${(s.pads || []).length} pareado(s), nenhum conectado` : '';
  return html`<span class="pd-sum"><b>${name || 'Nenhum controle conectado'}</b>${tail}${' · Parada do controle'}${mark}</span>`;
}

function EStopChecks({ pad }) {
  const checks = pad?.estop?.checks || [];
  return html`<ul class="pd-checks">${checks.map((c) => {
    const s = c.ok === true ? 'ok' : c.ok === false ? 'bad' : 'unk';
    return html`<li class=${'pd-s-' + s}>
      <span class="pd-mark">${STEP_ICON[s]}</span>
      <span>${c.label}${c.why ? html`<small>${c.why}</small>` : null}</span></li>`;
  })}</ul>`;
}

// ---------------- Teste de emergência: confirma torque ativo ao pressionar e desligado após soltar ----------------

const TEST_STEPS = [
  ['torque', 'Segure o robô (ou apoie-o em uma bancada) e pressione Start no controle para deixá-lo em pé.'],
  ['press', 'Pressione Select rapidamente (não mantenha pressionado: após 2 s ele senta e desliga).'],
  ['readback', 'Aguarde o programa principal confirmar que o torque foi desligado.'],
];
const TEST_AT = { need_torque: 0, armed: 1, pressed: 1, released: 2 };              // Etapa atual
const FAIL_AT = { torque: 0, press: 1, early_off: 1, long: 1, pressed_off: 1, pressed_unknown: 1, readback: 2, relax: 2, studio: 2 };
function testStepState(t, i) {
  if (t.state === 'passed') return 'ok';
  if (t.state === 'failed') {
    const f = FAIL_AT[t.failed_at] ?? 2;
    return i < f ? 'ok' : i === f ? 'fail' : 'todo';
  }
  const at = TEST_AT[t.state];
  if (at === undefined) return 'todo';
  return i < at ? 'ok' : i === at ? 'doing' : 'todo';            // Enquanto Select estiver pressionado, a segunda etapa continua em andamento.
}

function EStopTest({ pad, op }) {
  const t = pad?.estop_test || { state: 'idle' };
  const ok = pad?.estop?.ok;
  const running = !['idle', 'passed', 'failed'].includes(t.state);
  return html`<section class="board pd-card" id="pd-estop" tabIndex="-1">
    <h3>A parada de emergência do controle funciona?</h3>
    <${EStopChecks} pad=${pad} />
    <div class="pd-test">
      ${t.state === 'idle' ? html`<p class="pd-small-p">As verificações acima apenas confirmam a comunicação. O teste só termina quando você pressiona Select e confirma que os servos realmente desenergizaram.</p>` : null}
      ${t.state !== 'idle' ? html`<ol class="pd-steps">${TEST_STEPS.map(([key, text], i) => {
        const s = testStepState(t, i);
        return html`<li class=${'pd-s-' + s}><span class="pd-mark">${STEP_ICON[s] || ''}</span><span>${text}
          ${key === 'press' && t.state === 'pressed' ? html`<small>Pressionado há ${t.held_s ?? 0} s… solte</small>` : null}</span></li>`;
      })}</ol>` : null}
      ${t.why && running ? html`<p class="pd-small-p">${t.why}</p>` : null}
      ${t.held_long && running ? html`<div class="banner warn" role="status"><b>Select ficou pressionado por muito tempo. Solte agora.</b><span class="more">Após 2 s, o robô senta e desliga; esta tentativa não contará.</span></div>` : null}
      ${t.state === 'passed' ? html`<div class="pd-result pd-good">✓ Teste aprovado: ${fmtMs(t.ms)} entre soltar Select e confirmar a desenergização.<br />Pressione Start para deixá-lo em pé novamente.</div>` : null}
      ${t.state === 'failed' ? html`<div class="pd-result pd-fail"><b>× Teste reprovado: ${t.why || 'motivo desconhecido'}</b>${t.fix ? html`<br />${t.fix}` : null}</div>` : null}
      <div class="pd-btns">
        ${running
          ? html`<button class="btn-light" onClick=${() => op({ op: 'estop_test', action: 'cancel' })}>Cancelar teste</button>`
          : html`<button class="btn-dark" id="pd-estop-btn" disabled=${!ok} title=${ok ? '' : 'Todas as verificações acima precisam estar aprovadas'} onClick=${() => op({ op: 'estop_test', action: 'start' })}>${t.state === 'idle' ? 'Testar parada de emergência' : 'Testar novamente'}</button>`}
      </div>
    </div>
  </section>`;
}

// ---------------- Assistente de pareamento ----------------

function bars(rssi) {
  if (typeof rssi !== 'number') return html`<span class="pd-bars" title="O sinal não apareceu nesta busca (o dispositivo já foi pareado e está salvo no robô)">—</span>`;
  const n = rssi >= -60 ? 3 : rssi >= -75 ? 2 : 1;
  return html`<span class="pd-bars" title=${`Sinal: ${rssi} dBm`}>${[1, 2, 3].map((i) => html`<i class=${i <= n ? 'pd-on' : ''} style=${{ height: `${4 + i * 3}px` }}></i>`)}</span>`;
}

function DeviceList({ devices, picked, busy, op }) {
  const [showAll, setShowAll] = useState(false);
  const pads = devices.filter((d) => d.pad);
  const others = devices.filter((d) => !d.pad);
  const row = (d) => html`<div class=${cx('pd-dev', picked === d.mac && 'pd-sel')} key=${d.mac}>
    ${bars(d.rssi)}
    <span class="pd-dev-name"><b>${d.name || '(nome ainda indisponível)'}</b><small class="num">${d.mac}${d.kind_label ? ` · ${d.kind_label}` : ''}</small></span>
    <span class="pd-tags">
      ${d.pad ? html`<span class="pd-tag">Controle</span>` : html`<span class="pd-tag pd-gray">${d.why_not || 'Não parece ser um controle'}</span>`}
      ${d.paired ? html`<span class="pd-tag pd-gray">Pareado</span>` : null}
      ${d.connected ? html`<span class="pd-tag pd-gray">Conectado</span>` : null}
    </span>
    <button class=${d.pad ? 'btn-dark' : 'btn-light'} disabled=${busy} title=${busy ? 'A busca ainda está em andamento; aguarde para selecionar' : ''} onClick=${() => op({ op: 'pair', mac: d.mac }, 180000)}>Parear este</button>
  </div>`;
  return html`<div class="pd-devs">
    ${pads.length ? pads.map(row) : html`<div class="pd-empty">Nenhum controle encontrado. A luz do controle está piscando rapidamente?</div>`}
    ${others.length ? html`<button class="pd-link" onClick=${() => setShowAll(!showAll)}>${showAll ? 'Recolher' : `${others.length} outros dispositivos Bluetooth`}</button>` : null}
    ${showAll ? others.map(row) : null}
  </div>`;
}

function Wizard({ w, op, kind, setKind, onClose }) {
  const st = w?.state || 'idle';
  const busy = st === 'running';
  const k = kindOf(kind);
  const steps = w?.steps || [];
  const err = w?.error;
  const cfgBusy = w?.configd_busy_s;
  return html`<section class="board pd-card pd-wizard" id="pd-wizard" tabIndex="-1">
    <div class="pd-card-h"><h3>Parear um controle</h3>
      ${!busy ? html`<button class="pd-link" onClick=${onClose}>Fechar</button>` : null}</div>
    ${cfgBusy ? html`<div class="banner warn" role="status"><b>O pareamento anterior do configd ainda não terminou</b><span class="more">Não é possível interrompê-lo. Aguarde cerca de ${cfgBusy} s antes de parear outro controle.</span></div>` : null}
    ${st === 'idle' ? html`
      <div class="pd-kinds" role="radiogroup" aria-label="Tipo de controle">
        ${Object.entries(KINDS).map(([key, x]) => html`<button role="radio" aria-checked=${kind === key} class=${kind === key ? 'pd-on' : ''} onClick=${() => setKind(key)}>${x.label}</button>`)}
      </div>
      <ol class="pd-how">${k.how.map((s) => html`<li>${s}</li>`)}</ol>
      <div class="pd-btns">
        <button class="btn-dark" disabled=${!!cfgBusy} onClick=${() => op({ op: 'scan', seconds: 12 }, 30000)}>A luz está piscando; iniciar busca</button>
        <button class="btn-light" disabled=${!!cfgBusy} title="Usa robotctl pad pair oficial: seleciona automaticamente o dispositivo em modo de pareamento" onClick=${() => op({ op: 'pair' }, 180000)}>Parear diretamente (automático)</button>
      </div>
      <p class="pd-small-p">A busca leva cerca de 12 s. O Wi-Fi pode ficar lento durante a busca porque Bluetooth e Wi-Fi usam o mesmo chip. Não é possível buscar enquanto o robô caminha.</p>
      ${w.helper_available === false ? html`<p class="pd-small-p"><b>Assistente atualizado indisponível</b>: esta placa precisa parar o btd para parear; o Studio não consegue fazer isso e o pareamento pode falhar. Reinstale o assistente ou execute <code>sudo robotctl pad pair</code> no robô.</p>`
        : w.helper_available === true ? html`<p class="pd-small-p">O pareamento usa o assistente atualizado e o comando oficial <code>robotctl pad pair</code>, que pausa o btd e reinicia o Bluetooth.</p>`
        : html`<p class="pd-small-p">O assistente atualizado usa <code>robotctl pad pair</code> (pausa o btd e reinicia o Bluetooth). Sem ele, o pareamento pode falhar; reinstale-o ou execute <code>sudo robotctl pad pair</code> no robô.</p>`}
      ` : html`
      <ol class="pd-steps">${steps.map((s) => html`<li class=${'pd-s-' + s.state}>
        <span class="pd-mark">${STEP_ICON[s.state] || ''}</span>
        <span>${s.label}${s.note ? html`<small>${s.note}</small>` : null}</span></li>`)}</ol>
      ${w.phase === 'scan' || w.phase === 'pick' ? html`<${DeviceList} devices=${w.devices || []} picked=${w.picked} busy=${busy} op=${op} />` : null}
      ${err ? html`<div class="pd-err" role="alert">
        <b>${err.msg}</b>
        ${err.fix ? html`<div>Como corrigir: ${err.fix}</div>` : null}
        ${err.raw ? html`<details><summary>Texto original</summary><code>${err.raw}</code></details>` : null}
      </div>` : null}
      ${w.phase === 'keys' && st !== 'done' ? html`<p class="pd-small-p">Pressione cada botão e mova os dois analógicos em todas as direções. Os botões testados aparecem com contorno claro no desenho.</p>` : null}
      ${st === 'done' ? html`<div class="pd-result pd-good">✓ Pareamento concluído: ${w.result_name || 'controle'}. O controle reconectará após reiniciar o robô; basta ligá-lo.</div>` : null}
      <div class="pd-btns">
        ${busy ? html`<button class="btn-light" onClick=${() => op({ op: 'cancel' })}>Parar</button>` : null}
        ${w.phase === 'pick' && !busy ? html`<button class="btn-light" disabled=${!!cfgBusy} onClick=${() => op({ op: 'scan', seconds: 12 }, 30000)}>Buscar novamente</button>` : null}
        ${w.phase === 'keys' && st !== 'done' ? html`<button class="btn-dark" onClick=${() => op({ op: 'keys_done' })}>Botões conferidos; concluir</button>` : null}
        ${st === 'failed' ? html`<button class="btn-dark" disabled=${!!cfgBusy} onClick=${() => op(w.retry || { op: 'scan', seconds: 12 }, 180000)}>Tentar novamente</button>` : null}
        ${!busy ? html`<button class="btn-light" onClick=${() => op({ op: 'wizard_reset' })}>${st === 'done' ? 'Concluir' : 'Recomeçar'}</button>` : null}
      </div>
      ${w.via ? html`<p class="pd-small-p">Método de pareamento: ${w.via}${w.elapsed_s != null ? ` · ${w.elapsed_s.toFixed(0)} s` : ''}</p>` : null}`}
  </section>`;
}

// ---------------- Controles pareados ----------------

function KnownPads({ pad, op }) {
  const pads = pad?.status?.pads || [];
  if (!pads.length) return null;
  const forget = (p) => {
    const lines = [`Esquecer ${p.name || p.mac}?`, ''];
    if (p.connected) lines.push('Ele está conectado. Ao esquecê-lo, a conexão será encerrada e o robô parará imediatamente (o padd modificado também o fará sentar). Segure o robô antes de continuar.', '');
    lines.push('Isso remove o controle apenas do robô. O controle ainda memoriza o robô; para pareá-lo novamente, ative o modo de pareamento no controle.');
    if (window.confirm(lines.join('\n'))) op({ op: 'forget', mac: p.mac });
  };
  return html`<section class="board pd-card" id="pd-known" tabIndex="-1">
    <h3>Controles memorizados pelo robô</h3>
    ${pads.map((p) => html`<div class="pd-dev" key=${p.mac}>
      <span class=${cx('pd-dot', p.connected && 'pd-on')}></span>
      <span class="pd-dev-name"><b>${p.name || '(sem nome)'}</b><small class="num">${p.mac}</small></span>
      <span class="pd-tags">
        <span class="pd-tag pd-gray">${p.connected ? 'Conectado' : 'Desconectado'}</span>
        ${p.trusted ? null : html`<span class="pd-tag pd-warn" title="Funciona agora, mas não reconectará após reiniciar o robô">Não confiável</span>`}
      </span>
      ${p.trusted ? null : html`<button class="btn-light" onClick=${() => op({ op: 'pair', mac: p.mac }, 180000)}>Corrigir</button>`}
      <button class="btn-light" onClick=${() => forget(p)}>Esquecer</button>
    </div>`)}
    <p class="pd-small-p">Para reconectar um controle, basta ligá-lo; não é necessário parear novamente.</p>
  </section>`;
}

// ---------------- Controle virtual: desenho, dois analógicos e teclado compartilham o mesmo controlador ----------------

const TEXT_TYPES = ['text', 'password', 'search', 'email', 'number', 'tel', 'url'];
const typing = (el) => !!el && (el.isContentEditable || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT'
  || (el.tagName === 'INPUT' && TEXT_TYPES.includes((el.type || 'text').toLowerCase())));
// O teclado só controla a caminhada, não os modos cabeça/corpo. As setas não são usadas para que a rolagem da página não mova o robô.
const KEYMAP = { KeyW: ['ly', -1], KeyS: ['ly', 1], KeyA: ['lx', -1], KeyD: ['lx', 1], KeyQ: ['rx', -1], KeyE: ['rx', 1] };
const ZERO = { lx: 0, ly: 0, rx: 0, ry: 0 };
const dz = (v) => (Math.abs(v) < DZ ? 0 : v);
const MIRROR_WHY = 'Controle físico conectado: o desenho apenas o acompanha e ignora comandos virtuais (Select ainda desenergiza).';

// Leituras usam a mesma fórmula de pad_drive.sticks_to_intent; o backend continua sendo a referência.
function readout(mode, f, lim, head) {
  const LX = dz(f.lx), LY = -dz(f.ly), RX = dz(f.rx), RY = -dz(f.ry);
  if (mode === 'head') return [['Pescoço', RY * head, 'rad'], ['Inclinação vertical', -LY * head, 'rad'], ['Giro da cabeça', -LX * head, 'rad'], ['Inclinação lateral', RX * head, 'rad']];
  if (mode === 'body') {
    return [['Altura', LY * (LY >= 0 ? 1.0 : 2.5), 'cm'], ['Inclinação frente/trás', clamp(RY * 0.2618, -0.26, 0.26), 'rad'],
      ['Inclinação lateral', clamp(RX * 0.2618, -0.26, 0.26), 'rad']];
  }
  return [['Frente/trás', LY * lim.v, 'm/s'], ['Deslocamento lateral', -LX * lim.v, 'm/s'], ['Giro', -RX * lim.w, 'rad/s']];
}

// Estado do controle virtual: analógicos (separados por pointerId), teclado, gatilhos/botões mantidos e modo atual.
// O desenho, os analógicos e o teclado usam o mesmo controlador.
// - Analógicos relativos ao ponto inicial, zona morta de 0,1; envia a 10 Hz enquanto pressionado e um stop ao voltar ao centro.
// - Teclado só funciona com foco na área de controle e é liberado ao perder o foco.
// - Ao navegar, perder foco, ocultar a página, sair da seção, conectar um controle físico ou ceder o controle, libera tudo.
//   Ao sair envia drive {on:false}; ao retornar envia drive {open}.
// - Proteção contra toque acidental: só inicia perto do centro do analógico; ignora toque logo após rolagem; botões exigem 0,12 s sem movimento.
//   Exceção: Select desenergiza imediatamente.
// - O modo do backend prevalece; ao sair do modo, a página volta à caminhada e exige pressionar novamente os analógicos.
function useVpad({ pad, st, link }) {
  const v = pad?.virtual || {};
  const m = pad?.motion || {};
  const mirror = !!v.mirror;
  const d = v.driver;
  const locked = !!(d && !d.mine);
  const usable = !!pad?.motion && !mirror && !locked;
  const [axes, setAxes] = useState(ZERO);
  const [pressedView, setPressedView] = useState(() => new Set());
  const [heldView, setHeldView] = useState(() => new Set());
  const [mode, setModeView] = useState('drive');
  const [msg, setMsg] = useState(null);
  const [kbOn, setKbOn] = useState(false);
  const R = useRef(null);
  if (!R.current) {
    R.current = { sticks: { l: { pid: null, x: 0, y: 0 }, r: { pid: null, x: 0, y: 0 } }, kb: new Map(), held: new Set(),
      pressed: new Set(), mode: 'drive', modeAt: 0, lastNonZero: false, timer: null, keysTimer: null, alive: true };
  }
  const S = R.current;
  Object.assign(S, { usable, pad, st, mirror, locked, d });

  const say = (text, bad = true) => setMsg(text ? { text, bad, at: performance.now() } : null);
  const cmd = (args, t = 2000) => link.cmd('pad.op', args, t);
  const whyNot = () => (S.mirror ? MIRROR_WHY : S.locked ? `${S.d?.by || 'Outra página'} está no controle: aguarde soltar ou toque em “Assumir”`
    : 'Ainda não recebemos o estado do robô');
  const press = (role) => { S.pressed.add(role); setPressedView(new Set(S.pressed)); };
  const unpress = (role) => { if (S.pressed.delete(role)) setPressedView(new Set(S.pressed)); };

  // ---- Analógicos ----
  const frame = () => {
    const f = { lx: S.sticks.l.x, ly: S.sticks.l.y, rx: S.sticks.r.x, ry: S.sticks.r.y };
    if (S.mode === 'drive') for (const code of S.kb.keys()) { const [axis, val] = KEYMAP[code]; f[axis] = val; }
    return f;
  };
  const isZero = (f) => Math.max(Math.abs(f.lx), Math.abs(f.ly), Math.abs(f.rx), Math.abs(f.ry)) < DZ;
  const r3 = (x) => Math.round(x * 1000) / 1000 || 0;
  const send = async () => {
    const f = frame();
    if (isZero(f) || !S.usable) { kick(); return; }
    S.lastNonZero = true;
    const sentMode = S.mode;
    const r = await cmd({ op: 'sticks', mode: sentMode, lx: r3(f.lx), ly: r3(f.ly), rx: r3(f.rx), ry: r3(f.ry), seq: nextSeq() });
    if (!S.alive) return;
    if (!r.ok) { say(r.reason || r.error || 'Falha ao enviar'); return; }
    const dd = r.data || {};
    if (dd.dropped && dd.mode && dd.mode !== S.mode && sentMode === S.mode && performance.now() - S.modeAt > MODE_GRACE_MS) adopt(dd.mode, dd.dropped);
    else if (dd.dropped && S.mode !== 'drive') say(dd.dropped, false);
  };
  // Ao receber entrada, envia um quadro imediatamente e depois a cada 100 ms; ao voltar ao centro, envia stop.
  function kick() {
    const f = frame();
    setAxes(f);
    if (isZero(f) || !S.usable) {
      if (S.timer) { clearInterval(S.timer); S.timer = null; }
      if (S.lastNonZero) { S.lastNonZero = false; cmd({ op: 'stop', seq: nextSeq() }); }
      return;
    }
    if (!S.timer) { S.timer = setInterval(send, SEND_MS); send(); }
  }
  const voidSticks = () => {
    for (const side of ['l', 'r']) { const s = S.sticks[side]; if (s.pid != null) s.void = true; s.x = 0; s.y = 0; }
    S.kb.clear();
    kick();
  };
  const focusZone = (e) => {
    const z = e.currentTarget?.closest && e.currentTarget.closest('.pd-zone');
    if (z && document.activeElement !== z) z.focus({ preventScroll: true });
  };
  const stickDown = (side, e, k, center = true) => {
    if (e.button > 0) return;
    // No toque, só inicia perto do centro; toque na base normalmente significa rolagem. Não chama preventDefault para permitir rolar.
    if (isTouch(e) && (!center || scrolledRecently())) return;
    if (!ACT.active) return;                      // Ignora se a seção não estiver visível.
    e.preventDefault(); focusZone(e);
    if (!S.usable) { say(whyNot(), false); return; }
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* Alguns navegadores não oferecem este recurso. */ }
    S.sticks[side] = { pid: e.pointerId, ox: e.clientX, oy: e.clientY, k: Math.max(8, k), x: 0, y: 0, void: false };
  };
  const stickMove = (side, e) => {
    const s = S.sticks[side];
    if (s.pid !== e.pointerId || s.void) return;
    let x = (e.clientX - s.ox) / s.k, y = (e.clientY - s.oy) / s.k;
    const n = Math.hypot(x, y);
    if (n > 1) { x /= n; y /= n; }
    s.x = x; s.y = y;
    kick();
  };
  const stickUp = (side, e) => {
    if (S.sticks[side].pid !== e.pointerId) return;
    S.sticks[side] = { pid: null, x: 0, y: 0 };
    kick();
  };

  // ---- Botões mantidos: LT / RT / X (canal keys) ----
  const sendKeys = async (down = []) => {
    const r = await cmd({ op: 'keys', held: [...S.held], down, seq: nextSeq() });
    if (!S.alive) return;
    const drop = (k) => { S.held.delete(k); unpress(k === 'x' ? 'west' : k); };
    if (!r.ok) { down.forEach(drop); say(r.reason || r.error || 'Não foi possível pressionar'); }
    else if (r.data?.ended?.length) { r.data.ended.forEach(drop); say('O backend liberou os botões mantidos (desenergização, troca de controle ou desconexão). Solte e pressione novamente.', false); }
    setHeldView(new Set(S.held));
    if (!S.held.size && S.keysTimer) { clearInterval(S.keysTimer); S.keysTimer = null; }
  };
  const holdKey = (k) => {
    if (!ACT.active) return;
    S.held.add(k); setHeldView(new Set(S.held));
    sendKeys([k]);
    if (!S.keysTimer) S.keysTimer = setInterval(() => { if (S.held.size) sendKeys(); }, HOLD_MS);
  };
  const releaseKey = (k) => { if (!S.held.delete(k)) return; setHeldView(new Set(S.held)); sendKeys(); };

  // ---- Modos: Y / B ----
  function adopt(serverMode, why) {
    S.mode = serverMode; S.modeAt = performance.now(); setModeView(serverMode);
    voidSticks();
    if (why) say(why, false);
    // Confirma o retorno à caminhada para que o backend saiba que a página recebeu a mudança antes de aceitar outro modo.
    if (serverMode === 'drive') cmd({ op: 'mode', mode: 'drive', seq: nextSeq() });
  }
  const setMode = async (next, why) => {
    if (next === S.mode) return;
    S.mode = next; S.modeAt = performance.now(); setModeView(next);
    voidSticks();                                   // Ao trocar de modo, exige soltar e pressionar novamente os analógicos.
    const r = await cmd({ op: 'mode', mode: next, seq: nextSeq() });
    if (!S.alive) return;
    if (!r.ok) { say(r.reason || r.error || 'Não foi possível trocar de modo'); if (S.mode === next && next !== 'drive') adopt('drive'); return; }
    if (r.data?.dropped && r.data.mode && r.data.mode !== S.mode) { adopt(r.data.mode, r.data.dropped); return; }
    if (r.data?.note) say(r.data.note, false);
    else if (why) say(`Voltou à caminhada (${why})`, false);
  };
  // O heartbeat hb:true apenas renova o modo; não reativa um modo encerrado pelo backend.
  const beatMode = async () => {
    const r = await cmd({ op: 'mode', mode: S.mode, hb: true });
    if (S.alive && r.ok && r.data?.mode && r.data.mode !== S.mode && performance.now() - S.modeAt > MODE_GRACE_MS) adopt(r.data.mode, r.data.dropped);
  };

  // ---- Liberar tudo ----
  function releaseAll(why, keep) {
    if (S.touchOff) { const f = S.touchOff; S.touchOff = null; f(); }     // Cancela um toque que ainda não virou pressionamento.
    if (S.driveTimer) { clearTimeout(S.driveTimer); S.driveTimer = null; }  // Cancela a alternância antes de completar 3 s.
    S.kb.clear();
    for (const side of ['l', 'r']) { const s = S.sticks[side]; if (s.pid != null) s.void = true; s.x = 0; s.y = 0; }
    if (S.held.size) { S.held.clear(); setHeldView(new Set()); sendKeys(); }
    S.pressed.clear(); if (keep) S.pressed.add(keep); setPressedView(new Set(S.pressed));
    if (S.mode !== 'drive') setMode('drive', why);   // O backend também limpa os modos de cabeça/corpo.
    kick();
  }

  // ---- Pressionar / soltar os botões do desenho ----
  const estop = (fromCard) => {
    // Select no desenho desenergiza imediatamente, sem esperar soltar. O botão de desenergização do painel também passa por aqui.
    const p = link.cmd('relax', {}, 7000);
    if (fromCard === true) releaseAll('Desenergização acionada no painel remoto');
    else releaseAll('Select pressionado no desenho (desenergização)', 'select');
    p.then((r) => { if (S.alive) say(r.ok ? '✓ Desenergização enviada. O robô ficará solto; segure-o.' : (r.reason || r.error || 'Falha ao desenergizar; use o botão − do controle ou desligue a alimentação.'), !r.ok); });
  };
  const startKey = async () => {
    const s = S.pad?.motion?.start;
    if (!s) return;
    const tilt = S.st?.tilt_deg;
    if (s.op === 'stand' && typeof tilt === 'number' && tilt > 30
      && !window.confirm(`O robô está caído (inclinação de ${Math.round(tilt)}°). As pernas farão força repentinamente ao levantar. Você está segurando o robô?`)) { unpress('start'); return; }
    const r = await cmd({ op: 'start', expect: s.op, src: 'svg' }, 10000);
    if (S.alive) say(r.ok ? `✓ Start → ${s.label}${r.data?.reason ? `: ${r.data.reason}` : ''}` : (r.reason || r.error || 'Falha'), !r.ok);
  };
  // Direcional para a direita reinicia imediatamente; libera tudo antes, como Select.
  const rebootKey = async () => {
    releaseAll('Direcional para a direita pressionado (o programa principal desenergizará os servos)', 'dr');
    const r = await cmd({ op: 'reboot', src: 'svg' }, 7000);
    if (S.alive) say(r.ok ? '✓ Reinicialização dos servos enviada. O robô ficará solto; segure-o e pressione Start quando estiver pronto.' : (r.reason || r.error || 'Falha'), !r.ok);
  };
  // Direcional para cima: exige 3 s pressionado; soltar antes cancela a alternância.
  const driveHold = () => {
    const target = S.pad?.motion?.drive_mode?.target;
    clearTimeout(S.driveTimer);
    say(`Mantenha pressionado por 3 s para alternar para ${DRIVE_CN[target] || 'o outro modo'}…`, false);
    S.driveTimer = setTimeout(async () => {
      S.driveTimer = null;
      if (!S.pressed.has('du')) return;
      const r = await cmd({ op: 'drive_mode', expect: target, src: 'svg' }, 10000);
      if (!S.alive) return;
      if (!r.ok) { say(r.reason || r.error || 'Falha'); return; }
      say(r.data?.reason ? `✓ ${r.data.reason}` : `✓ Alternou para ${DRIVE_CN[target]}; o robô emitirá ${target === 'roller' ? 'dois' : 'um'} sinais e voltará à postura em pé.`, false);
    }, DRIVE_HOLD_MS);
  };
  const oneShot = async (role) => {
    const key = ROLE_BIND[role];
    const row = S.pad?.motion?.keys?.[key];
    const r = await cmd({ op: 'key', key, src: 'svg' }, 10000);
    if (!S.alive) return;
    if (!r.ok) { say(r.reason || r.error || 'Falha'); if (key === 'x') { releaseKey('x'); unpress('west'); } } else say(`✓ ${row ? row.does : key}`, false);
  };
  const info = (role) => {
    if (role === 'select') return { ok: true, does: 'Desenergização de emergência: pressione para soltar os servos; segure o robô' };
    const f = FUNC[role];
    if (f?.off) return { ok: false, why: f.off };
    const mm = S.pad?.motion || {};
    if (role === 'dr') {                          // Como Select, pode ser acionado por outra página em uma emergência.
      const x = mm.reboot;
      if (!x || S.mirror) return { ok: false, why: whyNot() };
      return x.ok ? { ok: true, does: x.does } : { ok: false, why: x.why };
    }
    if (role === 'start') {
      const s = mm.start;
      if (!s || S.mirror) return { ok: false, why: whyNot() };
      if (S.locked && s.op !== 'walk_stop') return { ok: false, why: whyNot() };   // Qualquer página pode parar e deixar o robô em pé.
      return s.ok ? { ok: true, does: `Ação atual: ${s.label}` } : { ok: false, why: s.why };
    }
    if (!S.usable) return { ok: false, why: whyNot() };
    if (role === 'du') {
      const x = mm.drive_mode;
      if (!x) return { ok: false, why: 'Ainda não recebemos o estado de caminhada ou modo de rodas.' };
      return x.ok ? { ok: true, does: x.does } : { ok: false, why: x.why };
    }
    if (role === 'north') return { ok: true, does: S.mode === 'head' ? 'Voltar à caminhada' : 'Modo cabeça: analógicos controlam a cabeça' };
    if (role === 'east') return { ok: true, does: S.mode === 'body' ? 'Voltar à caminhada' : 'Modo corpo: analógicos inclinam e agacham o corpo' };
    if (role === 'ls' || role === 'rs') {
      const t = { drive: ['Caminhada: frente/trás e deslocamento lateral', 'giro'], head: ['giro e inclinação vertical da cabeça', 'inclinação do pescoço e lateral da cabeça'], body: ['elevar e agachar', 'inclinar em todas as direções'] }[S.mode];
      return { ok: true, does: `Arraste: ${t[role === 'ls' ? 0 : 1]}` };
    }
    if (role === 'lt' || role === 'rt') {
      const t = mm.triggers || {};
      if (!t.ok) return { ok: false, why: t.why || 'Indisponível no momento' };
      return { ok: true, does: (role === 'lt' ? 'Mantenha: abrir o bico e emitir “wheee”' : 'Mantenha: abrir o bico; ao pressionar, grasnar') + (t.note ? ` (${t.note})` : '') };
    }
    const bk = ROLE_BIND[role];
    if (bk) {
      const row = mm.keys?.[bk];
      if (!row) return { ok: false, why: 'Ainda não recebemos a função deste botão.' };
      return row.ok ? { ok: true, does: row.does + (role === 'west' ? ' (mantenha pressionado para repetir)' : '') } : { ok: false, why: row.why };
    }
    return { ok: false, why: 'Sem função' };
  };
  const fire = (role) => {
    if (!ACT.active) return;                      // Ignora eventos fora da seção (Select usa outro caminho).
    const x = info(role);
    if (!x.ok) { say(x.why, false); return; }
    press(role);
    if (role === 'start') { startKey(); return; }
    if (role === 'dr') { rebootKey(); return; }
    if (role === 'du') { driveHold(); return; }
    if (role === 'north' || role === 'east') { const want = role === 'north' ? 'head' : 'body'; setMode(S.mode === want ? 'drive' : want); return; }
    if (ROLE_HELD[role]) holdKey(ROLE_HELD[role]);
    if (ROLE_BIND[role]) oneShot(role);
  };
  const down = (role, e) => {
    if (e.button > 0) return;
    if (role === 'select') {
      // Select desenergiza ao pressionar; sua área clicável não permite rolagem.
      e.preventDefault();
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* Alguns navegadores não oferecem este recurso. */ }
      estop(); return;
    }
    if (isTouch(e)) {
      // No toque, exige 0,12 s sem movimento; soltar antes conta como toque curto. Ignora logo após rolagem.
      if (scrolledRecently() || !ACT.active) return;
      if (S.touchOff) S.touchOff();
      S.touchOff = touchHold(e, { press: () => fire(role), release: () => up(role), tap: () => { fire(role); up(role); } });
      return;
    }
    e.preventDefault(); focusZone(e);
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* Alguns navegadores não oferecem este recurso. */ }
    fire(role);
  };
  const up = (role) => {
    if (!S.pressed.has(role)) return;
    unpress(role);
    if (ROLE_HELD[role]) releaseKey(ROLE_HELD[role]);
    if (role === 'du' && S.driveTimer) { clearTimeout(S.driveTimer); S.driveTimer = null; say('Não completou 3 s; modo não alterado.', false); }
  };

  // ---- Teclado: só funciona quando a área de controle está em foco ----
  const zoneProps = {
    tabIndex: 0,
    onKeyDown: (e) => {
      const km = KEYMAP[e.code];
      if (!km || typing(e.target) || e.ctrlKey || e.altKey || e.metaKey) return;
      // Se a área sair da tela durante a rolagem, ignora repetições de teclas pressionadas.
      if (!ACT.active) return;
      e.preventDefault();
      // Repetições do navegador só renovam teclas já pressionadas; após liberar tudo, exige uma nova pressão física.
      if (e.repeat && !S.kb.has(e.code)) return;
      if (S.mode !== 'drive') { say('O teclado não funciona nos modos cabeça/corpo. Use os analógicos.', false); return; }
      if (!S.usable) { say(whyNot(), false); return; }
      const had = S.kb.has(e.code);
      S.kb.set(e.code, performance.now());
      if (!had) kick();
    },
    onKeyUp: (e) => { if (S.kb.delete(e.code)) kick(); },
    onFocus: () => setKbOn(true),
    onBlur: (e) => {
      const to = e.relatedTarget;
      if (to && to.closest && to.closest('.pd-zone')) return;        // Alternar entre áreas de controle não conta como perda de foco.
      setKbOn(false);
      if (S.kb.size) { S.kb.clear(); kick(); }
    },
  };

  useEffect(() => {
    S.alive = true;
    // Ao entrar na seção, limpa o estado de saída sem assumir o controle; envia após conectar e confirma que continua visível.
    const open = () => link.whenOpen().then(() => { if (S.alive && ACT.active) cmd({ op: 'drive', open: true, seq: nextSeq() }, 3000); });
    // Ao sair da seção, libera tudo; o backend registra a saída e descarta quadros atrasados.
    const leave = (why) => {
      releaseAll(why);
      link.cmd('pad.op', { op: 'drive', on: false, seq: nextSeq(), why }, 3000);
    };
    const offAct = padActivity.subscribe(({ active, changed }, why) => {
      if (!changed) return;
      if (active) open(); else leave(why);
    });
    if (ACT.active) open();
    // Após reconectar, informa novamente que a seção permanece ativa.
    const offLink = link.on((m) => { if (m.t === '_status' && m.status === 'open' && ACT.active) open(); });
    const blur = () => releaseAll('Janela perdeu o foco');
    const vis = () => { if (document.visibilityState !== 'visible') releaseAll('Página em segundo plano'); };
    // Espaço aciona a desenergização superior; Esc libera todos os controles.
    const keyCap = (e) => { if (e.code === 'Space' || e.code === 'Escape') releaseAll(e.code === 'Space' ? 'Espaço pressionado (desenergização)' : 'Esc pressionado'); };
    // Se um evento de tecla solta se perder, considera a tecla liberada após 1 s sem repetição.
    const stale = setInterval(() => {
      const now = performance.now();
      let changed = false;
      for (const [c, at] of S.kb) if (now - at > KEY_STALE_MS) { S.kb.delete(c); changed = true; }
      if (changed) kick();
    }, 200);
    const beat = setInterval(() => { if (S.mode !== 'drive' && document.visibilityState === 'visible') beatMode(); }, MODE_HB_MS);
    window.addEventListener('blur', blur);
    document.addEventListener('visibilitychange', vis);
    window.addEventListener('keydown', keyCap, true);
    return () => {
      releaseAll('Seção de controle desmontada');
      S.alive = false;
      offAct(); offLink();
      clearInterval(stale); clearInterval(beat); clearInterval(S.timer); clearInterval(S.keysTimer);
      S.timer = S.keysTimer = null;
      window.removeEventListener('blur', blur);
      document.removeEventListener('visibilitychange', vis);
      window.removeEventListener('keydown', keyCap, true);
      link.cmd('pad.op', { op: 'drive', on: false, seq: nextSeq() }, 3000);   // Informa a saída; quadros atrasados são descartados.
    };
  }, []);
  // Libera tudo ao conectar um controle físico, outra página assumir ou o estado ficar indisponível.
  useEffect(() => { if (!usable) releaseAll(mirror ? 'Controle físico conectado' : locked ? 'Outra página assumiu o controle' : 'Estado indisponível'); }, [usable]);
  // O modo do backend prevalece; se ele encerrar o modo desta página, ela volta à caminhada.
  useEffect(() => {
    const sm = v.mode;
    if (!sm || sm === S.mode || performance.now() - S.modeAt < MODE_GRACE_MS) return;
    adopt(sm, v.mode_exit ? `${MODE_CN[S.mode]} encerrado: ${v.mode_exit.why}` : null);
  });
  useEffect(() => {
    if (!msg) return undefined;
    const t = setTimeout(() => setMsg(null), msg.bad ? 8000 : 4000);
    return () => clearTimeout(t);
  }, [msg]);

  const liveWeb = { buttons: Object.fromEntries([...pressedView].map((r) => [r, true])),
    axes: { ...axes, lt: heldView.has('lt') ? 1 : 0, rt: heldView.has('rt') ? 1 : 0 } };
  return { mode, axes, msg, kbOn, mirror, locked, usable, liveWeb, zoneProps, info, down, up, stickDown, stickMove, stickUp, say,
    estop: () => estop(true) };
}

// Botões de ação contínua: pressionar envia action_start; manter envia action_hold a cada 0,15 s; soltar, perder foco, ocultar a página ou sair da seção
// envia action_stop. No toque, exige 0,12 s sem movimento nem cancelamento do navegador; ignora toques logo após a rolagem:
// A primeira etapa de “chutes alternados” chama robot.do; iniciar o gesto aqui para rolar a página não pode acionar o movimento. Soltar antes de 0,12 s não faz nada.
function HoldButton({ item, link, onErr, lit, locked, quiet }) {
  const [held, setHeld] = useState(false);
  const timer = useRef(null);
  const alive = useRef(false);
  const pend = useRef(null);
  const seq = useRef(0);
  const stop = useCallback(() => {
    if (pend.current) { const f = pend.current; pend.current = null; f(); }
    if (!alive.current) return;
    alive.current = false; setHeld(false);
    clearInterval(timer.current); timer.current = null;
    link.cmd('pad.op', { op: 'action_stop' }, 3000);
  }, []);
  const down = (e) => {
    if (e.button > 0) return;
    if (isTouch(e)) {
      if (scrolledRecently() || !ACT.active || !item.ok || locked) return;
      if (pend.current) pend.current();
      pend.current = touchHold(e, { press: () => { pend.current = null; start(); }, release: stop });
      return;
    }
    start(e);
  };
  // Cada pressionamento recebe um identificador (press). Se soltar e pressionar novamente antes da resposta, ignora a resposta antiga para evitar temporizadores duplicados que continuariam enviando
  // action_hold depois de o botão ser solto; assim, a proteção do backend que para após 0,45 s sem renovação continua valendo. O backend também confere esse identificador.
  const start = async (e) => {
    if (e) { e.preventDefault(); try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* Alguns navegadores não oferecem este recurso. */ } }
    if (alive.current || !item.ok || locked || !ACT.active) return;
    const my = ++seq.current;
    alive.current = true; setHeld(true);
    const r = await link.cmd('pad.op', { op: 'action_start', id: item.id, press: my }, 4000);
    if (my !== seq.current) return;                       // Um novo pressionamento ocorreu antes da resposta; ignora este resultado.
    if (!r.ok) { onErr(r.reason || r.error || 'Ação não executada'); alive.current = false; setHeld(false); return; }
    if (!alive.current) { link.cmd('pad.op', { op: 'action_stop' }, 3000); return; }      // O botão foi solto antes da resposta.
    clearInterval(timer.current);
    const iv = setInterval(async () => {
      if (my !== seq.current || !alive.current) { clearInterval(iv); return; }
      const h = await link.cmd('pad.op', { op: 'action_hold', press: my }, 2000);
      if (my === seq.current && alive.current && h.ok && h.data && h.data.running === null) {
        alive.current = false; setHeld(false); clearInterval(iv);
      }
    }, HOLD_MS);
    timer.current = iv;
  };
  useEffect(() => {
    const vis = () => { if (document.visibilityState !== 'visible') stop(); };
    // Para imediatamente ao sair da seção ou navegar para outra página.
    const offAct = padActivity.subscribe(({ active, changed }) => { if (changed && !active) stop(); });
    window.addEventListener('blur', stop);
    document.addEventListener('visibilitychange', vis);
    return () => { offAct(); window.removeEventListener('blur', stop); document.removeEventListener('visibilitychange', vis); stop(); };
  }, []);
  return html`<button class=${cx('pd-act', 'pd-hold', held && 'pd-held', lit && 'pd-lit')} disabled=${!item.ok || locked}
    title=${item.ok ? `Mantenha pressionado; solte para parar: ${item.text}` : item.why}
    onPointerDown=${down} onPointerUp=${stop} onPointerCancel=${stop} onLostPointerCapture=${stop}
    onKeyDown=${(e) => { if (e.key === 'Enter' && !e.repeat) start(); }} onKeyUp=${(e) => { if (e.key === 'Enter') stop(); }}
    onContextMenu=${(e) => e.preventDefault()}>
    <b>${item.name}</b><small>${item.ok || quiet ? item.text : item.why}</small></button>`;
}

// Exibe a ação atual de Start, a função dos analógicos, o resultado recente e as instruções completas.
function VpadBar({ vp, pad }) {
  const m = pad?.motion || {};
  const v = pad?.virtual || {};
  const lim = v.limits || {};
  const s = m.start;
  if (vp.mirror) return html`<p class="pd-small-p pd-vbar">${MIRROR_WHY}。</p>`;
  return html`<div class="pd-vbar">
    <span>Ação de Start: <b>${s ? (s.ok ? s.label : 'indisponível') : '—'}</b>${s && !s.ok ? html`<small>（${s.why})</small>` : null}</span>
    <span>Analógicos: <b>${MODE_CN[vp.mode]}</b>${vp.mode !== 'drive' && pad?.motion && !m.driving ? html`<small> (a estratégia não está ativa; os analógicos não moverão o robô)</small>` : null}</span>
    <span class="pd-kbhint">${vp.kbOn ? 'Teclado conectado' : 'Clique no desenho para ativar o teclado'}</span>
    ${vp.msg ? html`<span class=${cx('pd-vmsg', vp.msg.bad && 'pd-bad-t')} role=${vp.msg.bad ? 'alert' : 'status'}>${vp.msg.text}</span>` : null}
  </div>
  <p class="pd-small-p pd-vbar-hint">Teclado: clique no desenho; W / S avançam e recuam, A / D deslocam para os lados, Q / E giram (o teclado não funciona nos modos cabeça/corpo); Espaço = desenergizar (emergência, funciona em toda a página) · Esc = liberar tudo (para, sem desenergizar). Velocidade máxima  ${(lim.v ?? 0.3).toFixed(2)} m/s, ${(lim.w ?? 1.5).toFixed(1)} rad/s (${lim.src || 'padrão oficial'}), limite da cabeça ${(v.inputs?.head ?? 2.5).toFixed(1)} rad (${v.inputs?.src || 'padrão oficial'}). Se o robô ainda não estiver pronto para caminhar, os analógicos não funcionam: toque em “Levantar” e depois “Caminhar” (ou pressione Start no desenho).</p>`;
}

function Remote({ st, pad, link, vp }) {
  const [err, setErr] = useState(null);
  const [busyUntil, setBusyUntil] = useState(0);
  const [busyPose, setBusyPose] = useState(null);
  const v = pad?.virtual || {};
  const m = pad?.motion || {};
  const live = pad?.live || {};
  const d = v.driver;
  const locked = !!(d && !d.mine);
  const mirror = !!v.mirror;
  const lb = live.buttons || {};
  const lax = live.axes || {};
  const binds = Object.fromEntries((pad?.bindings || []).map((b) => [b.button, b.skill]));
  const bindOf = (btn) => (btn in binds ? binds[btn] : DEFAULT_BIND[btn]);
  const physSkill = (name) => mirror && Object.entries(BIND_ROLE).some(([btn, role]) => bindOf(btn) === name && lb[role]);
  const now = performance.now();
  const busy = now < busyUntil && m.posture === busyPose;
  useEffect(() => { if (busyUntil) { const t = setTimeout(() => setBusyUntil(0), Math.max(0, busyUntil - performance.now())); return () => clearTimeout(t); } return undefined; }, [busyUntil]);

  const op = async (args, timeout = 8000) => {
    setErr(null);
    const r = await link.cmd('pad.op', args, timeout);
    if (!r.ok) setErr(r.reason || r.error || 'Falha');
    return r;
  };
  const takeOver = async () => {
    if (!window.confirm(`${d?.by || 'Outra página'} está no controle. Ao assumir, os analógicos e ações daquela página deixarão de funcionar. Deseja assumir?`)) return;
    await op({ op: 'drive', on: true, force: true, seq: nextSeq() });
  };

  const press = async (b) => {
    if (b.op === 'stand' && typeof st?.tilt_deg === 'number' && st.tilt_deg > 30
      && !window.confirm(`O robô está caído (inclinação de ${Math.round(st.tilt_deg)}°). As pernas farão força repentinamente ao levantar. Você está segurando o robô?`)) return;
    setBusyUntil(performance.now() + BUSY_MS); setBusyPose(m.posture);
    const r = await op({ op: b.op }, 10000);
    if (!r.ok) setBusyUntil(0);
  };
  const B = m.buttons || {};
  const mainBtn = (b, extra) => {
    if (!b) return null;
    const lit = mirror && ((b.op === 'stand' || b.op === 'walk' || b.op === 'walk_stop') ? lb.start : b.op === 'sit' ? (bindOf('dpad_down') === 'sit_toggle' && lb.dd) : false);
    // Qualquer página pode parar e deixar o robô em pé sem fila; os demais botões ficam desativados enquanto outra página controla ou há uma ação pendente.
    const off = !b.ok || (b.op !== 'walk_stop' && (locked || busy));
    return html`<button class=${cx('pd-big', extra, lit && 'pd-lit')} disabled=${off} onClick=${() => press(b)}
      title=${b.ok ? (b.call ? `Enviar ao programa principal: ${b.call}` : '') : b.why}>
      <b>${b.label}</b><small>${busy ? 'Aguardando resposta…' : b.ok ? (b.note || (b.op === 'walk_stop' ? 'Parar e ficar em pé (sem sentar)' : '')) : b.why}</small></button>`;
  };
  const last = m.last;
  const la = m.last_action;
  // Quando vários botões estão indisponíveis pelo mesmo motivo, exibe a explicação apenas uma vez.
  const common = (items) => {
    const xs = items || [];
    return xs.length && xs.every((x) => !x.ok && x.why === xs[0].why) ? xs[0].why : null;
  };
  const skWhy = common(m.skills), actWhy = common(m.actions), comboWhy = common(m.combos);
  const why = (text) => (text ? html`<p class="pd-small-p pd-why">${text}</p>` : null);
  return html`<section class="board pd-card pd-remote" id="pd-remote" tabIndex="-1">
    <div class="pd-card-h">
      <h3>Controle remoto</h3>
      <span class="pd-pose">Agora: <b>${m.posture_cn || '—'}</b></span>
      <span class="sv-spacer"></span>
      ${d ? html`<span class=${cx('pd-tag', !d.mine && 'pd-warn')}>${d.mine ? 'Esta página está no controle' : `${d.by || 'Outra página'} está no controle`}</span>` : null}
      ${locked ? html`<button class="btn-light" onClick=${takeOver}>Assumir controle</button>` : null}
      ${/* O botão fixo de desenergização também fica disponível aqui, ao alcance durante o uso dos analógicos; sempre pode ser acionado. */ ''}
      <button class="estop pd-relax" title="Desenergiza os 15 servos pelo mesmo comando do botão superior. Segure o robô, que ficará solto."
        onClick=${(e) => { e.currentTarget.blur(); vp.estop(); }}>Desenergizar</button>
    </div>
    <p class="pd-small-p pd-leave-note">Ao sair desta seção ou navegar para outra página, os analógicos e ações mantidos são liberados imediatamente.</p>
    ${err ? html`<div class="banner bad" role="alert"><b>${err}</b><a href="#" onClick=${(e) => { e.preventDefault(); setErr(null); }}>Entendi</a></div>` : null}
    ${locked ? html`<div class="banner warn" role="status"><b>${d.by || 'Outra página'} está controlando os analógicos ou executando uma ação</b><span class="more">Só uma página pode controlar por vez. Esta página será liberada 6 s depois que a outra soltar; para assumir antes, toque em “Assumir controle”. “Parar e ficar em pé” e Select (desenergizar) continuam disponíveis.</span></div>` : null}
    ${v.pad_unknown ? html`<div class="banner warn" role="status"><b>Não foi possível detectar se há um controle físico</b><span class="more">${v.pad_unknown} Se houver um controle conectado, ele terá prioridade sobre os analógicos virtuais.</span></div>` : null}
    ${mirror ? html`<div class="banner warn" role="status"><b>Controle físico conectado: o desenho acompanha os botões, mas não envia comandos</b><span class="more">Assim, os controles não disputam o comando. Levantar, caminhar, sentar, habilidades e sons continuam disponíveis; Select ainda desenergiza.</span></div>` : null}

    <div class="pd-sec">
      <div class="pd-sec-h">Levantar, caminhar e sentar</div>
      ${m.posture === 'servo_session' || st?.posture === 'servo_session' ? html`<p class="pd-small-p pd-why">Ajuste dos servos em andamento: o programa principal está pausado e os comandos de postura estão indisponíveis. Toque em “Devolver ao programa principal” para retomá-lo.</p>` : null}
      <div class="pd-bigs">${mainBtn(B.stand)}${mainBtn(B.walk, B.walk?.op === 'walk_stop' ? 'pd-stopbtn' : '')}${mainBtn(B.sit)}</div>
      ${last ? html`<p class=${cx('pd-small-p', !last.ok && 'pd-bad-t')}>${last.ok ? '✓' : '×'} ${last.what}${last.by ? `(${last.by})` : ''}：${last.ok ? (last.reason || 'Comando recebido pelo programa principal') : last.reason}</p>` : null}
    </div>

    <${AudioInteraction} pad=${pad} link=${link} activity=${padActivity} />
    <${MotionStudio} pad=${pad} link=${link} activity=${padActivity} />

    <div class="pd-sec">
      <div class="pd-sec-h">Habilidades<small>Toque para executar uma vez (ação oficial)</small></div>
      ${why(skWhy)}
      <div class="pd-acts">
        ${(m.skills || []).map((s) => html`<button class=${cx('pd-act', physSkill(s.name) && 'pd-lit')} disabled=${!s.ok || locked}
          title=${s.ok ? `robot.do ${s.name}` : s.why} onClick=${() => op({ op: 'skill', name: s.name })}>
          <b>${s.label}</b><small>${s.ok || skWhy ? '' : s.why}</small></button>`)}
        ${!(m.skills || []).length ? html`<p class="pd-small-p">${m.skills_why || 'Nenhuma habilidade configurada para este robô'}</p>` : null}
      </div>
      <div class="pd-sec-h">Sons</div>
      <div class="pd-acts pd-sounds">
        ${(m.sounds || []).map((s) => html`<button class=${cx('pd-act', 'pd-chipbtn', mirror && s.tag === 'chirp' && (lax.rt || 0) > 0.3 && 'pd-lit')} disabled=${!s.ok}
          title=${s.ok ? `robot.sound ${s.tag}` : s.why} onClick=${() => op({ op: 'sound', tag: s.tag })}>${s.label}</button>`)}
      </div>
      <div class="pd-sec-h">Ações<small>Mantenha pressionado; solte para parar</small></div>
      ${why(actWhy)}
      <div class="pd-acts">
        ${(m.actions || []).map((a) => html`<${HoldButton} key=${a.id} item=${a} link=${link} onErr=${setErr} locked=${locked} quiet=${!!actWhy}
          lit=${mirror && a.id === 'mouth' && Math.max(lax.lt || 0, lax.rt || 0) > 0.1} />`)}
      </div>
      <div class="pd-sec-h">Sequências<small>Executa várias ações em sequência enquanto pressionado; soltar, desenergizar ou tocar em Parar interrompe</small></div>
      ${comboWhy && comboWhy !== actWhy ? why(comboWhy) : null}
      <div class="pd-acts">
        ${(m.combos || []).map((a) => html`<${HoldButton} key=${a.id} item=${a} link=${link} onErr=${setErr} locked=${locked} quiet=${!!comboWhy} />`)}
      </div>
      ${m.running ? html`<p class="pd-small-p">Executando “${m.running.name}”: etapa ${m.running.step + 1} de ${m.running.steps}${m.running.by ? `(${m.running.by})` : ''}</p>`
        : la ? html`<p class=${cx('pd-small-p', !la.ok && 'pd-bad-t')}>“${la.name}”${la.result}</p>` : null}
      <p class="pd-small-p">Criação de sequências personalizadas será adicionada em uma próxima versão; as sequências ficam no diretório state do robô.</p>
    </div>
    <p class="pd-small-p">Segurança: o movimento só ocorre enquanto pressionado. Soltar, sair desta seção, navegar, perder foco ou colocar a página em segundo plano interrompe imediatamente (e recentraliza cabeça e corpo). Se a conexão cair, o robô para após 0,5 s sem comandos. Só uma página controla por vez. No celular, arrastar a partir de áreas vazias do desenho rola a página sem mover o robô.</p>
  </section>`;
}

// ---------------- Modelo 3D do robô na seção do controle ----------------
// Em telas largas, modelo 3D e câmera ficam em cartões empilhados à esquerda; em telas estreitas, aparecem acima do controle remoto.
// Como na visão geral: articulações em tempo real, escala fixa, um dedo rola a página e dois giram o modelo. Fora da tela, não renderiza.
// A geometria é armazenada em cache no módulo duck3d e não é carregada duas vezes. Dados antigos ficam esmaecidos por classe CSS.
// Linha inferior: postura, bateria e valores atuais de movimento, calculados como no painel remoto.
function PadDuck({ st, pad, vp, live }) {
  const canvasRef = useRef(null);
  const duckRef = useRef(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    const d = new Duck3D(canvasRef.current, { view: 'front34', centerX: 0.5, centerY: 0.5, fill: 0.86, pageScroll: true });
    duckRef.current = d;
    d.load('model/').catch((e) => setErr(`Falha ao carregar o modelo 3D: ${e.message}`));
    return () => d.dispose();
  }, []);
  useEffect(() => {
    if (!duckRef.current || !st) return;
    duckRef.current.setJoints(st.joints);
    duckRef.current.setGravity(st.gravity);
  }, [st]);
  const v = pad?.virtual || {};
  const ax = pad?.live?.axes || {};
  const mirror = vp.mirror;
  const f = mirror ? { lx: ax.lx || 0, ly: ax.ly || 0, rx: ax.rx || 0, ry: ax.ry || 0 } : vp.axes;
  const rows = readout(mirror ? 'drive' : vp.mode, f, v.limits || { v: 0.3, w: 1.5 }, v.inputs?.head ?? 2.5);
  const pct = st?.battery?.pct;
  const old = !live || st?.joints_age_ms == null || st.joints_age_ms > 1000;
  return html`<section class="board pd-card pd-3d" aria-label="Postura atual do robô">
    <div class="pd-3d-stage"><canvas ref=${canvasRef} class=${old ? 'stage-stale' : ''}></canvas>
      ${err ? html`<span class="sv-loading">${err}</span>` : null}</div>
    <p class="pd-small-p pd-3d-line num">${pad?.motion?.posture_cn || '—'} · Bateria ${typeof pct === 'number' ? `${Math.round(pct)}%` : '—'}
      ${rows.map(([n, val, u]) => ` · ${n} ${(Math.round(val * 100) / 100 || 0).toFixed(2)} ${u}`).join('')}${old ? ' · dados desatualizados' : ''}</p>
  </section>`;
}

// ---------------- Seção do controle na visão geral ----------------

const TOPBAR_PX = 56;       // Barra superior fixa (styles.css .topbar), descontada ao verificar se a seção está visível.
const TABBAR_PX = 83;       // Barra inferior em dispositivos móveis (styles.css .tabbar)

// Ordem da visão geral: cabeçalho, desenho do controle e painel remoto, assistente de pareamento, teste de emergência e controles pareados.
// Não há página separada para o controle; #/pad é uma âncora da visão geral.
// A seção permanece montada; padActivity define sua atividade com base na rota, visibilidade e posição na tela.
export function PadPage({ st, pad, link, api, previewActive = false, live: duckLive = true }) {
  const [msg, setMsg] = useState(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [kind, setKind] = useState('xbox');
  const [visualFits, setVisualFits] = useState(true);
  const rootRef = useRef(null);
  const s = pad?.status || {};
  const live = pad?.live || {};
  const w = pad?.wizard || { state: 'idle' };
  const showWizard = wizardOpen || w.state !== 'idle';
  // Prioriza o modelo detectado; sem controle conectado, usa o modelo escolhido no assistente (Xbox por padrão).
  const activeKind = live.device?.kind || s.active?.kind || kind;
  const vp = useVpad({ pad, st, link });
  // Exibe os botões físicos quando há espelhamento ou teste de pareamento; caso contrário, exibe os botões virtuais.
  const shown = vp.mirror || live.state === 'attached' ? live : vp.liveWeb;

  // Considera a altura real do cabeçalho; se não houver espaço, a página rola para manter a câmera acessível.
  useEffect(() => {
    const left = rootRef.current?.querySelector('.pd-left');
    if (!left) return;
    let frame = null;
    const measure = () => {
      frame = null;
      const height = left.getBoundingClientRect().height;
      const top = parseFloat(getComputedStyle(left).top);
      if (height > 0 && Number.isFinite(top)) setVisualFits(height + top + 16 <= innerHeight);
    };
    const schedule = () => { if (frame == null) frame = requestAnimationFrame(measure); };
    const observer = new ResizeObserver(schedule);
    for (const el of [left, document.querySelector('.band'), document.querySelector('.sticky-bar')]) {
      if (el) observer.observe(el);
    }
    window.addEventListener('resize', schedule);
    schedule();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); window.removeEventListener('resize', schedule); };
  }, []);

  const op = useCallback(async (args, timeout = 15000) => {
    const r = await link.cmd('pad.op', args, timeout);
    if (!r.ok) setMsg(r.reason || r.error || 'Falha'); else setMsg(null);
    return r;
  }, []);

  // Verifica se a seção está na tela, descontando as barras fixa superior e inferior. Ao navegar, o observador pode notificar a saída com atraso:
  // app.js já atualiza a rota sincronamente no evento hashchange (padActivity.setRoute).
  // Considera o cabeçalho, desenho, painel remoto, pareamento e teste de emergência; o modelo 3D não conta como uso do controle.
  useEffect(() => {
    let io = null;
    const mq = window.matchMedia('(max-width: 700px)');
    const seen = new Map();
    const build = () => {
      if (io) io.disconnect();
      seen.clear();
      io = new IntersectionObserver((es) => {
        for (const e of es) seen.set(e.target, e.isIntersecting);
        padActivity.setInView([...seen.values()].some(Boolean));
      }, { rootMargin: `-${TOPBAR_PX}px 0px -${mq.matches ? TABBAR_PX : 0}px 0px`, threshold: 0 });
      const root = rootRef.current;
      if (root) for (const el of root.querySelectorAll(':scope > .pd-head, .pd-live, #pd-remote, :scope > .pd-more')) io.observe(el);
    };
    build();
    if (mq.addEventListener) mq.addEventListener('change', build);
    return () => {
      if (io) io.disconnect();
      if (mq.removeEventListener) mq.removeEventListener('change', build);
      padActivity.setInView(false);
    };
  }, []);

  // Informa ao backend que a seção está sendo usada; só então ele assina o canal padd e ativa o dispositivo, economizando recursos quando ocioso.
  // Exige 0,3 s de visibilidade contínua; após reconectar, envia novamente de imediato.
  useEffect(() => {
    let since = ACT.active ? performance.now() : null;
    let t0 = null;
    const tick = () => {
      if (ACT.active && since != null && performance.now() - since >= WATCH_SETTLE_MS) link.cmd('pad.op', { op: 'watch' }, 3000);
    };
    const arm = () => { clearTimeout(t0); t0 = setTimeout(tick, WATCH_SETTLE_MS + 20); };
    const offAct = padActivity.subscribe(({ active, changed }) => {
      if (!changed) return;
      if (active) { since = performance.now(); arm(); } else { since = null; clearTimeout(t0); }
    });
    if (since != null) arm();
    const iv = setInterval(tick, WATCH_MS);
    const offLink = link.on((m) => { if (m.t === '_status' && m.status === 'open') arm(); });
    return () => { offAct(); offLink(); clearInterval(iv); clearTimeout(t0); };
  }, []);

  // A ação “Ir” da lista inicial abre o assistente, leva ao teste de emergência ou rola até os controles pareados e o painel remoto.
  useEffect(() => {
    const fn = (what) => {
      if (what === 'wizard') setWizardOpen(true);
      // Aguarda o assistente ser renderizado antes de rolar.
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const el = document.getElementById({ wizard: 'pd-wizard', estop: 'pd-estop', known: 'pd-known', remote: 'pd-remote' }[what]);
        if (!el) return;
        el.scrollIntoView({ block: 'center' });
        const btn = what === 'estop' ? document.getElementById('pd-estop-btn') : null;
        try { (btn && !btn.disabled ? btn : el).focus({ preventScroll: true }); } catch { /* Navegadores antigos */ }
      }));
    };
    GO.add(fn);
    return () => GO.delete(fn);
  }, []);
  useEffect(() => { if (w.state === 'idle' && !wizardOpen) setMsg(null); }, [w.state]);

  const connected = !!s.active || live.state === 'attached';
  const tapTag = { attached: 'Ao vivo', waiting: 'Aguardando controle', absent: 'Botões indisponíveis', denied: 'Sem permissão para ler os botões', error: 'Falha ao ler os botões', connecting: 'Conectando', off: '' }[live.state] || '';
  return html`<section class="pd-page" id="pad-block" ref=${rootRef} aria-label="Controle">
    <header class="pd-head">
      <h2>Controle</h2>
      <${Summary} pad=${pad} />
      <span class="sv-spacer"></span>
      ${!showWizard ? html`<button class="btn-dark" onClick=${() => setWizardOpen(true)}>${connected ? 'Parear outro controle' : 'Parear controle'}</button>` : null}
    </header>
    ${msg ? html`<div class="banner bad" role="alert"><b>${msg}</b><a href="#" onClick=${(e) => { e.preventDefault(); setMsg(null); }}>Entendi</a></div>` : null}
    ${s.error && live.state !== 'attached' ? html`<div class="banner warn" role="status"><b>Não foi possível ler o estado do controle no configd</b><span class="more">${s.error}</span></div>` : null}
    ${s.netpad ? html`<div class="banner warn" role="status"><b>Controle UDP (netpad) ativo</b><span class="more">O padd recebe comandos apenas do controle UDP enviado pelo computador; controles Bluetooth e sua parada de emergência não funcionam. Para usar Bluetooth, desative [netpad] na configuração.</span></div>` : null}
    ${s.known && s.driver && s.driver !== 'active' ? html`<div class="banner bad" role="alert"><b>padd não está em execução (${s.driver})</b><span class="more">O controle não funcionará mesmo conectado. O padd só inicia quando o programa principal robotd está ativo.</span></div>` : null}
    ${st?.posture === 'servo_session' ? html`<div class="banner warn" role="status"><b>Ajustando os servos</b><span class="more">O programa principal está pausado; controle, movimento e postura estão indisponíveis. Os servos mantêm a posição ao sair desta página. Toque em “Devolver ao programa principal” para retomá-lo.</span></div>` : null}
    <div class="pd-main">
      <section class="board pd-card pd-live">
        <div class="pd-card-h"><h3>${live.device?.name || s.active?.name || `${kindOf(activeKind).label}${vp.mirror ? '' : '(controle virtual)'}`}</h3>
          <span class="pd-livetag">${tapTag}${live.last_ms != null && live.state === 'attached' ? ` · ${fmtMs(live.last_ms)} desde a última entrada` : ''}</span></div>
        <div class=${cx('pd-zone', 'pd-svgzone', vp.kbOn && 'pd-kb')} ...${vp.zoneProps} aria-label="Controle virtual (clique para ativar W/S/A/D/Q/E no teclado)">
          <${GamepadSvg} kind=${activeKind} live=${shown} seen=${w.phase === 'keys' ? w.seen : null} ctl=${vp} keys=${pad?.motion?.keys} />
        </div>
        <${VpadBar} vp=${vp} pad=${pad} />
        ${['error', 'absent', 'denied'].includes(live.state) ? html`<p class="pd-small-p">${live.why || 'Não foi possível ler os botões'}</p>` : null}
        ${!connected && live.state !== 'attached' ? html`<p class="pd-small-p">Nenhum controle físico conectado: a figura acima é um controle virtual clicável, com as mesmas funções do padd do robô. O desenho mostra ${kindOf(activeKind).label}.</p>` : null}
        <details class="pd-legend-box">
          <summary>Guia dos botões</summary>
          <${Legend} kind=${activeKind} live=${shown} bindings=${pad?.bindings} imuHead=${pad?.virtual?.pad_imu_head} />
        </details>
      </section>
      <div class=${cx('pd-left', !visualFits && 'pd-left-overflow')}><${PadDuck} st=${st} pad=${pad} vp=${vp} live=${duckLive} />
        <${InlineCamera} api=${api} active=${previewActive} /></div>
      <${Remote} st=${st} pad=${pad} link=${link} vp=${vp} />
    </div>
    <div class="pd-more">
      ${showWizard ? html`<${Wizard} w=${w} op=${op} kind=${kind} setKind=${setKind} onClose=${() => { setWizardOpen(false); op({ op: 'wizard_reset' }); }} />` : null}
      <${EStopTest} pad=${pad} op=${op} />
      <${KnownPads} pad=${pad} op=${op} />
    </div>
  </section>`;
}
