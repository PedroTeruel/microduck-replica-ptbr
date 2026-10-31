// Cartão “Bateria” da barra de indicadores da Visão geral (battery-plan.md v2 §5): os valores vêm do estimador do backend (studio/battery.py, st.battery); aqui só são exibidos.
// Ao abrir o cartão, são exibidos os detalhes do cálculo, linha por linha. Ao ultrapassar o limite crítico ou quando a tensão estiver muito baixa, um bipe curto é emitido (somente no navegador;
// compartilha o controle de silêncio da página da IMU, studio.imu.mute). É apenas um aviso: esta página não contém comandos que movimentem o robô.
import { html, useState, useEffect, useLayoutEffect, useRef } from './vendor/preact-htm.module.js';

const MUTE_KEY = 'studio.imu.mute';          // compartilhado com a página da IMU (web/imu.js)
export function loadMute() { try { return localStorage.getItem(MUTE_KEY) === '1'; } catch { return false; } }
export function saveMute(v) { try { localStorage.setItem(MUTE_KEY, v ? '1' : '0'); } catch { /* modo privado */ } }

// O navegador exige uma interação do usuário antes de reproduzir áudio; inicialize o som no primeiro clique.
let actx = null;
function unlock() {
  try {
    const C = window.AudioContext || window.webkitAudioContext;
    if (!C) return;
    actx = actx || new C();
    if (actx.state === 'suspended') actx.resume();
  } catch { actx = null; }
}
document.addEventListener('pointerdown', unlock, { capture: true, passive: true });
document.addEventListener('keydown', unlock, { capture: true });

function beep() {
  if (!actx || loadMute()) return;
  try {
    const t = actx.currentTime + 0.01;
    for (const [f, dt] of [[660, 0], [440, 0.16]]) {          // Dois bipes descendentes, distintos do sinal ascendente de conclusão da calibração da IMU.
      const o = actx.createOscillator(), g = actx.createGain();
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t + dt);
      g.gain.exponentialRampToValueAtTime(0.12, t + dt + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dt + 0.14);
      o.connect(g).connect(actx.destination);
      o.start(t + dt);
      o.stop(t + dt + 0.16);
    }
  } catch { /* ignore se o áudio não puder ser reproduzido */ }
}

// Os estilos ficam neste arquivo (sem alterar styles.css).
const CSS = `
.bat-cell { position: relative; }
.bat-hit { all: unset; box-sizing: border-box; display: flex; flex-direction: column; gap: 2px; cursor: pointer; border-radius: 8px; }
.bat-hit:focus-visible { outline: 2px solid var(--blue); outline-offset: 4px; }
.bat-cell .bat-row { display: flex; align-items: baseline; gap: 4px; }
.bat-cell .bat-bar { position: relative; width: 120px; height: 4px; margin-left: 14px; border-radius: 2px; background: #E5E5EA; align-self: center; }
.bat-cell .bat-bar > i { position: absolute; left: 0; top: 0; height: 4px; border-radius: 2px; }
.bat-cell .bat-bar > b { position: absolute; top: -3px; width: 1px; height: 10px; background: #8E8E93; }
.bat-cell .small { display: flex; align-items: center; gap: 6px; }
.bat-cell.warn .big, .bat-cell.warn .small { color: var(--warn); }
.bat-cell.bad .big, .bat-cell.bad .small { color: var(--danger); }
.bat-pop { position: absolute; z-index: 30; left: 12px; top: calc(100% - 6px); width: min(440px, calc(100vw - 40px));
  padding: 12px 16px 14px; font-size: 13px; line-height: 1.65; color: var(--text); box-shadow: 0 8px 28px rgba(0,0,0,.14), inset 0 0 0 1px var(--board-edge); }
.bat-pop h3 { margin: 0 0 6px; font-size: 14px; font-weight: 600; }
.bat-pop ul { margin: 0; padding-left: 18px; }
.bat-pop li + li { margin-top: 2px; }
.bat-pop .bat-foot { margin-top: 8px; display: flex; justify-content: space-between; gap: 12px; }
@media (max-width: 720px) { .bat-pop { left: 0; } }
`;
if (!document.getElementById('bat-css')) {
  const s = document.createElement('style');
  s.id = 'bat-css';
  s.textContent = CSS;
  document.head.appendChild(s);
}

