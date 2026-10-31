// Página da IMU: exibe a postura atual, permite selecionar o chip e calibrar a orientação de montagem com o robô em pé.
// O assistente coleta leituras na pose oficial e inclinações para frente, para trás e para os lados; o código calcula a correção.
// A instalação varia entre robôs, então a orientação precisa ser verificada e calibrada.
//
// - O botão principal percorre os estados: iniciar coleta → coletando (clique para encerrar) → calculando → resultado.
// - A coleta começa com 3 s parado sobre a mesa; depois inclina para frente, para trás, para a esquerda e para a direita, em qualquer ordem.
//   Antes de cada inclinação, nivele e aguarde meio segundo; incline e mantenha por 1 s. A seta no modelo 3D demonstra a próxima direção.
//   Cada direção concluída acende um ponto e toca um sinal curto. Ao concluir as cinco etapas, a coleta termina; é possível continuar ou recomeçar se faltar alguma.
// - O resultado compara lado a lado as poses antes e depois da calibração, com referência vertical, ângulo e diferença.
//   Quando a calibração completa em pé fica a menos de 2° da orientação usada pelo programa principal e a postura inclina no máximo 5°,
//   o backend registra a verificação na lista inicial do painel (res.check); isso é apenas um registro e não grava dados no robô.
//   Se a verificação falhar, o motivo e as etapas a repetir vêm em redo.
// - As regras de estabilidade e nivelamento correspondem a find_hold / find_ref em studio/imu_calib.py, com parâmetros equivalentes em RULES.
//   O frontend exige critérios mais rigorosos: inclinação de 12° a 30°, parada de 1 s e direção a no máximo 35° de um dos quatro eixos.
//   O backend calcula a orientação via link.cmd('imu.op', {op:'solve', samples}), com samples no formato [{step, t, g}].
// - O backend (studio/imu.py) recebe solve / coarse-capture / verify. No modo de calibração de fábrica, coleta repouso e inclinação frontal
//   de busStatus.last_sample.imu e solicita ao programa principal que valide e grave a orientação.
//   A placa do barramento é identificada na inicialização; a detecção de chips I²C continua usando microduck-firstboot.
import { html, useState, useEffect, useRef } from './vendor/preact-htm.module.js';
import { Duck3D } from './duck3d.js';
import { TwoStep } from './confirm.js';

const RULES = {
  // ---- Mesmos nomes e valores que RULES em imu_calib.py; mantenha os dois lados sincronizados. ----
  still_min_n: 15,
  still_max_spread_deg: 1.5,
  level_deg: 5,              // Nivelamento: dentro desta diferença em relação ao repouso na mesa.
  ref_min_n: 5,              // Número mínimo de leituras consecutivas niveladas.
  ref_spread_deg: 1.5,       // Oscilação máxima durante o nivelamento.
  hold_band_deg: 1.8,        // Na parada, leituras dentro desta diferença da última; ignora um salto isolado.
  // ---- Critérios mais rigorosos do frontend ----
  still_s: 3.0,              // Coletar 3 s em repouso.
  hold_min_n: 8,             // O backend exige 5.
  hold_s: 1.0,               // Uma direção é concluída após 1 s de parada.
  tilt_go_deg: 12,           // O backend exige no mínimo 10°.
  tilt_target_deg: 15,
  tilt_max_deg: 30,          // O backend permite até 35°.
  dir_max_deg: 35,           // Desvio máximo em relação aos eixos frontal, traseiro e laterais.
  stale_ms: 1000,
  dedupe_ms: 40,             // Sem state_t_ns, leituras com menos diferença no horário de geração são consideradas duplicadas.
  max_step_n: 600,           // Máximo de leituras por etapa (um minuto a 10 Hz).
};

const STEPS = ['still', 'fwd', 'back', 'left', 'right'];
const TILTS = ['fwd', 'back', 'left', 'right'];
// dir: direção em que a gravidade se desloca ao inclinar o robô, relativa à orientação atual. Usada para identificar a inclinação e desenhar a seta.
const STEP = {
  still: { cn: 'Repouso em pé', short: 'repouso' },
  fwd: { cn: 'Inclinação frontal', short: 'frente', dir: 0, how: 'abaixe o lado da cabeça' },
  back: { cn: 'Inclinação para trás', short: 'trás', dir: 180, how: 'abaixe o lado da cauda' },
  left: { cn: 'Inclinação para a esquerda', short: 'esquerda', dir: 90, how: 'abaixe o lado esquerdo do robô (visto por trás, o seu lado esquerdo)' },
  right: { cn: 'Inclinação para a direita', short: 'direita', dir: -90, how: 'abaixe o lado direito do robô (visto por trás, o seu lado direito)' },
};
const DIRV = { fwd: [1, 0, 0], back: [-1, 0, 0], left: [0, 1, 0], right: [0, -1, 0] };   // Referencial do corpo, igual ao referencial mundial da cena 3D.

const CHIP_CN = { bus: 'Placa do barramento (ID 200)', bno08x: 'BNO085 (I²C)', lsm6dsv16x: 'LSM6DSV16X (I²C)' };
const BUS_BOARD_CN = { ft6: 'FT6', imu_to_dxl: 'IMU-to-DXL', sflp_124_12: 'SFLP 124/12', qinmo: 'Qinmo (configurado)' };
const BUS_PROTOCOL_CN = { feetech: 'Feetech', dxl2: 'Dynamixel 2.0' };
const unsupportedProfile = info => info && info.profile !== undefined && !['legacy', 'qinmo'].includes(info.profile);
const unsupportedTransport = info => info && (!['feetech', 'dxl2'].includes(info.protocol) || unsupportedProfile(info));
function chipLabel(imu) {
  if (imu?.source !== 'bus') return CHIP_CN[imu?.source] || imu?.source || '—';
  const info = imu.imu_bus;
  if (imu?.profile_error || unsupportedTransport(info)) return 'Protocolo ou tipo da IMU não confirmado';
  return info ? `${BUS_BOARD_CN[info.board] || info.board || 'Placa do barramento'} · ${BUS_PROTOCOL_CN[info.protocol] || info.protocol} (ID 200)`
    : CHIP_CN.bus;
}
function imuContext(mode, imu) {
  return JSON.stringify([mode, imu?.source, imu?.source === 'bus' ? imu.imu_bus || null : null,
    imu?.configured_imu_profile ?? null, imu?.metadata_error ?? null, imu?.profile_error ?? null,
    imu?.redo?.session_id || null, !!imu?.redo?.active]);
}

// ---------------- Cálculos auxiliares (mesmo método de imu_calib.py) ----------------

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = (a) => Math.sqrt(dot(a, a));
const unit = (a) => { const n = len(a); return Number.isFinite(n) && n > 1e-9 ? [a[0] / n, a[1] / n, a[2] / n] : null; };
const deg = (r) => r * 180 / Math.PI;
const rad = (d) => d * Math.PI / 180;
const angle = (a, b) => { const ua = unit(a), ub = unit(b); return ua && ub ? deg(Math.acos(Math.max(-1, Math.min(1, dot(ua, ub))))) : null; };
const meanDir = (vs) => (vs.length ? unit(vs.reduce((s, v) => [s[0] + v[0], s[1] + v[1], s[2] + v[2]], [0, 0, 0])) : null);
const spread = (vs) => { const m = meanDir(vs); return m ? Math.max(0, ...vs.map((v) => angle(v, m) ?? 0)) : 0; };
// Percentil 90 (imu_calib.spread_p90_deg): usado na etapa de repouso para ignorar leituras isoladas fora do padrão.
const spreadP90 = (vs) => {
  const m = meanDir(vs);
  if (!m) return 0;
  const ds = vs.map((v) => angle(v, m) ?? 0).sort((a, b) => a - b);
  return ds[Math.floor(0.9 * (ds.length - 1))];
};
// imu_calib.trimmed_mean_dir: remove os 10% mais distantes da média antes de calcular a direção média do repouso.
const trimmedMeanDir = (vs) => {
  const m = meanDir(vs);
  if (!m) return null;
  const lim = spreadP90(vs);
  return meanDir(vs.filter((v) => (angle(v, m) ?? 0) <= lim + 1e-9)) || m;
};
const okVec = (g) => Array.isArray(g) && g.length === 3 && g.every((x) => typeof x === 'number' && Number.isFinite(x));
const DOWN = [0, 0, -1];

/** Calcula o ângulo e a direção da inclinação em relação a g0. Mesmo método de imu_calib.tilt_of. */
function tiltOf(g0, g) {
  const t = angle(g0, g);
  const up = [-g0[0], -g0[1], -g0[2]];
  const d = sub(g, g0);
  const h = sub(d, up.map((u) => u * dot(d, up)));
  const x0 = sub([1, 0, 0], up.map((u) => u * up[0]));
  if (!unit(h) || !unit(x0)) return { t, d: null };
  const a = unit(x0), b = unit(h);
  return { t, d: deg(Math.atan2(dot(cross(a, b), up), dot(a, b))) };
}

function qRotate(q, v) {
  const [w, x, y, z] = q;
  const r = [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]];
  return r.map((row) => dot(row, v));
}

