// Seção Bateria das configurações (battery-plan.md v2 §4): tipo de alimentação, faixas de aviso, tensão mínima sob carga, calibração da leitura, alerta sonoro e recomendações de manutenção.
// As opções são salvas no Microduck em state/battery-settings.json, validadas por battery.op e aplicadas imediatamente. Esta seção apenas exibe avisos; não movimenta o robô.
import { html, useState, useEffect } from './vendor/preact-htm.module.js';
import { loadMute, saveMute } from './battery.js';
import { Stepper } from './stepper.js';

const f2 = (v) => (typeof v === 'number' && isFinite(v) ? v.toFixed(2) : '—');
const sign = (v) => (typeof v === 'number' && isFinite(v) ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}` : '—');
const CLS = { rest: 'Servos liberados', light: 'Em pé / sentado', heavy: 'Caminhando / em movimento' };

const CSS = `
.bset { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.bset h2 { margin: 0; font-size: 15px; font-weight: 600; }
.bset .now { font-size: 13px; color: var(--text-2); }
.bset .row { display: grid; grid-template-columns: 120px 1fr; gap: 6px 14px; align-items: center; }
.bset .row > label, .bset .row > .k { font-size: 14px; }
.bset .note { grid-column: 2; font-size: 13px; line-height: 1.55; color: var(--text-2); }
.bset input[type=number] { width: 96px; height: 32px; padding: 0 8px; border: 1px solid #D2D2D7; border-radius: 8px; font: inherit; font-size: 15px; }
.bset .radio { display: flex; flex-wrap: wrap; gap: 4px 18px; }
.bset .radio label { display: flex; align-items: center; gap: 8px; height: 32px; font-size: 14px; }
.bset .btn { height: 34px; padding: 0 16px; border: 0; border-radius: 999px; background: #E5E5EA; font: inherit; font-size: 14px; cursor: pointer; }
.bset .btn.primary { background: var(--blue); color: #FFF; }
.bset .btn:disabled { opacity: .45; cursor: default; }
.bset .msg { font-size: 13px; line-height: 1.55; }
.bset .msg.bad { color: var(--danger); }
.bset .msg.ok { color: var(--ok); }
.bset .tips { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.65; color: var(--text-2); }
.bset .cal { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
@media (max-width: 560px) { .bset .row { grid-template-columns: 1fr; } .bset .note { grid-column: 1; } }
`;
if (!document.getElementById('bset-css')) {
  const s = document.createElement('style');
  s.id = 'bset-css';
  s.textContent = CSS;
  document.head.appendChild(s);
}

export function BatterySettings({ link, st }) {
  const [data, setData] = useState(null);         // Dados do backend: configurações, valores padrão, limites e predefinições.
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);           // {kind, text}
  const [busy, setBusy] = useState(false);
  const [meter, setMeter] = useState('');
  const [cal, setCal] = useState(null);           // Resultado da calibração.
  const [muted, setMuted] = useState(loadMute());

  const load = async () => {
    await link.whenOpen();
    const r = await link.cmd('battery.op', { op: 'get' }, 8000);
    if (r.ok) { setData(r.data); setForm({ ...r.data.settings }); } else setMsg({ kind: 'bad', text: `Não foi possível ler as configurações da bateria: ${r.reason || r.error}` });
  };
  useEffect(() => { load(); }, []);

  if (!form) {
    return html`<div class="board bset" aria-label="Bateria"><h2>Bateria</h2><div class="now">${msg ? msg.text : 'Carregando…'}</div></div>`;
  }
  const s0 = data.settings, rg = data.ranges || {};
  const bench = form.preset === 'bench';
  const dirty = Object.keys(s0).some((k) => s0[k] !== form[k]);
  const b = st?.battery || {};
  const set = (k, v) => { setForm({ ...form, [k]: v }); setMsg(null); };
  const num = (k, step, unit) => html`<${Stepper} value=${form[k]} min=${rg[k]?.[0]} max=${rg[k]?.[1]} step=${step}
    aria-label=${k} unit=${unit} onChange=${(v) => set(k, v)} />`;

  const save = async (values) => {
    setBusy(true);
    const r = await link.cmd('battery.op', { op: 'set', values }, 8000);
    setBusy(false);
    if (r.ok) { setData(r.data); setForm({ ...r.data.settings }); setMsg({ kind: 'ok', text: 'Salvo e aplicado imediatamente.' }); setCal(null); return true; }
    setMsg({ kind: 'bad', text: `Não foi possível salvar: ${r.reason || r.error}` });
    return false;
  };
  const measure = async () => {
    const v = Number(meter);
    setCal(null);
    setMsg(null);
    const r = await link.cmd('battery.op', { op: 'calibrate', measured_v: meter === '' ? null : v }, 8000);
    if (!r.ok) { setCal({ ok: false, reason: r.reason || r.error }); return; }
    setCal(r.data);
  };

  const now = b.mode === 'no_data' ? 'Tensão dos servos indisponível'
    : b.mode === 'estimating' ? 'Estimativa em andamento'
      : `Leitura dos servos: ${f2(b.volts)} V (${CLS[b.cls] || 'estado desconhecido'})${bench || b.mode === 'bench' ? '' : ` · carga aproximada: ${b.pct ?? '—'}%`}`;
  return html`<div class="board bset" aria-label="Bateria">
    <h2>Bateria</h2>
    <div class="now num">${data.presets?.[s0.preset] || s0.preset} · ${s0.preset === 'bench' ? 'exibe somente a tensão' : 'estimativa por tabela genérica'} · calibração ${sign(s0.cal_offset_v)} V　${now}</div>

    <div class="row">
      <span class="k">Tipo</span>
      <div class="radio">
        ${Object.entries(data.presets || {}).map(([k, label]) => html`<label>
          <input type="radio" name="bat-preset" value=${k} checked=${form.preset === k} onChange=${() => set('preset', k)} /> ${label}</label>`)}
      </div>
      <div class="note">${bench
        ? 'Fonte de bancada (fonte ajustável): mostra somente a tensão, sem calcular nem avisar a porcentagem de carga. Ainda avisa se a tensão ficar abaixo do limite sob carga por 30 s (por exemplo, devido ao limite de corrente da fonte ou a cabos finos).'
        : 'A HD-1910 suporta até 8,4 V e deve ser usada somente com bateria 2S. A carga é estimada por uma tabela baseada na tensão dos servos (não há medidor de carga); a margem de erro é de cerca de ±15%. Sem calibração, a estimativa tende a ser conservadora.'}</div>
    </div>

    ${bench ? null : html`
    <div class="row">
      <label>Limite de aviso (amarelo)</label>
      <span>${num('warn_pct', 1, '%')}</span>
      <div class="note">Padrão: ${data.defaults.warn_pct}%. Na tabela, 30% corresponde a uma tensão maior do que os 30% lineares do programa antigo (7,42 V contra 7,08 V), então a faixa amarela aparece antes.</div>
    </div>
    <div class="row">
      <label>Limite crítico (vermelho)</label>
      <span>${num('red_pct', 1, '%')}</span>
      <div class="note">Padrão: ${data.defaults.red_pct}%, pelo menos 5 pontos abaixo do limite de aviso. Atingir este limite apenas exibe um aviso; ainda é possível ficar em pé e caminhar.</div>
    </div>`}
    <div class="row">
      <label>Limite de tensão sob carga</label>
      <span>${num('load_floor_v', 0.1, 'V')}</span>
      <div class="note">Padrão: ${data.defaults.load_floor_v} V (3,45 V por célula). Se a tensão ficar abaixo deste valor por 30 s, será exibido o aviso mais destacado.</div>
    </div>
    <div class="row">
      <label>Calibração da leitura</label>
      <span>${num('cal_offset_v', 0.01, 'V')}</span>
      <div class="note">Diferença entre a tensão medida nos terminais da bateria e a leitura dos servos; padrão: 0. Cada um dos 15 servos pode ter um desvio de ±0,1 V, fazendo a leitura geral ficar um pouco abaixo.</div>
    </div>
    <div class="row">
      <span class="k">Medi a tensão da bateria</span>
      <div class="cal">
        <${Stepper} value=${meter} min=${6} max=${9} step=${0.01} placeholder="7.62" aria-label="Leitura do multímetro" unit="V"
          onChange=${(v) => { setMeter(v); setCal(null); }} />
        <button class="btn" type="button" disabled=${meter === ''} onClick=${measure}>Calcular</button>
      </div>
      <div class="note">Libere os servos e deixe o Microduck parado por pelo menos 30 s. Meça com um multímetro a entrada de bateria do HAT e informe o valor para calcular a calibração da leitura.
        Se estiver usando uma fonte ajustável, também é possível comparar com a tensão exibida nela enquanto o Microduck estiver parado.</div>
      ${cal ? html`<div class=${'note msg ' + (cal.ok ? '' : 'bad')}>${cal.reason}
        ${cal.ok ? html`<div style="margin-top:6px"><button class="btn primary" type="button" disabled=${busy}
          onClick=${() => save({ cal_offset_v: cal.offset })}>${cal.confirm ? 'Confirmar: ' : ''}Aplicar esta calibração (${sign(cal.offset)} V)</button></div>` : null}</div>` : null}
    </div>

    <div class="row">
      <span class="k">Alerta sonoro</span>
      <label style="font-size:14px"><input type="checkbox" checked=${!muted}
        onChange=${(e) => { const m = !e.target.checked; setMuted(m); saveMute(m); }} /> Emitir um som curto ao atingir o limite crítico ou quando a tensão estiver muito baixa</label>
      <div class="note">O som é reproduzido somente enquanto esta página estiver aberta. O controle de silêncio é compartilhado com a página da IMU.</div>
    </div>

    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">
      <button class="btn primary" type="button" disabled=${!dirty || busy} onClick=${() => save(form)}>Salvar</button>
      <button class="btn" type="button" disabled=${busy} onClick=${() => { setForm({ ...data.defaults }); setMsg(null); }}>Restaurar padrões</button>
      ${msg ? html`<span class=${'msg ' + msg.kind}>${msg.text}</span>` : null}
    </div>

    <ul class="tips">
      ${bench ? null : html`<li>Este recurso apenas avisa; o Microduck não para automaticamente quando a bateria acaba. Após usar, desligue a alimentação e desconecte a bateria. Mesmo com os servos liberados, há consumo. Se a bateria for deixada conectada, pode descarregar excessivamente; a placa de proteção, quando presente, corta a alimentação por volta de 5 V, desligando também a placa principal.</li>
      <li>Recarregue a bateria pouco depois de descarregá-la. Para armazenamento prolongado, deixe-a com meia carga (cerca de 7,4–7,6 V).</li>`}
      <li>As configurações ficam salvas no Microduck (${data.path}) e são compartilhadas entre computadores e celulares.</li>
    </ul>
  </div>`;
}