const f2 = (v) => (typeof v === 'number' && isFinite(v) ? v.toFixed(2) : '—');

/** Linha menor: tensão e método de estimativa. */
function smallLine(b) {
  if (!b || !b.mode) return '—';
  if (b.mode === 'no_data') return 'Não foi possível ler a tensão';
  if (b.mode === 'estimating') return `Estimando${typeof b.estimating_left_s === 'number' ? ` por ${b.estimating_left_s} s` : ''}`;
  if (b.mode === 'bench') return b.why || 'Fonte de bancada';         // A tensão já aparece em destaque.
  return `${f2(b.volts)} V · ${b.why || ''}`;
}

/** Ao ultrapassar o limite crítico ou quando a tensão estiver muito baixa, emite um bipe na transição para alerta. */
function useBeep(b) {
  const prev = useRef(null);
  const on = { red: !!b?.red, low: !!b?.low_volt };
  useEffect(() => {
    const p = prev.current;
    if (p && ((on.red && !p.red) || (on.low && !p.low))) beep();
    prev.current = on;
  }, [on.red, on.low]);
}

export function BatteryCell({ b }) {
  b = b || {};
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useBeep(b);
  // Ative Escape e o fechamento ao clicar fora assim que o painel abrir, usando useLayoutEffect. useEffect esperaria o próximo quadro (até 100 ms),
  // Para que Escape funcione imediatamente ao abrir, inclusive nos testes ponta a ponta.
  useLayoutEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === 'Escape' || e.keyCode === 27) setOpen(false); };
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('pointerdown', away); document.removeEventListener('keydown', esc); };
  }, [open]);

  const bench = b.mode === 'bench';
  const pct = typeof b.pct === 'number' ? Math.round(b.pct) : null;
  const kind = b.level === 'error' ? 'bad' : b.level === 'warn' ? 'warn' : '';
  const color = kind === 'bad' ? 'var(--danger)' : kind === 'warn' ? 'var(--warn)' : 'var(--text)';
  const big = bench ? html`<span class="big">${f2(b.volts)}</span><span class="unit">V</span>`
    : html`<span class="big">${pct ?? '—'}</span><span class="unit">%</span>`;
  const bar = !bench && pct !== null ? html`<span class="bat-bar" aria-hidden="true">
      <i style=${{ width: `${Math.max(0, Math.min(100, pct))}%`, background: color }}></i>
      ${typeof b.warn_pct === 'number' ? html`<b style=${{ left: `${b.warn_pct}%` }} title="Limite de alerta"></b>` : null}
      ${typeof b.red_pct === 'number' ? html`<b style=${{ left: `${b.red_pct}%`, background: 'var(--danger)' }} title="Limite crítico"></b>` : null}
    </span>` : null;
  const title = bench ? 'Tensão da fonte' : 'Como a carga é calculada';
  return html`<div class=${'bat-cell' + (kind ? ` ${kind}` : '')} ref=${ref} data-mode=${b.mode || ''}>
    <button class="bat-hit" type="button" aria-expanded=${open ? 'true' : 'false'} aria-label=${`Bateria: ${bench ? `${f2(b.volts)} V` : pct ?? '—'}${bench ? '' : '%'}; abra para ver como é calculada`}
      onClick=${() => setOpen((o) => !o)}>
      <span class="label">Bateria</span>
      <span class="num bat-row">${big}${bar}</span>
      <span class="small num">${b.low_volt ? html`<span class="badge bad" aria-hidden="true">×</span>` : null}${smallLine(b)}</span>
    </button>
    ${open ? html`<div class="bat-pop board" role="dialog" aria-label=${title}>
      <h3>${title}</h3>
      <ul>${(b.detail || ['Ainda não há leituras']).map((line) => html`<li>${line}</li>`)}</ul>
      <div class="bat-foot"><a href="#/settings" onClick=${() => setOpen(false)}>Configurações da bateria ›</a>
        <a href="#/logs" onClick=${() => setOpen(false)}>Ver logs</a></div>
    </div>` : null}
  </div>`;
}