const fmt = (v, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—');
const sgn = (v, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? `${v > 0 ? '+' : ''}${v.toFixed(d)}` : '—');
const dirDiff = (a, b) => Math.abs(((a - b) % 360 + 540) % 360 - 180);
const names = (ks) => ks.map((k) => STEP[k].cn).join(', ');

// ---------------- Trechos estáveis e referência nivelada (correspondem a _run_back / find_hold / find_ref de imu_calib.py) ----------------

function runBack(gs, end, band) {
  const last = gs[end];
  const idx = [end];
  let skipped = 0, j = end - 1;
  while (j >= 0) {
    if (angle(gs[j], last) <= band) { idx.push(j); j--; }
    else if (j - 1 >= 0 && angle(gs[j - 1], last) <= band) { skipped++; j--; }   // Ignora uma leitura isolada fora do padrão.
    else break;
  }
  return { idx: idx.sort((a, b) => a - b), skipped };
}

function findHold(gs) {
  if (!gs.length) return { idx: [], skipped: 0 };
  let best = runBack(gs, gs.length - 1, RULES.hold_band_deg);
  if (gs.length >= 2) {
    const alt = runBack(gs, gs.length - 2, RULES.hold_band_deg);
    if (alt.idx.length > best.idx.length + 1) best = alt;
  }
  return best;
}

function findRef(gs, g0, before) {
  const n = RULES.ref_min_n;
  for (let end = before; end >= n; end--) {
    const win = gs.slice(end - n, end);
    if (win.every((v) => (angle(g0, v) ?? 0) <= RULES.level_deg)) {
      const m = meanDir(win);
      if (m && spread(win) <= RULES.ref_spread_deg) return m;
    }
  }
  return null;
}

// ---------------- Coleta (estado em ref; alimentada a cada quadro de st) ----------------
// phase: idle → collect → solving (etapas completas) → done / error; coleta encerrada incompleta → short (continuar / recomeçar).

function freshWizard() {
  return { phase: 'idle', t0: 0, g0: null,
    buf: { still: [], fwd: [], back: [], left: [], right: [] },          // Leituras de cada etapa concluída; o backend encontra nelas o nivelamento e a parada.
    done: { still: false, fwd: false, back: false, left: false, right: false },
    seg: [],                 // Leituras desde a conclusão da direção anterior.
    ref: null, level: 0, cand: null, inZone: false, repeat: null, needLevel: false,
    live: null, progress: 0, hold: 0, paused: null, moved: false, over: false,
    lastKey: null, lastBirth: null, events: [], missing: [], result: null, error: null };
}

const missingSteps = (W) => STEPS.filter((k) => !W.done[k]);
const nextTodo = (W) => TILTS.find((k) => !W.done[k]) || null;

/** Processa um quadro. live indica se a conexão está atual, conforme o mesmo critério do painel; sem live, consulta joints_age_ms.
 * Retorna true quando a tela deve redesenhar. Ao concluir uma etapa, adiciona um evento a W.events para tocar o sinal sonoro. */
function feed(W, st, live) {
  if (W.phase !== 'collect') return false;
  const g = st?.gravity;
  const fresh = live !== false && st && st.joints_age_ms != null && st.joints_age_ms < RULES.stale_ms;
  if (!okVec(g) || !fresh) { const p = W.paused; W.paused = 'Leitura interrompida. Aguardando a conexão; os dados coletados foram preservados.'; return p !== W.paused; }
  const gu = unit(g);
  if (!gu) return false;
  // Remove duplicatas: Studio e robot.state publicam a 10 Hz, então uma leitura pode chegar duas vezes.
  // Prefere state_t_ns; sem ele, usa o horário de geração estimado como hora de recebimento menos joints_age_ms.
  const birth = performance.now() - st.joints_age_ms;
  if (st.state_t_ns != null) {
    if (st.state_t_ns === W.lastKey) return false;
    W.lastKey = st.state_t_ns;
  } else {
    if (W.lastBirth != null && Math.abs(birth - W.lastBirth) < RULES.dedupe_ms) return false;
    W.lastBirth = birth;
  }
  W.paused = null;
  const s = { t: +(birth / 1000 - W.t0).toFixed(3), g: gu.map((x) => +x.toFixed(6)) };
  if (!W.done.still) {
    const b = W.buf.still;
    b.push(s);
    if (spreadP90(b.map((x) => x.g)) > RULES.still_max_spread_deg) { W.buf.still = [s]; W.moved = true; }
    const b2 = W.buf.still;
    W.progress = Math.min(1, (b2[b2.length - 1].t - b2[0].t) / RULES.still_s);
    if (W.progress >= 1 && b2.length >= RULES.still_min_n) {
      W.g0 = trimmedMeanDir(b2.map((x) => x.g));
      W.done.still = true; W.moved = false; W.progress = 0; W.seg = []; W.ref = null;
      finishStep(W, 'still');
    }
    return true;
  }
  // As quatro inclinações podem ocorrer em qualquer ordem. Acumula leituras em seg e identifica a direção quando o robô para.
  const b = W.seg;
  b.push(s);
  if (b.length > RULES.max_step_n) b.splice(0, b.length - RULES.max_step_n);
  const gs = b.map((x) => x.g);
  // Nivelamento: as últimas ref_min_n leituras devem estar próximas do repouso na mesa e oscilar pouco; esse trecho é a referência da próxima inclinação.
  const n = RULES.ref_min_n;
  const tail = gs.slice(-n);
  const levelNow = tail.length === n && tail.every((v) => angle(W.g0, v) <= RULES.level_deg) && spread(tail) <= RULES.ref_spread_deg;
  if (levelNow) W.ref = meanDir(tail);
  let k = 0;
  for (let i = gs.length - 1; i >= 0 && k < n && angle(W.g0, gs[i]) <= RULES.level_deg; i--) k++;
  W.level = levelNow ? 1 : k / n;
  W.live = tiltOf(W.ref || W.g0, gu);
  W.over = W.live.t > RULES.tilt_max_deg;
  W.hold = 0; W.inZone = false; W.cand = null; W.repeat = null; W.needLevel = false;
  // A parada segue os mesmos critérios do backend, com exigências adicionais do frontend: inclinação de 12° a 30°, eixo a até 35° e parada de 1 s.
  const { idx } = findHold(gs);
  const hold = idx.map((i) => b[i]);
  const hm = meanDir(hold.map((x) => x.g));
  if (!hm) return true;
  const href = findRef(gs, W.g0, idx[0]);
  const ht = tiltOf(href || W.g0, hm);
  if (!(ht.t >= RULES.tilt_go_deg && ht.t <= RULES.tilt_max_deg) || ht.d == null) return true;
  const dirK = TILTS.find((x) => dirDiff(ht.d, STEP[x].dir) <= RULES.dir_max_deg) || null;
  W.cand = dirK;
  if (!dirK) return true;
  if (W.done[dirK]) { W.repeat = dirK; return true; }
  if (!href) { W.needLevel = true; return true; }
  W.inZone = true;
  const span = hold.length > 1 ? hold[hold.length - 1].t - hold[0].t : 0;
  W.hold = Math.min(1, (span + 1e-6) / RULES.hold_s);
  if (hold.length >= RULES.hold_min_n && W.hold >= 1) {
    W.buf[dirK] = b.slice();
    W.done[dirK] = true;
    W.seg = []; W.ref = null; W.hold = 0; W.inZone = false; W.cand = null;
    finishStep(W, dirK);
  }
  return true;
}

function finishStep(W, k) {
  if (!missingSteps(W).length) { W.phase = 'solving'; W.events.push('all'); }
  else W.events.push(k);
}

/** Inicia uma nova coleta. */
function startCollect(W, now) {
  Object.assign(W, freshWizard(), { phase: 'collect', t0: now });
}

/** Encerra a coleta: calcula se estiver completa ou informa as etapas faltantes. */
function endCollect(W) {
  if (W.phase !== 'collect') return;
  const miss = missingSteps(W);
  if (!miss.length) { W.phase = 'solving'; return; }
  W.phase = 'short'; W.missing = miss;
}

/** Continua a coleta preservando as etapas já concluídas. */
function resumeCollect(W) {
  W.phase = 'collect'; W.seg = []; W.ref = null; W.paused = null; W.missing = []; W.result = null; W.error = null;
  if (!W.done.still) { W.buf.still = []; W.progress = 0; }
}

/** Refaz somente as etapas indicadas pelo backend em redo. */
function redoSteps(W, steps) {
  for (const k of steps) { if (k in W.done) { W.done[k] = false; W.buf[k] = []; } }
  resumeCollect(W);
}

/** Prepara a lista plana de leituras para o backend, com step em cada item (studio/imu.py espera uma lista). */
function payload(W) {
  return STEPS.flatMap((k) => W.buf[k].map((x) => ({ step: k, t: x.t, g: x.g })));
}

// ---------------- Sinais sonoros (síntese via Web Audio; preferência de silêncio salva no localStorage) ----------------

const MUTE_KEY = 'studio.imu.mute';
function loadMute() { try { return localStorage.getItem(MUTE_KEY) === '1'; } catch { return false; } }
function saveMute(v) { try { localStorage.setItem(MUTE_KEY, v ? '1' : '0'); } catch { /* Em modo privado, vale somente nesta página. */ } }
let actx = null;
/** O navegador exige uma interação do usuário para liberar áudio; chamado ao clicar em “Iniciar coleta”. */
function audioUnlock() {
  try {
    const C = window.AudioContext || window.webkitAudioContext;
    if (!C) return;
    actx = actx || new C();
    if (actx.state === 'suspended') actx.resume();
  } catch { actx = null; }
}
function beep(kind) {
  if (!actx) return;
  try {
    const t = actx.currentTime + 0.01;
    // Direção concluída: 990 Hz; repouso: 660 Hz; todas completas: dois tons ascendentes.
    const tones = kind === 'all' ? [[880, 0], [1320, 0.13]] : [[kind === 'still' ? 660 : 990, 0]];
    for (const [f, dt] of tones) {
      const o = actx.createOscillator(), gn = actx.createGain();
      o.type = 'sine';
      o.frequency.value = f;
      gn.gain.setValueAtTime(0.0001, t + dt);
      gn.gain.exponentialRampToValueAtTime(0.06, t + dt + 0.012);
      gn.gain.exponentialRampToValueAtTime(0.0001, t + dt + 0.11);
      o.connect(gn); gn.connect(actx.destination);
      o.start(t + dt); o.stop(t + dt + 0.12);
    }
  } catch { /* Ignora falhas de áudio. */ }
}

// ---------------- 3D ----------------

const reduceMotion = () => { try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; } };

/** Desenha sobre o 3D a referência vertical e uma seta animada indicando a próxima inclinação, usando a projeção da câmera do robô. */
function drawOverlay(d, canvas, svg, arrow, plumb, now) {
  if (!svg) return;
  if (!d || !d.ready || !d.home || !d.blob) { svg.innerHTML = ''; return; }
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  const V = d.camera.position.constructor;           // Vector3 do three.js; não precisa importar three separadamente.
  d.camera.updateMatrixWorld();
  const P = d.blob.position;                          // Centro no chão, sob os pés.
  const H = 2 * (d.home.target.z - P.z);              // Altura do robô.
  const pr = (x, y, z) => { const v = new V(x, y, z).project(d.camera); return [(v.x + 1) / 2 * w, (1 - v.y) / 2 * h]; };
  let out = '';
  if (plumb) {
    const [x1, y1] = pr(P.x, P.y, P.z), [x2, y2] = pr(P.x, P.y, P.z + H * 1.12);
    out += `<line class="plumb" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
  }
  if (arrow && DIRV[arrow]) {
    const u = DIRV[arrow], R = H * 1.08;
    const swing = reduceMotion() ? 1 : 0.55 + 0.45 * Math.sin(now / 260);
    const end = 6 + 20 * swing;                        // O arco oscila de 6° a 26° a partir do topo da cabeça.
    const pts = [];
    for (let a = 0; a <= end + 1e-6; a += 2) {
      const s = Math.sin(rad(a)), c = Math.cos(rad(a));
      pts.push(pr(P.x + R * s * u[0], P.y + R * s * u[1], P.z + R * c));
    }
    if (pts.length >= 2) {
      const [ex, ey] = pts[pts.length - 1], [px, py] = pts[pts.length - 2];
      const dx = ex - px, dy = ey - py, L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L, sz = Math.max(12, h * 0.03);
      const head = `${ex + ux * sz},${ey + uy * sz} ${ex - uy * sz * 0.6},${ey + ux * sz * 0.6} ${ex + uy * sz * 0.6},${ey - ux * sz * 0.6}`;
      // Linha tracejada demonstra o robô inclinado, do chão até a ponta da seta.
      const [gx, gy] = pr(P.x, P.y, P.z);
      out += `<line class="ghost" x1="${gx}" y1="${gy}" x2="${ex}" y2="${ey}"/>`;
      out += `<polyline class="arc" points="${pts.map((p) => p.join(',')).join(' ')}"/><polygon class="head" points="${head}"/>`;
      // Posiciona o rótulo abaixo da seta, sem cobrir o ângulo nem sair da área visível.
      const lx = Math.min(w - 50, Math.max(50, ex)), ly = Math.min(h - 50, Math.max(120, ey + sz + 26));
      out += `<text class="lbl" x="${lx}" y="${ly}">Incline para ${STEP[arrow].short}</text>`;
    }
  }
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.innerHTML = out;
}

/** Define a câmera. Aceita vistas predefinidas do Duck3D ou ângulos {az, el} em graus; az 0 é frontal e −90 é o lado direito do robô. */
function applyView(d, view) {
  if (typeof view === 'string') { d.setView(view); return; }
  d.setView('front');
  const h = d.home;
  if (!h) return;
  const t = h.target, dist = h.pos.distanceTo(t), az = rad(view.az), el = rad(view.el);
  h.pos.set(t.x + dist * Math.cos(el) * Math.cos(az), t.y + dist * Math.cos(el) * Math.sin(az), t.z + dist * Math.sin(el));
  d.camera.position.copy(h.pos);
  d.controls.target.copy(t);
  d.controls.update();
  d.dirty = true;
}

function DuckView({ g, joints, stale, arrow, plumb, view = 'front34', children }) {
  const canvasRef = useRef(null), duckRef = useRef(null), svgRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [moved, setMoved] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    const d = new Duck3D(canvasRef.current, { view: 'front34', centerX: 0.5, centerY: 0.56, fill: 0.7 });
    duckRef.current = d;
    d.onUserMove = () => setMoved(true);
    d.load('model/').then(() => setReady(true)).catch((e) => setErr(`Falha ao carregar o modelo 3D: ${e.message}`));
    return () => d.dispose();
  }, []);

  useEffect(() => {
    const d = duckRef.current;
    if (!d || !ready) return;
    if (Array.isArray(joints)) d.setJoints(joints);
    d.setGravity(g);
  }, [g, joints, ready]);

  const viewKey = JSON.stringify(view);
  useEffect(() => {
    if (!ready || !duckRef.current) return;
    applyView(duckRef.current, view);
    setMoved(false);
  }, [ready, viewKey]);

  useEffect(() => {
    if (!ready) return undefined;
    if (!arrow && !plumb) { if (svgRef.current) svgRef.current.innerHTML = ''; return undefined; }
    let raf = 0;
    const tick = (now) => { drawOverlay(duckRef.current, canvasRef.current, svgRef.current, arrow, plumb, now || 0); raf = requestAnimationFrame(tick); };
    tick(performance.now());
    return () => cancelAnimationFrame(raf);
  }, [ready, arrow, plumb]);

  return html`<div class="imu-view">
    <canvas ref=${canvasRef} class=${stale ? 'stale' : ''}></canvas>
    <svg class="imu-overlay" ref=${svgRef} aria-hidden="true"></svg>
    ${err ? html`<span class="imu-note" role="alert">${err}</span>` : children}
    ${moved ? html`<button class="reset-view" onClick=${(e) => { e.currentTarget.blur(); duckRef.current?.resetView(); setMoved(false); }}>Redefinir visão</button>` : null}
  </div>`;
}

/** Exibe um robô durante a coleta, com a seta da próxima etapa; após o cálculo, compara as poses antes e depois.
 * Mantém a primeira instância 3D ao alternar. Durante a coleta, a vista é por trás; na comparação, escolhe a vista lateral ou frontal conforme a correção. */
function ImuStage({ st, stale, corr, parts, collecting, arrow, cue }) {
  const g = okVec(st?.gravity) ? st.gravity : null;
  const joints = st?.joints;
  const after = g && corr ? qRotate(corr, g) : null;
  const tb = g ? angle(g, DOWN) : null, ta = after ? angle(after, DOWN) : null;
  const old = stale || !g;
  const sideways = corr && Math.abs(parts?.pitch_deg ?? 0) >= Math.abs(parts?.roll_deg ?? 0);
  const view = corr ? (sideways ? { az: -80, el: 6 } : 'front') : collecting ? 'back34' : 'front34';
  const noteLive = old ? html`<span class="imu-note">${g ? 'Leitura desatualizada; não representa a posição atual' : 'Sem dados de postura'} · disponíveis quando o programa principal está no modo de movimento</span>`
    : html`<span class="imu-note">Ao vivo · inclinação do corpo conforme a IMU</span>`;
  return html`<div class="imu-stage-wrap">
    <div class=${'imu-stage' + (corr ? ' duo' : '')}>
      <${DuckView} key="before" g=${g} joints=${joints} stale=${old} arrow=${corr ? null : arrow} plumb=${!!corr} view=${view}>
        <div class="imu-stage-read num"><span>${corr ? 'Antes da calibração' : 'Inclinação do corpo (em relação à vertical)'}</span><b>${fmt(tb)}°</b></div>
        ${!corr && cue ? html`<span class="imu-cue">${cue}</span>` : null}
        ${corr ? html`<span class="imu-note">Orientação salva atual</span>` : noteLive}
      <//>
      ${corr ? html`<${DuckView} key="after" g=${after} joints=${joints} stale=${old} plumb=${true} view=${view}>
        <div class="imu-stage-read num after"><span>Após a calibração</span><b>${fmt(ta)}°</b></div>
        <span class="imu-note">Com a nova orientação · ainda não gravada</span>
      <//>` : null}
    </div>
    ${corr ? html`<p class="imu-diff num">Em pé: inclinação antes <b>${fmt(tb)}°</b> → depois <b>${fmt(ta)}°</b>; diferença <b>${fmt(g && after ? angle(g, after) : null)}°</b>.
      Ambos os modelos usam leituras atuais; a linha tracejada indica a vertical. ${sideways ? 'Vista lateral (correção principalmente frontal/traseira).' : 'Vista frontal (correção principalmente lateral).'}</p>` : null}
  </div>`;
}

// ---------------- Indicador de direção: quatro pontos cardeais e repouso ao centro; concluídos acendem, próximo pisca e o ponto azul mostra a inclinação atual. ----------------

function DirPad({ W }) {
  const C = 100, R = 80, MAX = 32;
  const r = (t) => Math.min(t, MAX) / MAX * R;
  const pt = (t, d) => [C - r(t) * Math.sin(rad(d)), C - r(t) * Math.cos(rad(d))];   // Cabeça para cima: frente para cima e esquerda do robô para a esquerda.
  const collecting = W.phase === 'collect';
  const next = collecting && W.done.still ? nextTodo(W) : null;
  const L = collecting && W.done.still ? W.live : null;
  const p = L && L.t != null ? pt(L.t, L.d ?? 0) : [C, C];
  const ring = (t) => html`<circle cx=${C} cy=${C} r=${r(t)} class="pad-ring" />`;
  return html`<svg class="imu-pad" viewBox="0 0 200 200" role="img"
    aria-label=${`Concluído: ${names(STEPS.filter((k) => W.done[k])) || 'nenhuma etapa'}`}>
    <circle cx=${C} cy=${C} r=${R + 6} class="pad-bg" />
    ${ring(RULES.tilt_go_deg)}${ring(RULES.tilt_max_deg)}
    ${TILTS.map((k) => {
      const [x, y] = pt(20, STEP[k].dir), [lx, ly] = pt(33, STEP[k].dir);
      const cls = W.done[k] ? 'done' : k === next ? 'next' : (k === W.cand && W.inZone ? 'hot' : '');
      return html`<g class=${'pad-dot ' + cls}><circle cx=${x} cy=${y} r="13" />
        ${W.done[k] ? html`<path d=${`M${x - 5.5},${y} l4,4 l7,-8`} class="tick" />` : null}
        <text x=${lx} y=${ly + 4} class="pad-lbl">${STEP[k].short}</text></g>`;
    })}
    <g class=${'pad-dot center ' + (W.done.still ? 'done' : collecting ? 'next' : '')}>
      <circle cx=${C} cy=${C} r="11" />
      ${W.done.still ? html`<path d=${`M${C - 5},${C} l3.5,3.5 l6.5,-7.5`} class="tick" />` : null}
    </g>
    ${L && W.hold > 0 ? html`<circle cx=${p[0]} cy=${p[1]} r="12" class="pad-hold"
      style=${`stroke-dasharray:${(W.hold * 75.4).toFixed(1)} 76`} transform=${`rotate(-90 ${p[0]} ${p[1]})`} />` : null}
    ${L ? html`<circle cx=${p[0]} cy=${p[1]} r="6" class=${'pad-live' + (W.over ? ' over' : W.inZone ? ' on' : '')} />` : null}
  </svg>`;
}

// ---------------- Cartões laterais ----------------

// Considera a orientação confirmada somente quando imu.mount.verified (retornado por calibration-status no studio/imu.py) é verdadeiro.
// O programa principal só informa orientação confirmada ou não confirmada; a orientação temporária só aparece quando imu.temporary é enviado.
function statusOf(st, imu, live) {
  const s = st?.imu?.status;
  const v = imu?.mount?.verified;
  if (imu?.profile_error) return { word: 'Tipo da IMU não confirmado', kind: 'bad', hint: imu.profile_error };
  if (imu?.mount_protocol_mismatch) return { word: 'Recalibre a orientação', kind: 'warn',
    hint: 'O protocolo ou tipo atual do barramento não corresponde à orientação de montagem salva. Recalibre abaixo e solicite a validação do programa principal.' };
  if (v === false) {
    return { word: 'Orientação não confirmada', kind: 'warn',
      hint: st?.posture === 'starting' ? 'O programa principal não entra no modo de movimento: faça primeiro a calibração inicial.' : 'Uma montagem desalinhada pode fazer o robô avançar ao caminhar. Calibre primeiro.' };
  }
  if (imu?.temporary) return { word: 'Orientação temporária', kind: 'warn', hint: 'A direção para cima foi identificada, mas a direção frontal não foi verificada. Pode ficar em pé, mas não caminhe.' };
  if (live !== false && s === 'missing') return { word: 'IMU indisponível', kind: 'bad', hint: 'Verifique a conexão do módulo ou redetecte o chip abaixo.' };
  if (live !== false && s === 'frozen') return { word: 'Leitura da IMU congelada', kind: 'bad', hint: 'A postura não está sendo atualizada. Não caminhe.' };
  // Se a mensagem da IMU ainda não chegou, IMU normal no modo de movimento indica orientação confirmada.
  if (v === true || (v == null && s === 'ok' && st?.mode === 'motion')) {
    const when = imu?.stand_calib_at;
    return { word: 'Orientação confirmada', kind: 'ok', hint: when ? `Última calibração em pé: ${when}` : 'O programa principal verificou as direções para cima e para frente; a postura em pé ainda não foi calibrada.' };
  }
  return { word: 'Desconhecida', kind: null, hint: 'A orientação de montagem salva pelo programa principal ainda não foi recebida.' };
}

function freshText(st, live, age) {
  if (live === false) return { live: false, text: Number.isFinite(age) ? `Sem atualização há ${Math.round(age / 1000)} s` : 'MicroDuck desconectado' };
  const a = st?.joints_age_ms;
  if (a == null) return { live: false, text: 'Sem leitura' };
  if (a >= RULES.stale_ms) return { live: false, text: `Sem atualização há ${Math.round(a / 1000)} s` };
  return { live: true, text: 'Ao vivo' };
}

function StatusCard({ st, imu, live, age }) {
  const S = statusOf(st, imu, live);
  const F = freshText(st, live, age);
  const src = imu?.source;
  const guard = st?.guard;
  return html`<section class=${'board imu-card' + (F.live ? '' : ' imu-stale')}>
    <h3>Estado atual${F.live ? '' : html` <span class="sv-small">(${F.text}; abaixo, últimos dados antes da desconexão)</span>`}</h3>
    <div class="imu-kv">
      <span>Orientação</span><b class=${'imu-word ' + (S.kind || '')}>${S.kind === 'warn' || S.kind === 'bad' ? html`<span class=${'badge ' + S.kind}>${S.kind === 'bad' ? '×' : '!'}</span>` : S.kind === 'ok' ? '✓ ' : ''}${S.word}</b>
      <span></span><span class="sv-small">${S.hint}</span>
      <span>Chip</span><b>${chipLabel(imu)}</b>
      ${src === 'bus' ? html`<span>Tipo configurado</span><b>${imu?.configured_imu_profile === 'qinmo' ? 'Qinmo (configurado)'
        : imu?.configured_imu_profile === 'legacy' ? 'Placa existente detectada automaticamente'
        : imu?.metadata_error || unsupportedTransport(imu?.imu_bus) ? 'Não confirmado (diagnóstico incompatível)'
        : imu?.configured_imu_profile != null ? 'Tipo incompatível (requer confirmação)' : 'Placa existente (programa principal antigo)'}</b>
        <span>Conexão real</span><b>${imu?.imu_bus ? chipLabel(imu) : 'Ainda não conectada'}</b>
        <span>Unidade de velocidade angular</span><b class="num">${imu?.profile_error || unsupportedTransport(imu?.imu_bus) ? 'Não confirmada (diagnóstico incompatível)'
          : imu?.imu_bus?.profile === 'qinmo' ? 'Valor bruto ÷ 16,4 °/s'
          : imu?.imu_bus ? 'Valor bruto × 0,0175 °/s' : 'Exibida após a conexão'}</b>` : null}
      <span>Inclinação</span><b class="num">${fmt(st?.tilt_deg)}°<small> em relação à vertical; o programa principal só permite andar dentro de ${guard?.tilt_tolerance_deg ?? 10}°</small></b>
      <span>Postura em pé</span><b class="num">${st?.hold ? html`desvio máximo de HOME: ${fmt(st.hold.max_error_deg)}°<small> postura do modo de calibração ${st.hold.stage === 'holding' ? 'estável' : 'levantando'}</small>`
        : guard?.max_joint_error_deg != null ? html`desvio máximo de HOME: ${fmt(guard.max_joint_error_deg)}°<small> postura válida dentro de ${guard.joint_tolerance_deg ?? 5}°</small>` : '—'}</b>
      <span>Leitura</span><b class=${'num' + (F.live ? '' : ' imu-dim')}>${F.text}${imu?.reader?.errors ? html`<small> ${imu.reader.errors} falhas de leitura</small>` : null}</b>
    </div>
    ${src === 'bus' && imu?.imu_bus?.protocol === 'dxl2' ? html`<p class="sv-small">Este tipo de placa não fornece número de amostra, bits de estado nem idade da leitura. O programa principal verifica a atualidade do recebimento e se os bytes brutos estão congelados.</p>` : null}
    ${imu?.mount?.quat ? html`<details class="imu-details"><summary>Orientação de montagem (quatérnio w, x, y, z)</summary>
      <code class="num">${imu.mount.quat.map((x) => fmt(x, 4)).join(', ')}</code>${imu.mount.verified ? ' · verificada' : ' · não verificada'}
      <p class="sv-small">Se a montagem mudou ou a última calibração ficou incorreta, calibre e valide novamente em “Orientação de montagem da IMU”.</p></details>` : null}
  </section>`;
}

function ChipCard({ imu, link, live }) {
  const [profile, setProfile] = useState(imu?.configured_imu_profile || 'legacy');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  useEffect(() => { setProfile(imu?.configured_imu_profile || 'legacy'); }, [imu?.configured_imu_profile]);
  const selection = imu?.profile_selection;
  const reason = live === false || link.status !== 'open' ? 'MicroDuck desconectado; aguardando reconexão.'
    : imu?.metadata_error || unsupportedTransport(imu?.imu_bus) ? imu?.metadata_error || imu?.profile_error || 'O programa principal informou um tipo de IMU incompatível.'
    : !selection?.can_start ? selection?.reason || 'O programa principal ainda não permite selecionar o tipo pela interface web. Atualize-o primeiro.' : null;
  const select = async () => {
    setBusy(true); setMessage(null);
    try {
      const reply = await link.cmd('imu.op', { op: 'profile-select', profile, confirmed: true }, 180000);
      setMessage(reply.ok ? 'Tipo salvo; reconectando no modo de calibração. Segure o robô com as duas mãos e mantenha os motores sem força enquanto coleta e valida a orientação acima.'
        : reply.reason || reply.error || 'A seleção do tipo não foi concluída. Confira o estado da sessão; é possível cancelar e restaurar os parâmetros anteriores.');
    } finally { setBusy(false); }
  };
  return html`<section class="board imu-card">
    <h3>Chip <span class="sv-small">Em uso: ${chipLabel(imu)}</span></h3>
    <p class="sv-small">A detecção automática reconhece FT6 e IMU-to-DXL (Feetech), além de SFLP 124/12 (Dynamixel 2.0). FT6 e placas próprias são identificados pela assinatura conhecida; DXL2 genérico só tem o layout compatível confirmado.</p>
    <p class="sv-small">A identidade exclusiva do Qinmo não pode ser verificada pela documentação, então selecione-o aqui uma vez. A seleção e as unidades serão mantidas nas próximas inicializações. “Configurado” não significa certificação do fabricante. Se trocar a placa ou alterar a montagem, valide a orientação novamente.</p>
    ${imu?.source === 'bus' || imu?.source == null ? html`<label class="sv-small">Tipo de IMU do barramento
      <select aria-label="Tipo de IMU do barramento" value=${profile} disabled=${busy || !!imu?.redo?.active}
        onChange=${e => { setProfile(e.target.value); setMessage(null); }}>
        <option value="legacy">Detecção automática (placa existente)</option><option value="qinmo">Qinmo · Feetech · valor bruto ÷ 16,4 °/s</option>
      </select></label>
      <div class="imu-actions"><${TwoStep} key=${profile} label="Salvar tipo e reconectar"
        ask="O robô está seguro. Confirmar reconexão e recalibração?" onConfirm=${select} disabled=${busy || !!reason}
        title=${reason} busyLabel="Salvando tipo e reconectando…" /></div>
      <p class="sv-small">Segure o robô e mantenha os motores sem força. Ao salvar, o programa principal reinicia no modo de calibração e invalida a orientação anterior; a operação só termina após a validação. É possível cancelar e restaurar os parâmetros anteriores.</p>
      ${reason ? html`<p class="sv-warn">${reason}</p>` : null}
      ${message ? html`<p role="status" class="sv-small">${message}</p>` : null}` : null}
    <p class="sv-small">Conecte os módulos I²C antes da primeira inicialização. Se conectar depois, execute este comando via SSH no MicroDuck:</p>
    <p><code class="num">sudo microduck-firstboot --detect-imu-only --force</code></p>
    <p class="sv-small">O comando detecta novamente a IMU e atualiza a configuração de inicialização. Depois, reinicie o programa principal.</p>
  </section>`;
}

function blockReason(st, imu, live) {
  if (!st) return 'MicroDuck ainda não conectado.';
  if (live === false) return 'MicroDuck desconectado; aguardando reconexão.';
  if (imu?.profile_error) return imu.profile_error;
  if (imu?.redo?.active) return 'Recalibração da orientação em andamento. Conclua a validação pelo programa principal ou cancele e restaure os parâmetros anteriores.';
  if (st.posture === 'servo_session') return 'A página de servos ainda controla o barramento. Clique em “Devolver ao programa principal” no topo.';
  if (st.posture === 'absent') return 'O programa principal do MicroDuck não está em execução.';
  if (st.posture === 'starting') return `O programa principal ainda está iniciando${st.start_error ? `: ${st.start_error}` : ''}`;
  if (st.mode === 'commissioning') {
    // No modo de calibração também é possível ficar em pé para calibrar a postura e calcular uma orientação completa.
    if (!st.hold) return 'No modo de calibração, clique em “Ativar postura em pé” e segure o robô enquanto ele se levanta.';
    if (st.hold.stage !== 'holding') return 'Aguardando o robô estabilizar em pé.';
    if (!okVec(st.gravity) || st.joints_age_ms == null || st.joints_age_ms > RULES.stale_ms) return 'Sem dados atuais de postura.';
    return null;
  }
  if (imu?.mount?.verified === false) return 'A orientação ainda não foi confirmada. Faça primeiro a calibração inicial acima.';
  // Se o robô não estiver em pé, oriente a pessoa a ativar a postura em pé.
  if (st.posture === 'limp') return 'Motores sem força. Clique em “Ativar postura em pé” e segure o robô enquanto ele se levanta.';
  if (st.posture === 'homing') return 'O robô está se levantando; aguarde estabilizar.';
  if (st.posture === 'walking') return 'O robô está andando; pare-o primeiro.';
  if (st.posture === 'policy') return 'A política está em execução e o robô pode mover as pernas ao ser levantado. Pressione + no controle para voltar à postura segura.';
  if (st.posture === 'sitting') return 'O robô está sentado. Clique em “Ativar postura em pé” para levantá-lo.';
  if (st.posture !== 'holding') return 'Não foi possível identificar a postura atual.';
  if (!okVec(st.gravity) || st.joints_age_ms == null || st.joints_age_ms > RULES.stale_ms) return 'Sem dados atuais de postura.';
  if (st.imu?.status === 'missing' || st.imu?.status === 'frozen') return 'Leitura da IMU inválida. Verifique os cabos.';
  return null;
}

// ---------------- Ativar ou desativar a postura em pé ----------------
// Fora do modo de calibração, usa o mesmo comando “levantar” do cartão de controle e respeita as verificações do backend.
// “Desativar” usa o comando de liberação global. No modo de calibração, os 15 servos vão juntos para HOME em 3 s; não há equilíbrio, então segure o robô.
const POSE_CN = { holding: 'Em pé', policy: 'Em pé (política em execução)', walking: 'Andando', limp: 'Sem força', homing: 'Levantando',
  sitting: 'Sentado', commissioning: 'Modo de calibração (sem força)', starting: 'Programa principal iniciando', absent: 'Programa principal parado', servo_session: 'Ajustando servos' };
const HOLD_CN = { holding: 'Modo de calibração (em pé)', ramping: 'Modo de calibração (levantando)' };
const HOLD_CONFIRM = 'No modo de calibração, os 15 servos irão juntos para a postura em pé em 3 segundos e a manterão.\n'
  + 'Este modo não controla o equilíbrio; segure o robô depois que ele se levantar. A direção dos servos vem da página de servos ou, se nunca foi configurada, do arquivo do programa principal.\nSegure o MicroDuck com as duas mãos. Deseja continuar?';

function StanceCard({ st, imu, pd, link, live }) {
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const commissioning = (st?.mode || imu?.mode) === 'commissioning';
  const open = link.status === 'open';
  const hold = st?.hold || imu?.hold || null;
  const now = !st ? 'Ainda não conectado' : live === false ? 'MicroDuck desconectado' : st.posture === 'servo_session' ? POSE_CN.servo_session
    : commissioning && hold ? HOLD_CN[hold.stage] || 'Modo de calibração (em pé)' : (POSE_CN[st.posture] || 'Estado desconhecido');
  const sb = pd?.motion?.buttons?.stand;              // Verificação do botão “Levantar” enviada pelo backend no estado do controle.
  const standWhy = !st || live === false ? 'MicroDuck desconectado; aguardando reconexão.'
    : imu?.redo?.active ? 'Mantenha os motores sem força durante a recalibração e segure o robô. Levante-o após concluir ou cancelar.'
    : st.posture === 'servo_session' ? 'A página de servos ainda controla o barramento. Clique em “Devolver ao programa principal”.'
      : st.posture === 'starting' ? 'O programa principal ainda está iniciando; aguarde.'
        : commissioning ? (hold ? (hold.stage === 'holding' ? 'O robô já está em pé.' : 'O robô está se levantando.') : null)
          : sb && !sb.ok ? sb.why : null;
  const stand = async () => {
    if (commissioning) {
      if (!window.confirm(HOLD_CONFIRM)) return;
      setBusy(true); setMsg(null);
      const r = await link.cmd('imu.op', { op: 'hold' }, 25000);
      setBusy(false);
      setMsg(r.ok ? { ok: true, text: 'O robô está em pé. Segure-o; agora você pode calibrar a orientação de montagem ou fazer a calibração em pé. Ao terminar, clique em “Desativar” ou em “Liberar” no topo.' }
        : { ok: false, text: r.reason || r.error || 'Não foi possível levantar o robô.' });
      return;
    }
    if (typeof st?.tilt_deg === 'number' && st.tilt_deg > 30
      && !window.confirm(`O robô está deitado (inclinação de ${Math.round(st.tilt_deg)}°). As pernas podem se mover bruscamente ao levantar. Você está segurando-o com firmeza?`)) return;
    setBusy(true); setMsg(null);
    const r = await link.cmd('pad.op', { op: 'stand' }, 10000);
    setBusy(false);
    setMsg(r.ok ? { ok: true, text: 'Comando para levantar enviado. Segure o robô e aguarde estabilizar antes da calibração em pé.' } : { ok: false, text: r.reason || r.error || 'Não foi possível levantar o robô.' });
  };
  const relax = async () => {
    setMsg(null);
    const r = await link.cmd('relax', {}, 7000);
    setMsg(r.ok ? { ok: true, text: 'Comando para liberar os motores enviado. Segure o MicroDuck.' } : { ok: false, text: r.reason || r.error || 'Falha ao liberar os motores. Use − no controle ou desligue a alimentação.' });
  };
  return html`<section class="board imu-card imu-stance">
    <h3>Postura em pé <span class="sv-small">O robô precisa estar estável para a calibração em pé.</span></h3>
    <div class="imu-actions">
      <button class="btn-dark imu-stand" disabled=${!!standWhy || busy} onClick=${stand}
        title=${standWhy || 'Usa o mesmo comando “Levantar” do cartão de controle.'}>${busy ? 'Aguardando resposta…' : 'Ativar postura em pé'}</button>
      <button class="btn-light imu-relax" disabled=${!open} onClick=${relax}
        title="Usa o comando “Liberar” do topo; libera os 15 servos">Desativar (liberar motores)</button>
      <span class="sv-small imu-stance-now">Estado atual: <b>${now}</b></span>
    </div>
    ${standWhy ? html`<p class="sv-small imu-stance-why">${standWhy}</p>` : null}
    ${imu?.redo?.active ? null : commissioning
      ? html`<p class="sv-small">Também é possível ficar em pé no modo de calibração: “Ativar postura em pé” move e mantém os 15 servos juntos, sem controle de equilíbrio; segure o robô. “Desativar” libera os servos. Depois de estabilizar, faça a calibração em pé abaixo.</p>`
      : standWhy ? null
        : html`<p class="sv-small">“Ativar postura em pé” usa o comando “Levantar” do cartão de controle; segure o robô. “Desativar” libera os motores, então continue segurando-o.</p>`}
    ${msg ? html`<div class=${'banner ' + (msg.ok ? 'warn' : 'bad')} role="status"><span>${msg.text}</span></div>` : null}
  </section>`;
}

/** Mensagem principal e instrução complementar durante a coleta. */
function collectWords(W) {
  if (W.paused) return [W.paused, ''];
  if (!W.done.still) {
    return [W.moved ? 'O robô se moveu; reiniciando a contagem.' : 'Coloque em uma mesa plana, solte e não toque no robô.',
      `Os 3 segundos em pé e parado definem a referência · faltam ${Math.max(0, RULES.still_s * (1 - W.progress)).toFixed(1)} s`];
  }
  const next = nextTodo(W);
  const n = next ? STEP[next] : null;
  const tip = n ? `Segure o tronco pelas laterais e levante um pouco (pés a 2–3 cm da mesa). Nivele por meio segundo, incline cerca de 15° para ${n.short} (${n.how}) e mantenha por 1 s. A ordem é livre.` : '';
  if (W.over) return ['Inclinação excessiva; volte um pouco.', tip];
  if (W.repeat) return [`${STEP[W.repeat].cn} já foi registrada.`, `Volte ao nivelamento e faça ${next ? STEP[next].cn : 'a próxima etapa'}.`];
  if (W.needLevel) return ['Nivele e aguarde um instante.', 'A referência não foi registrada; nivele por meio segundo antes de cada inclinação.'];
  if (W.inZone && W.cand) return [`${STEP[W.cand].cn}: mantenha parado…`, 'Mais um instante e a etapa será registrada.'];
  return [n ? `Próxima etapa: ${n.cn}` : 'Todas as etapas concluídas.', tip];
}

function CollectCard({ st, imu, live, W, act, muted, setMuted }) {
  const block = blockReason(st, imu, live);
  const ph = W.phase;
  const guardErr = st?.guard?.max_joint_error_deg;
  const res = W.result;
  const mute = html`<label class="imu-mute" title="Toca um sinal ao concluir cada direção"><input type="checkbox" checked=${muted}
    onChange=${(e) => setMuted(e.target.checked)} /> Silenciar</label>`;
  let button;
  if (ph === 'collect') button = html`<button class="imu-big rec" onClick=${act.end}><span class="rec-dot"></span>Coletando… (clique para encerrar)</button>`;
  else if (ph === 'solving') button = html`<button class="imu-big" disabled>Calculando…</button>`;
  else if (ph === 'short') button = html`<button class="imu-big" onClick=${act.resume}>Continuar coleta</button>`;
  else button = html`<button class="imu-big" disabled=${!!block} onClick=${act.start}>${ph === 'idle' ? 'Iniciar coleta' : 'Recomeçar coleta'}</button>`;
  const [say, sub] = ph === 'collect' ? collectWords(W) : ['', ''];
  return html`<section class="board imu-card imu-collect">
    <h3>Calibração em pé <span class="sv-small">Cerca de 1 minuto · use as duas mãos</span>${mute}</h3>
    ${ph === 'idle' ? html`<ol class="imu-howto">
      <li>Coloque o robô em pé (clique em “Ativar postura em pé” ou pressione + no controle; não inicie a marcha) e clique em “Iniciar coleta”.</li>
      <li>Coloque-o sobre uma mesa plana e <b>não toque por 3 segundos</b>.</li>
      <li>Fique atrás do robô, segurando o tronco pelas laterais. <b>Incline uma vez para frente, para trás, para a esquerda e para a direita</b>:
        nivele por meio segundo antes de cada inclinação, depois incline cerca de 15° e mantenha por 1 s. A ordem é livre; a seta 3D mostra a direção.</li>
      <li>O ponto acende e um sinal toca ao concluir cada direção; quando os quatro acenderem, a coleta termina e o cálculo começa automaticamente.</li>
    </ol>` : null}
    ${ph === 'collect' || ph === 'solving' || ph === 'short' ? html`<div class="imu-live">
      <${DirPad} W=${W} />
      <div class="imu-live-txt">
        ${ph === 'collect' ? html`<p class="imu-say"><b>${say}</b><br /><span class="sv-small">${sub}</span></p>
          ${!W.done.still ? html`<div class="imu-bar" aria-label="Progresso do repouso"><span style=${{ width: `${Math.round(W.progress * 100)}%` }}></span></div>`
            : html`<p class="imu-tilt num"><b>${fmt(W.live?.t)}°</b><span>em relação ao nivelamento</span></p>`}`
        : ph === 'solving' ? html`<p class="imu-say"><b>Coleta concluída; calculando…</b></p>`
          : html`<p class="imu-say"><b>Faltam: ${names(W.missing)}</b><br />
            <span class="sv-small">As etapas concluídas foram mantidas. Clique em “Continuar coleta” para completar ${names(W.missing)} ou em “Recomeçar” para iniciar tudo novamente.</span></p>`}
      </div>
    </div>` : null}
    ${ph === 'error' ? html`<div class="banner bad" role="alert"><b>Falha no cálculo</b><span class="more">${W.error}</span></div>` : null}
    ${ph === 'done' && res && !res.ok ? html`<p class="sv-warn">A calibração falhou. Confira o motivo e as etapas a refazer em “Resultado”, abaixo.</p>` : null}
    ${block && ph !== 'solving' ? html`<p class="sv-warn">${block}</p>`
      : ph === 'idle' && guardErr != null && guardErr > 5 ? html`<p class="sv-warn">As pernas estão a ${fmt(guardErr)}° de HOME. A postura e a compensação ficarão imprecisas. Calibre primeiro a posição zero dos servos.</p>` : null}
    <div class="imu-actions">${button}
      ${ph === 'short' || ph === 'collect' ? html`<button class="btn-light" onClick=${act.start} disabled=${!!block && ph !== 'collect'}>Recomeçar</button>` : null}</div>
  </section>`;
}

const GRADE = { good: ['Boa', 'ok'], ok: ['Utilizável', 'warn'], coarse: ['Inicial', 'warn'] };

function ResultCard({ res, imu, link, onRedo }) {
  const [checks, setChecks] = useState({});
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState(null);
  useEffect(() => { setChecks({}); setOut(null); }, [res]);
  if (!res) return null;
  const P = res.parts || {}, Q = res.quality || {}, R = res.rules || {};
  const confirms = res.confirm || [];
  const allChecked = confirms.every((_, i) => checks[i]);
  const [gw, gk] = GRADE[Q.grade] || ['—', ''];
  const redo = (res.redo || []).filter((k) => STEP[k]);
  const save = () => {
    // O resultado da calibração em pé já está em imu-pending.json; a gravação no programa principal ocorre na etapa 3.
    setOut({ ok: true, text: 'A orientação foi registrada no Studio. Vá à etapa 3 da lista inicial e clique em “Gravar no programa principal”.' });
    location.hash = '#/';
    setTimeout(() => document.querySelector('[data-step="commit"]')?.scrollIntoView({ block: 'center' }), 300);
  };
  const detail = html`<table class="imu-table num">
      <thead><tr><th>Etapa</th><th class="r">Inclinação</th><th class="r">Desvio</th><th class="r">Oscilação</th><th></th></tr></thead>
      <tbody>${STEPS.map((k) => { const s = (res.steps || {})[k] || {}; return html`<tr class=${s.ok === false ? 'bad' : ''}
        title=${s.ref ? `Referência: ${s.ref}${s.ref_offset_deg != null ? ` (diferença do repouso na mesa: ${fmt(s.ref_offset_deg)}°)` : ''}` : ''}>
        <td>${STEP[k].cn}</td><td class="r">${k === 'still' ? '—' : `${fmt(s.tilt_deg, 0)}°`}</td>
        <td class="r">${s.skew_deg != null ? `${fmt(s.skew_deg, 0)}°` : '—'}</td><td class="r">${s.spread_deg != null ? `${fmt(s.spread_deg)}°` : '—'}</td>
        <td>${s.ok ? '✓' : s.msg || (s.ok === false ? '×' : '')}</td></tr>`; })}</tbody>
    </table>
    ${res.ok && Q.grade !== 'coarse' ? html`<p class="sv-small">Verificação: diferença entre inclinações frontal/traseira ${fmt(Q.fb_pair_deg)}°, lateral ${fmt(Q.lr_pair_deg)}° e entre os eixos ${fmt(Q.cross_deg)}°.
      Maior desvio: ${fmt(Q.max_skew_deg)}° (quanto menor, melhor; “Boa” exige desvio ≤${R.good_skew_deg ?? 10}° por etapa e diferença ≤${R.good_cross_deg ?? 6}° entre pares;
      desvio >${R.skew_max_deg ?? 20}° ou diferença >${R.cross_max_deg ?? 12}° é reprovado).</p>` : null}
    ${res.standard ? html`<p class="sv-small">Orientação calculada: ${res.standard.text}${res.standard.off_deg > 0.5 ? ` (diferença adicional de ${fmt(res.standard.off_deg)}°)` : ''}</p>` : null}
    ${res.mount ? html`<details class="imu-details"><summary>Nova orientação de montagem (quatérnio w, x, y, z)</summary><code class="num">${res.mount.map((x) => fmt(x, 6)).join(', ')}</code></details>` : null}`;
  return html`<section class="board imu-card">
    <h3>Resultado ${res.ok ? html`<span class=${'imu-grade ' + gk}>${gw}</span>` : html`<span class="imu-grade bad">Reprovado</span>`}</h3>
    ${!res.ok ? html`<p class="sv-warn">${res.reason}</p>
      ${redo.length ? html`<div class="imu-actions"><button class="btn-dark" onClick=${() => onRedo(redo)}>Refazer ${names(redo)}</button>
        <span class="sv-small">As outras etapas foram mantidas; somente ${redo.length > 1 ? 'estas etapas' : 'esta etapa'} serão repetidas.</span></div>` : null}` : html`
      <div class="imu-parts num">
        <div><span>Frente / trás</span><b>${sgn(P.pitch_deg)}°</b><small>+ = leitura inclinada para frente em pé</small></div>
        <div><span>Esquerda / direita</span><b>${sgn(P.roll_deg)}°</b><small>+ = inclinação para a esquerda</small></div>
        <div><span>Orientação</span><b>${sgn(P.yaw_deg)}°</b><small>Rotação no eixo vertical; não é visível em pé</small></div>
        <div><span>Total</span><b>${fmt(P.total_deg)}°</b><small>Em relação à orientação atual</small></div>
      </div>`}
    ${res.check ? html`<p class=${res.check.ok ? 'sv-small imu-check' : 'sv-warn imu-check'}>${res.check.ok
      ? `✓ Diferença de ${fmt(res.check.diff_deg)}° em relação à orientação usada pelo programa principal; inclinação em pé de ${fmt(res.check.tilt_deg)}°: ${res.check.recorded ? 'verificação registrada (etapa 2 da lista inicial)' : 'dentro do limite, mas não registrada (consulte os registros)'}`
      : `A verificação não foi registrada: ${res.check.why}`}</p>` : null}
    ${(res.notes || []).map((n) => html`<p class="sv-small">· ${n}</p>`)}
    ${res.ok ? html`<details class="imu-details"><summary>Dados detalhados</summary>${detail}</details>` : detail}
    ${confirms.map((c, i) => html`<label class="imu-confirm"><input type="checkbox" checked=${!!checks[i]} onChange=${(e) => setChecks({ ...checks, [i]: e.target.checked })} /> ${c}</label>`)}
    ${res.ok ? html`<div class="imu-save">
      <button class="btn-dark" disabled=${!res.mount} onClick=${save}>Ir para a etapa 3 da lista inicial</button>
      <span class="sv-small">Esta etapa apenas registra a orientação; “Gravar no programa principal”, na etapa 3, reinicia o programa e ativa o modo de movimento.</span>
    </div>` : null}
    ${!res.mount && res.ok ? html`<p class="sv-warn">Não foi possível calcular a nova orientação; sem a orientação atual, não é possível gravar.</p>` : null}
    ${out ? html`<div class=${'banner ' + (out.ok ? 'warn' : 'bad')} role="status"><b>${out.ok ? 'Registrado' : 'Falha ao registrar'}</b><span class="more">${out.text}</span></div>` : null}
  </section>`;
}

// O resultado da calibração em pé é salvo no Studio (imu-pending.json); a gravação no programa principal ocorre na etapa 3 da lista inicial.

// ---------------- Orientação não confirmada ou robô sem conseguir ficar em pé: calibração inicial ----------------

function CoarseCard({ st, imu, link, live }) {
  const [opened, setOpened] = useState(false);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const mode = st?.mode || imu?.mode;
  const redo = imu?.redo || {};
  const context = imuContext(mode, imu);
  useEffect(() => { setOpened(false); setMsg(null); }, [context]);
  const open = link.status === 'open' && live !== false;
  const commissioning = mode === 'commissioning';
  const verified = imu?.mount?.verified === true;
  const working = !!(imu?.job && !imu.job.done && !imu.job.failed);
  const canCollect = commissioning && !imu?.profile_error && (!redo.active || ['commissioning', 'finish_failed'].includes(redo.phase));
  const showSteps = canCollect && (!verified || opened || redo.active);
  const startWhy = !open ? 'MicroDuck desconectado; aguardando reconexão.' : imu?.profile_error ? imu.profile_error : working ? 'A operação anterior ainda não terminou.'
    : commissioning ? null : !redo.can_start ? redo.reason || 'Não é possível voltar ao modo de calibração agora. Libere os motores e aguarde novas leituras.' : null;
  const run = async (op) => {
    setBusy(true); setMsg(null);
    const r = await link.cmd('imu.op', { op, confirmed: true }, 90000);
    setBusy(false);
    setMsg({ ok: r.ok, text: r.ok ? r.data?.note || (op === 'redo-start'
      ? 'Modo de calibração retomado. Mantenha os motores sem força, segure o MicroDuck e inicie a coleta.' : 'Cancelado; a orientação e o modo anteriores foram restaurados.')
      : r.reason || r.error || 'Operação incompleta. Confira o estado atual e tente novamente.' });
  };
  const start = async () => {
    if (startWhy || busy) return;
    if (commissioning) { setMsg(null); setOpened(true); }
    else await run('redo-start');
  };
  return html`<section class="board imu-card imu-coarse">
    <h3>Orientação de montagem da IMU <span class="sv-small">${redo.active ? 'Recalibração incompleta' : verified ? 'Salva; pode ser validada novamente' : 'Calibração inicial'}</span></h3>
    <p class="sv-small">Colete o repouso e a inclinação frontal, calcule a orientação de montagem (quatérnio) e solicite a validação do programa principal. Repita se a montagem mudou ou a calibração anterior ficou incorreta.</p>
    ${imu?.mount_protocol_mismatch ? html`<p class="sv-warn">O protocolo do barramento não corresponde à orientação salva. Recalibre; a nova orientação só será confirmada após a validação do programa principal.</p>` : null}
    ${redo.active ? html`<p class="sv-warn">${canCollect
      ? 'A recalibração ainda não terminou. Segure o MicroDuck com os motores sem força. Após a validação, o modo anterior será restaurado; você também pode cancelar e restaurar os parâmetros anteriores.'
      : 'A sessão de calibração está mudando ou sendo restaurada. Aguarde a operação atual; se a restauração falhar, cancele para recuperar os parâmetros anteriores.'}</p>
      <div class="imu-actions"><${TwoStep} label="Cancelar e restaurar parâmetros" ask="Segure o MicroDuck. Restaurar a orientação e o modo anteriores?"
        disabled=${!open || busy || working}
        onConfirm=${() => run('redo-cancel')} busyLabel="Restaurando…" /></div>` : null}
    ${!showSteps && !redo.active ? html`<div class="imu-actions"><${TwoStep}
      label="Recalibrar orientação" ask=${commissioning ? 'Segure o MicroDuck. Iniciar uma nova coleta?' : 'Segure o MicroDuck com os motores sem força. Reiniciar no modo de calibração?'}
      cls="btn-dark" disabled=${!!startWhy || busy} title=${startWhy} onConfirm=${start} busyLabel="Entrando no modo de calibração…" /></div>
      <p class="sv-small">${commissioning
        ? 'Segure o robô. Você pode mantê-lo sem força ou ativar a postura em pé e aguardar estabilizar antes de coletar novamente.'
        : 'Antes de recalibrar, clique em “Desativar (liberar motores)” e segure o robô. O programa principal reinicia ao entrar e ao concluir; a orientação original da IMU é copiada para backup.'} A posição zero, a direção e os limites dos servos são preservados; a nova orientação só será adotada após validação.</p>
      ${startWhy ? html`<p class="sv-warn">${startWhy}</p>` : null}` : null}
    ${showSteps ? html`<${CoarseSteps} key=${context} link=${link} disabled=${!open || busy || working} unloadedOnly=${!!redo.active}
      onBegin=${() => setOpened(true)} onDone=${(text) => setMsg({ ok: true, text })} />` : null}
    ${msg ? html`<div class=${'banner ' + (msg.ok ? 'warn' : 'bad')} role="status"><span>${msg.text}</span></div>` : null}
  </section>`;
}

function CoarseSteps({ link, disabled, unloadedOnly, onBegin, onDone }) {
  const [step, setStep] = useState('idle');       // idle / still / fwd / confirm / verifying / done / failed
  const [still, setStill] = useState(null);
  const [res, setRes] = useState(null);
  const [checks, setChecks] = useState({});
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const grab = async (phase, seconds) => {
    if (disabled || busy) return null;
    onBegin();
    setBusy(true); setOut(null);
    const r = await link.cmd('imu.op', { op: 'coarse-capture', phase, seconds }, 15000);
    if (!alive.current) return null;
    setBusy(false);
    if (!r.ok) { setOut({ ok: false, text: r.reason || r.error || 'Não foi possível coletar as leituras.' }); return null; }
    return r.data || {};
  };
  const takeStill = async () => {
    const d = await grab('still', 3);
    if (!d) return;
    setStill(d); setStep('fwd');
    setOut({ ok: true, text: `${d.n} leituras de repouso coletadas. Incline o tronco para frente de 15° a 30°, mantenha parado e clique na próxima etapa.` });
  };
  const takeFwd = async () => {
    const d = await grab('fwd', 3);
    if (!d) return;
    const samples = [...((still && still.samples) || []), ...(d.samples || [])];
    setBusy(true);
    const r = await link.cmd('imu.op', { op: 'solve', mode: 'coarse', frame: 'body', samples }, 20000);
    if (!alive.current) return;
    setBusy(false);
    if (!r.ok || !r.data || r.data.ok !== true) {
      setStep('failed');
      setOut({ ok: false, text: r.reason || (r.data && r.data.reason) || r.error || 'Não foi possível calcular a orientação.' });
      return;
    }
    setRes(r.data); setStep('confirm');
    setOut({ ok: true, text: 'Orientação calculada. Compare com a montagem real do módulo, confirme as opções e solicite a validação do programa principal.' });
  };
  const reset = () => { setStep('idle'); setStill(null); setRes(null); setChecks({}); setOut(null); };
  const verify = async () => {
    if (disabled || busy || !res?.mount) return;
    setBusy(true); setStep('verifying'); setOut(null);
    const r = await link.cmd('imu.op', { op: 'verify', confirmed: true, mount_wxyz: res.mount }, 90000);
    if (!alive.current) return;
    if (r.ok) onDone(r.data?.note || 'Validação do programa principal aprovada; orientação de montagem salva.');
    setBusy(false);
    if (r.ok) { setStep('done'); setOut({ ok: true, text: (r.data && r.data.note) || 'Validação do programa principal aprovada; orientação gravada no arquivo de calibração.' }); }
    else { setStep('failed'); setOut({ ok: false, text: r.reason || r.error || 'O programa principal reprovou a validação.' }); }
  };
  const confirms = (res && res.confirm) || [];
  const allChecked = confirms.every((_, i) => checks[i]);
  const nowStep = step === 'idle' ? 'still' : step;
  return html`<div class="imu-coarse-steps">
    <p class="sv-small">${unloadedOnly
      ? 'Esta sessão de recalibração restaurará o modo anterior. Mantenha os motores sem força e segure o MicroDuck.'
      : 'A calibração inicial ocorre no modo de calibração. Você pode ativar a postura em pé e segurar o robô após estabilizar ou mantê-lo sem força enquanto o segura. A postura em pé trava as articulações, mas não controla o equilíbrio; segure-o continuamente.'}
      Nivele o robô inteiro e colete por 3 s; depois incline o tronco para frente de 15° a 30°, mantenha parado e colete por 3 s. O computador calcula a orientação e o programa principal a valida.</p>
    ${nowStep === 'still' ? html`<div class="imu-coarse-step">
      <p class="imu-say"><b>① Segure o robô, nivele e não se mova</b></p>
      <p class="sv-small">Segure o tronco com as duas mãos, mantenha o robô em pé com os pés para baixo e fique parado. Se ativou a postura em pé, aguarde estabilizar. A tela ainda usa a orientação antiga; guie-se pela posição física.</p>
      <button class="btn-dark" disabled=${busy || disabled} onClick=${takeStill}>${busy ? 'Coletando…' : 'Coletar repouso (3 s)'}</button>
    </div>` : null}
    ${nowStep === 'fwd' ? html`<div class="imu-coarse-step">
      <p class="imu-say"><b>② Incline para frente de 15° a 30° e mantenha parado</b></p>
      <p class="sv-small">Segure o tronco inteiro e incline-o para frente, abaixando o lado da cabeça até 15°–30°. Fique parado por 3 s. Não mova apenas a cabeça nem incline para os lados.</p>
      <div class="imu-actions">
        <button class="btn-dark" disabled=${busy || disabled} onClick=${takeFwd}>${busy ? 'Coletando / calculando…' : 'Coletar inclinação frontal (3 s)'}</button>
        <button class="btn-light" disabled=${busy || disabled} onClick=${takeStill}>Coletar repouso novamente</button>
      </div>
    </div>` : null}
    ${nowStep === 'confirm' && res ? html`<div class="imu-coarse-step">
      <p class="sv-small">Resultado da calibração inicial: ${res.standard ? `${res.standard.text}${res.standard.off_deg > 0.5 ? ` (diferença adicional de ${fmt(res.standard.off_deg)}°)` : ''}` : 'orientação calculada'}.
        Esta etapa coleta somente repouso e inclinação frontal; as direções laterais ainda não foram verificadas. Depois, faça a calibração completa em pé abaixo.</p>
      ${(res.notes || []).map((n) => html`<p class="sv-small">· ${n}</p>`)}
      ${confirms.map((c, i) => html`<label class="imu-confirm"><input type="checkbox" checked=${!!checks[i]}
        onChange=${(e) => setChecks({ ...checks, [i]: e.target.checked })} /> ${c}</label>`)}
      <div class="imu-actions">
        <button class="btn-dark" disabled=${busy || disabled || !res.mount || !allChecked} onClick=${verify}>Solicitar validação do programa principal</button>
        <button class="btn-light" disabled=${busy} onClick=${reset}>Recomeçar</button>
      </div>
      <p class="sv-small"><b>Antes de solicitar a validação, nivele o robô e mantenha-o parado.</b> Depois, siga as instruções para inclinar o tronco para frente de 15° a 30° em até 20 s.</p>
    </div>` : null}
    ${nowStep === 'verifying' ? html`<div class="imu-coarse-step">
      <p class="imu-say"><b>Siga as instruções do programa principal e incline para frente de 15° a 30° em até 20 s</b></p>
      <p class="sv-small">Continue segurando o robô. O programa principal verifica primeiro o nivelamento e depois a inclinação frontal. Após a validação, a sessão de recalibração ainda precisa restaurar o modo anterior.</p>
    </div>` : null}
    ${nowStep === 'done' ? html`<p class="sv-small">Validação aprovada; orientação gravada no arquivo de calibração. Faça a calibração completa em pé abaixo para refinar o resultado.</p>` : null}
    ${nowStep === 'failed' ? html`<div class="imu-actions">
      <button class="btn-dark" onClick=${reset}>Recomeçar</button>
      <span class="sv-small">Resolva o motivo informado abaixo. A sessão de recalibração pode ser cancelada para restaurar os parâmetros anteriores.</span>
    </div>` : null}
    ${out ? html`<div class=${'banner ' + (out.ok ? 'warn' : 'bad')} role="status"><span>${out.text}</span></div>` : null}
  </div>`;
}

// ---------------- Progresso das operações do backend (calibração inicial, gravação e seleção do chip) ----------------
// imu.job = { kind: 'coarse'|'save'|'set_chip'|'detect', title, msg, tilt_deg?, target_deg?, hold?, failed?, done? }
// tilt_deg é enviado em destaque porque as etapas com o robô apoiado verificam nivelamento (≤5°) e inclinação frontal (15°–30%).

function JobBanner({ job }) {
  if (!job) return null;
  const kind = job.failed ? 'bad' : 'warn';
  return html`<div class=${'banner imu-job ' + kind} role="status" aria-live="polite">
    <b>${job.title || 'Em andamento'}</b><span class="more">${job.msg || ''}</span>
    ${job.tilt_deg != null ? html`<span class="imu-job-tilt num">${fmt(job.tilt_deg)}°${job.target_deg ? html`<small> / ${job.target_deg}</small>` : null}</span>` : null}
    ${job.hold != null && !job.done ? html`<span class="imu-bar small"><span style=${{ width: `${Math.round(Math.min(1, job.hold) * 100)}%` }}></span></span>` : null}
  </div>`;
}

// Interface auxiliar para fornecer leituras e inspecionar a coleta sem abrir o navegador.
export const _test = { RULES, STEPS, TILTS, feed, freshWizard, startCollect, endCollect, resumeCollect, redoSteps,
  missingSteps, payload, findHold, findRef, spreadP90, tiltOf, qRotate };

// ---------------- Página ----------------

/** live / age usam o mesmo critério do painel (calculado em Main de app.js); sem esses valores, consulta st.joints_age_ms. */
export function ImuPage({ st, imu, link, live, age, pd }) {
  const W = useRef(freshWizard());
  const [, bump] = useState(0);
  const redraw = () => bump((n) => n + 1);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [muted, setMutedState] = useState(loadMute);
  const mutedRef = useRef(muted);
  const setMuted = (v) => { mutedRef.current = v; setMutedState(v); saveMute(v); };
  const context = imuContext(st?.mode || imu?.mode, imu);

  useEffect(() => {
    W.current = freshWizard(); setRes(null); setMsg(null); redraw();
  }, [context]);

  useEffect(() => {
    if (!feed(W.current, st, live)) return;
    for (const e of W.current.events.splice(0)) if (!mutedRef.current) beep(e);
    redraw();
  }, [st, live]);

  // Envia a coleta ao backend; ele lê a orientação anterior de calibration-status.
  const phase = W.current.phase;
  useEffect(() => {
    if (phase !== 'solving') return undefined;
    let dead = false;
    const w = W.current;
    link.cmd('imu.op', { op: 'solve', frame: 'body', mode: 'full', samples: payload(w) }, 15000).then((r) => {
      if (dead || W.current !== w) return;
      if (r.ok && r.data) { w.phase = 'done'; w.result = r.data; setRes(r.data); }
      else { w.phase = 'error'; w.error = r.reason || r.error || 'Não foi possível calcular.'; }
      redraw();
    });
    return () => { dead = true; };
  }, [phase, context]);

  const act = {
    start: () => { audioUnlock(); startCollect(W.current, performance.now() / 1000); setRes(null); redraw(); },
    end: () => { endCollect(W.current); redraw(); },
    resume: () => { audioUnlock(); resumeCollect(W.current); redraw(); },
  };
  const onRedo = (steps) => { audioUnlock(); redoSteps(W.current, steps); setRes(null); redraw(); };

  const run = async (args, what, timeout = 15000) => {
    setBusy(true); setMsg(null);
    const r = await link.cmd('imu.op', args, timeout);
    setBusy(false);
    setMsg(r.ok ? { ok: true, text: `${what}: ${r.data?.note || 'Concluído.'}` } : { ok: false, text: `${what}: falha — ${r.reason || r.error || 'motivo não informado'}` });
    return r;
  };
  const w = W.current;
  const S = statusOf(st, imu, live);
  const F = freshText(st, live, age);
  const arrow = w.phase === 'collect' && w.done.still ? nextTodo(w) : null;
  const cue = w.phase === 'collect' ? (!w.done.still ? 'Repouso por 3 s: não toque no robô.' : arrow ? `Próxima etapa: ${STEP[arrow].cn} (ordem livre)` : null) : null;
  return html`<div class="imu-page">
    <header class="sv-head">
      <h1>IMU</h1>
      <span class="sv-metrics num">
        <span>Orientação <b>${S.word}</b></span>
        <span>Inclinação <b>${fmt(st?.tilt_deg)}°</b>${F.live ? '' : ` (${F.text})`}</span>
        <span>Chip <b>${chipLabel(imu)}</b></span>
      </span>
    </header>
    <div class="sv-sub">A IMU informa à política para que lado o corpo está inclinado. A montagem varia entre robôs e alguns graus de desalinhamento podem passar despercebidos em pé, mas fazer o MicroDuck avançar ao caminhar. Por isso, calibre a orientação de montagem.</div>
    <${JobBanner} job=${imu?.job} />
    ${msg ? html`<div class=${'banner ' + (msg.ok ? 'warn' : 'bad')} role="status"><span>${msg.text}</span>
      <a href="#" onClick=${(e) => { e.preventDefault(); setMsg(null); }}>Entendi</a></div>` : null}
    <div class="imu-grid">
      <${ImuStage} st=${st} stale=${!F.live} corr=${res?.ok ? res.correction : null} parts=${res?.parts}
        collecting=${w.phase === 'collect'} arrow=${arrow} cue=${cue} />
      <div class="imu-side">
        <${StatusCard} st=${st} imu=${imu} live=${live} age=${age} />
        <${CoarseCard} st=${st} imu=${imu} link=${link} live=${live} />
        <${StanceCard} st=${st} imu=${imu} pd=${pd} link=${link} live=${live} />
        <${CollectCard} st=${st} imu=${imu} live=${live} W=${w} act=${act} muted=${muted} setMuted=${setMuted} />
        <${ResultCard} res=${w.phase === 'done' ? res || w.result : null} imu=${imu} link=${link} onRedo=${onRedo} />
        <${ChipCard} imu=${imu} link=${link} live=${live} />
      </div>
    </div>
  </div>`;
}
