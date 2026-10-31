// Três cartões somente leitura de “Estado e ajustes” no painel (tuning-plan.md v2 §3) e a seção “Modelos” nas configurações.
// Os dados vêm do cartão de ajustes do backend (studio/tune.py, enviado uma vez por segundo como {t:'tune'}); este arquivo só os exibe. Não é possível editar os ajustes aqui.
// (cap.can_edit permanece false; a edição depende da instalação do assistente root no robô, conforme o plano de ajustes T4/T5.)
// Apenas o formulário de peso nas configurações grava dados, no diretório de estado do próprio Studio (duck-body.json), sem alterar o robô.
import { html, useState, useEffect } from './vendor/preact-htm.module.js';
import { Stepper } from './stepper.js';

const CSS = `
.tune { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; align-items: start; }
/* Em telas largas, o estado ocupa uma linha inteira; ajustes de movimento e modelos ficam em duas colunas. */
@media (min-width: 1100px) { .tune { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } .tune > .tn-run { grid-column: 1 / -1; } }
.tune .card { padding: 14px 16px; }
/* Tabela alinhada em três colunas: nome, valor e descrição. Cada célula desenha sua própria borda superior; o espaçamento usa preenchimento à direita para manter as linhas contínuas. */
.tune .tbl { display: grid; grid-template-columns: max-content max-content minmax(0, 1fr); font-size: 13.5px; line-height: 1.6; }
.tune .tbl > * { padding: 7px 18px 7px 0; border-top: 1px solid var(--line); min-width: 0; }
.tune .tbl > :nth-child(-n+3) { border-top: 0; }
.tune .tbl > :nth-child(3n) { padding-right: 0; }
.tune .tbl .k { color: var(--text); }
.tune .tbl .v { font-weight: 600; font-variant-numeric: tabular-nums; }
.tune .tbl .d { color: var(--text-2); }
.tune .tbl .warn { color: var(--warn); }
.tune .tbl .bad { color: var(--danger); }
.tune .tn-tag { display: inline-block; white-space: nowrap; font-size: 12px; line-height: 18px; padding: 0 8px; border-radius: 999px; font-weight: 600; background: #EFEFF4; color: var(--text-2); }
.tune .tn-tag.on { background: #E7F5EC; color: var(--ok); }
.tune .tn-tag.err { background: #FDEBEC; color: var(--danger); }
.tune .cap { font-size: 13px; color: var(--text-2); margin: 0 0 10px; }
.tune .cap.bad { color: var(--warn); }
.tune h3 { margin: 0 0 10px; font-size: 15px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.tune .summary { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 12px; font-size: 14px; }
.tune .summary .ph { font-weight: 600; }
.tune .summary .ph.warn { color: var(--warn); }
.tune .summary .ph.bad { color: var(--danger); }
.tune .group { margin-top: 12px; }
.tune .group > b { font-size: 13px; color: var(--text-2); font-weight: 600; }
.tune .kv { display: grid; grid-template-columns: 150px 1fr; gap: 3px 12px; font-size: 13.5px; line-height: 1.6; }
.tune .kv > span:first-child { color: var(--text-2); }
.tune .kv .warn { color: var(--warn); }
.tune .kv .bad { color: var(--danger); }
.tune .kv .ok { color: var(--ok); }
.tune .row { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 14px; font-size: 13.5px; line-height: 1.7; padding: 5px 0; border-top: 1px solid var(--line); }
.tune .row:first-child { border-top: 0; }
.tune .row .k { color: var(--text); font-weight: 500; }
.tune .row .d { color: var(--text-2); }
.tune .row .v { font-weight: 500; }
.tune .row .warn { color: var(--warn); }
.tune .row .bad { color: var(--danger); }
.tune .fold { margin-top: 10px; border-top: 1px solid var(--line); padding-top: 10px; }
.tune .fold > button { all: unset; cursor: pointer; font-size: 13px; color: var(--text-2); }
.tune .fold > button:hover { color: var(--text); }
.tune .foot { margin-top: 10px; font-size: 12.5px; color: var(--text-2); }
.tune .steps { display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
.tune .steps .step { display: flex; gap: 8px; line-height: 1.6; }
.tune .steps .mk { width: 16px; text-align: center; font-weight: 700; }
.tune .steps .mk.s { color: var(--ok); }
.tune .steps .mk.f { color: var(--danger); }
.tune .steps .mk.p { color: var(--blue); }
.tune .steps .mk.w { color: var(--text-2); }
.tune .steps .dt { color: var(--text-2); }
/* Modelos na página de configurações */
.mmod { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.mmod h2 { margin: 0; font-size: 15px; font-weight: 600; }
.mmod .slot { border-top: 1px solid var(--line); padding-top: 10px; font-size: 13.5px; line-height: 1.7; }
.mmod .slot:first-of-type { border-top: 0; padding-top: 0; }
.mmod .slot .nm { font-weight: 600; }
.mmod .slot .meta { color: var(--text-2); font-size: 12.5px; }
.mmod .slot.err .nm { color: var(--danger); }
.mmod .rol { font-size: 13px; color: var(--text-2); display: flex; flex-wrap: wrap; gap: 4px 16px; }
.mmod .body { display: grid; grid-template-columns: 120px 1fr; gap: 6px 14px; align-items: center; }
.mmod .body > label, .mmod .body > .k { font-size: 14px; }
.mmod .body .note { grid-column: 2; font-size: 13px; line-height: 1.55; color: var(--text-2); }
.mmod input[type=number], .mmod input[type=text] { width: 120px; height: 32px; padding: 0 8px; border: 1px solid #D2D2D7; border-radius: 8px; font: inherit; font-size: 15px; }
.mmod input[type=text] { width: 100%; max-width: 340px; }
.mmod .btn { height: 34px; padding: 0 16px; border: 0; border-radius: 999px; background: #E5E5EA; font: inherit; font-size: 14px; cursor: pointer; }
.mmod .btn.primary { background: var(--blue); color: #FFF; }
.mmod .btn:disabled { opacity: .45; cursor: default; }
.mmod .msg { font-size: 13px; line-height: 1.55; }
.mmod .msg.bad { color: var(--danger); }
.mmod .msg.ok { color: var(--ok); }
@media (max-width: 560px) {
  .tune .kv { grid-template-columns: 1fr; }
  .tune .kv > span:first-child { color: var(--text); font-weight: 500; }
  .tune .tbl { grid-template-columns: max-content minmax(0, 1fr); }
  .tune .tbl > * { padding-right: 12px; }
  .tune .tbl > :nth-child(-n+3) { border-top: 1px solid var(--line); }
  .tune .tbl > :nth-child(-n+2) { border-top: 0; }
  .tune .tbl > .d { grid-column: 1 / -1; border-top: 0; padding-top: 0; }
  .mmod .body { grid-template-columns: 1fr; }
  .mmod .body .note { grid-column: 1; }
}
`;
if (!document.getElementById('tune-css')) {
  const s = document.createElement('style');
  s.id = 'tune-css';
  s.textContent = CSS;
  document.head.appendChild(s);
}

// ---- Formatação ----
const num = (v, d = 1) => (typeof v === 'number' && isFinite(v) ? v.toFixed(d) : '—');
const rnd = (v) => (typeof v === 'number' && isFinite(v) ? String(Math.round(v)) : '—');
const txt = (v) => (v === null || v === undefined || v === '' ? '—' : String(v));

// ---- Cartão 1: estado de execução ----
function StepMark({ status }) {
  const c = { success: 's', failed: 'f', starting: 'p', waiting: 'w' }[status] || 'w';
  const g = { success: '✓', failed: '✗', starting: '●', waiting: '○' }[status] || '·';
  return html`<span class=${'mk ' + c}>${g}</span>`;
}

function RunCard({ run }) {
  const [open, setOpen] = useState(false);
  const ph = run?.phase || {};
  const auto = ph.kind === 'warn' || ph.kind === 'bad' || ph.error;
  const shown = open || auto;
  const toggle = () => setOpen(!open);
  const hz = run?.loop?.hz;
  const can = run?.can_walk;
  const walk = run?.net?.walk_model;
  const actual = run?.scale?.actual;
  const st = run?.startup;
  return html`<section class="board card tn-run" aria-label="Estado de execução">
    <button style=${'all:unset;display:block;width:100%;cursor:pointer'} onClick=${toggle} aria-expanded=${shown}>
      <div class="summary">
        <span class=${'ph ' + (ph.kind || '')}>${txt(ph.word)}</span>
        <span>·</span>
        <span class="num">${num(hz)} Hz</span>
        ${can !== null ? html`<span>·</span><span>${can ? 'Pode começar a andar' : 'Ainda não pode andar'}</span>` : null}
        ${walk ? html`<span>·</span><span>Modelo de marcha ${walk}</span>` : null}
        ${actual !== null && actual !== undefined ? html`<span>·</span><span>Fator deste ciclo ${num(actual, 2)}</span>` : null}
        <span style="color:var(--text-2);margin-left:auto">${shown ? 'Recolher ▲' : 'Detalhes ▼'}</span>
      </div>
    </button>
    ${shown ? html`
      ${st && st.known ? html`<div class="group"><b>Quatro etapas de inicialização</b>
        <div class="steps">${(st.rows || []).map((r) => html`<div class="step">
          <${StepMark} status=${r.status} /><span>${r.name}</span>
          ${r.detail ? html`<span class="dt">${r.detail}</span>` : null}
          ${r.at_s !== null && r.at_s !== undefined ? html`<span class="dt">(há ${num(r.at_s)} s desde a inicialização)</span>` : null}
        </div>`)}</div>
        ${st.unsupported ? html`<div class="foot">${st.unsupported}</div>` : null}
      </div>` : null}
      <div class="group"><b>Controle</b>
        <div class="kv">
          <span>Frequência desejada / real</span><span class="num">${num(run?.loop?.target)} / ${num(hz)} Hz</span>
          <span>Ciclos perdidos por tempo esgotado</span><span class="num">${rnd(run?.loop?.missed)}${run?.loop?.missed_per_min != null ? ` (último minuto: +${rnd(run?.loop?.missed_per_min)})` : ''}</span>
          <span>Tempo desde o último ciclo</span><span class="num">${num(run?.loop?.last_tick_age_ms, 0)} ms</span>
          <span>Rede em uso</span><span>${txt(run?.net?.active_model)}${run?.net?.scale_use_cn ? ` · ${run?.net?.scale_use_cn}` : ''}</span>
          <span>Fator deste ciclo</span><span class="num">${num(actual, 2)} = base ${num(run?.scale?.base, 2)} × tensão ${num(run?.scale?.volt_mult, 2)}</span>
        </div>
      </div>
      ${run?.guard ? html`<div class="group"><b>Condição para andar</b>
        <div class="kv">
          <span>Maior desvio articular</span><span class="num">${num(run.guard.max_joint_error_deg, 2)}° / tolerância ${num(run.guard.joint_tolerance_deg, 2)}°</span>
          <span>Inclinação do corpo</span><span class="num">${num(run.guard.tilt_deg, 2)}° / tolerância ${num(run.guard.tilt_tolerance_deg, 2)}°</span>
          ${run.guard.reason ? html`<span>Motivo</span><span>${run.guard.reason}</span>` : null}
          ${run?.refusal ? html`<span>Última recusa</span><span class="warn">${run.refusal}</span>` : null}
        </div>
      </div>` : null}
      <div class="group"><b>Hardware</b>
        <div class="kv">
          <span>IMU</span><span>${txt(run?.imu?.source)} · ${run?.imu?.ready === true ? 'Pronta' : run?.imu?.ready === false ? 'Não pronta' : '—'}${run?.imu?.age_ms !== undefined ? ` · há ${num(run?.imu?.age_ms, 0)} ms` : ''}${run?.imu?.fusion?.verdict ? ` · fusão ${run.imu.fusion.verdict}` : ''}</span>
          <span>Barramento</span><span>${rnd(run?.bus?.consecutive_errors)} falhas consecutivas${run?.bus?.startup_failures ? ` · ${rnd(run?.bus?.startup_failures)} falhas na inicialização` : ''}</span>
          ${(run?.bus?.worst || []).length ? html`<span>Servos com mais tempos esgotados</span><span>${run.bus.worst.map((w) => `${w.name} (tempo esgotado ${w.timeout} · pacote ausente ${w.missing})`).join(' · ')}</span>` : null}
          ${run?.cpu_c !== undefined && run?.cpu_c !== null ? html`<span>Temperatura da placa</span><span class="num">${num(run.cpu_c, 0)} °C</span>` : null}
        </div>
      </div>
      <div class="foot">${txt(run?.infer_note)}</div>
    ` : null}
  </section>`;
}

// ---- Cartão 2: ajuste do movimento (somente leitura) ----
function FeelCard({ feel, cap }) {
  const [adv, setAdv] = useState(true);
  const walk = feel?.walk || {};
  const vals = walk.values || {};
  const active = feel?.active;
  const pad = feel?.pad || {};
  const cur = pad.current || {};
  const servo = feel?.servo || {};
  const eff = servo.effective || {};
  // Três células por linha: nome, valor e descrição. A célula de descrição permanece mesmo vazia para alinhar a tabela.
  const row = (k, v, d, kind) => html`<span class="k">${k}</span><span class="v">${v}</span><span class=${'d ' + (kind || '')}>${d || ''}</span>`;
  // Nos três parâmetros de marcha, use o valor ativo no programa principal; se não estiver disponível, use o valor do arquivo. Avise somente se o arquivo tiver um valor diferente do ativo.
  const wv = (key, label, def) => {
    const x = vals[key] || {};
    const v = x.loaded != null ? x.loaded : x.file;
    const dflt = def != null ? `Padrão ${num(def, 2)}` : '';
    if (x.file != null && x.loaded != null && x.file !== x.loaded) {
      return row(label, num(v, 2), `${dflt ? `${dflt} · ` : ''}o arquivo define ${num(x.file, 2)}, mas o programa principal ainda usa ${num(x.loaded, 2)} (a alteração entra em vigor após reiniciar o programa principal)`, 'warn');
    }
    return row(label, num(v, 2), dflt);
  };
  const pdi = (gs) => (gs || []).map((g) => `P${g.pdi[0]} D${g.pdi[1]} ×${g.n}`).join(' / ') || '—';
  return html`<section class="board card" aria-label="Ajuste do movimento">
    <h3>Ajuste do movimento</h3>
    <p class=${'cap ' + (cap?.can_edit === false ? '' : 'bad')}>${cap?.why || 'Lendo a configuração do MicroDuck…'}</p>
    <div class="tbl">
      ${wv('action_scale', 'Amplitude da marcha', walk.default?.action_scale)}
      ${wv('head_lowpass', 'Suavização da cabeça', walk.default?.head_lowpass)}
      ${wv('legs_lowpass', 'Suavização das pernas', walk.default?.legs_lowpass)}
      ${active ? row('Valores usados neste ciclo', `${num(active.action_scale, 2)} · ${num(active.head_lowpass, 2)} · ${num(active.legs_lowpass, 2)}`,
        `amplitude · cabeça · pernas${active.use ? ` (${active.use})` : ''}`) : null}
      ${row('Abertura da boca', `${num(cur.mouth_percent, 0)}%`,
        pad.mouth_warn ? 'Quase não abre: o gatilho LT / RT do controle web multiplica esse percentual; a ação “Abrir a boca” não é afetada.' : '', pad.mouth_warn ? 'warn' : '')}
      ${row('Amplitude da cabeça', `${num(cur.head_rad, 1)} rad`, '')}
    </div>
    <div class="fold">
      <button onClick=${() => setAdv(!adv)} aria-expanded=${adv}>${adv ? '▾' : '▸'} Resposta dos servos · avançado</button>
      ${adv ? html`<div class="tbl" style="margin-top:8px">
        ${row('P', rnd(eff.kp), servo.src ? `Origem do valor ativo: ${servo.src}` : '')}
        ${row('D', rnd(eff.kd), '')}
        ${row('Limite de torque', rnd(eff.torque_limit), '')}
        ${servo.written_p ? row('Valor P gravado ao ativar os motores', servo.written_p.p != null ? rnd(servo.written_p.p) : '—',
          `${servo.written_p.src || ''}${servo.written_p.applied ? ' · gravado' : ''}`) : null}
        ${servo.regs ? row('Registradores do servo antes de ativar os motores', '', `RAM ${pdi(servo.regs.ram_before_arm)} · EEPROM ${pdi(servo.regs.eeprom)}`) : null}
        ${(servo.warn || []).map((w) => row('', '', w, 'warn'))}
      </div>` : null}
      ${adv && servo.regs_why ? html`<div class="foot">${servo.regs_why}</div>` : null}
    </div>
  </section>`;
}

// ---- Cartão 3: modelos (somente leitura) ----
function ModelsCard({ models }) {
  const slots = models?.slots || [];
  const rollers = models?.rollers || [];
  // Se não for possível ler a descrição do modelo no robô, informe isso e mostre a impressão digital do arquivo quando disponível.
  const what = (s) => (s.name ? `${s.name}${s.rounds ? ` · ${s.rounds} ciclos` : ''}` : s.path ? 'Descrição do modelo indisponível' : 'Não instalado');
  const rolOn = rollers.filter((r) => r.installed);
  return html`<section class="board card" aria-label="Modelos">
    <h3>Modelos <a href="#/models" aria-label="Gerenciar modelos" style="font-size:12px;font-weight:400;color:var(--blue);text-decoration:none">Gerenciar…</a></h3>
    <div class="tbl">
      ${slots.map((s) => html`<span class="k">${s.label}</span>
        <span>${s.error ? html`<span class="tn-tag err">Não carregado</span>` : s.active ? html`<span class="tn-tag on">Em execução</span>`
          : s.loaded ? html`<span class="tn-tag on">Carregado</span>` : html`<span class="tn-tag">${s.path ? 'Não carregado' : 'Não instalado'}</span>`}</span>
        <span class="d">${what(s)}${s.sha12 ? html` · <span title="Impressão digital do arquivo (12 primeiros caracteres do SHA-256)">${s.sha12}</span>` : null}
          ${s.error ? html`<br /><span class="bad">${s.error}</span>` : null}
          ${s.exec ? html`<br />amplitude ${num(s.exec.action_scale, 2)} · cabeça ${num(s.exec.head_lowpass, 2)} · pernas ${num(s.exec.legs_lowpass, 2)}` : null}
          ${s.buttons?.length ? html`<br />Botões do controle: ${s.buttons.join(' ')}` : null}</span>`)}
      ${rollers.length ? html`<span class="k">Rodas ( ${rollers.length} )</span>
        <span><span class=${'tn-tag' + (rolOn.length ? ' on' : '')}>${rolOn.length ? `${rolOn.length} instaladas` : 'Não instaladas'}</span></span>
        <span class="d">${rolOn.length
          ? rollers.map((r) => `${r.label.replace(/^Roda · /, '')} ${r.installed ? (r.rounds ? `${r.rounds} ciclos` : 'Instalada') : 'Não instalada'}`).join(' · ')
          : 'Disponível após instalar as rodas'}</span>` : null}
    </div>
  </section>`;
}

// ---- Três cartões do painel ----
export function TuneSection({ tune }) {
  if (!tune || !tune.ready) return html`<div class="board card tune"><h3>Estado e ajustes</h3><div class="cap">Lendo a configuração do MicroDuck…</div></div>`;
  return html`<div class="tune" id="tune-block">
    <${RunCard} run=${tune.run} />
    <${FeelCard} feel=${tune.feel} cap=${tune.cap} />
    <${ModelsCard} models=${tune.models} />
  </div>`;
}

// ---- Configurações › Modelos ----
const BODY_FIELDS = [
  ['total_g', 'Peso total do robô', 'g'],
  ['trunk_g', 'Tronco', 'g'],
  ['head_g', 'Cabeça', 'g'],
  ['leg_left_g', 'Perna esquerda', 'g'],
  ['leg_right_g', 'Perna direita', 'g'],
];

export function ModelSettings({ tune, link }) {
  const [body, setBody] = useState(null);
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    await link.whenOpen();
    const r = await link.cmd('tune.op', { op: 'body' }, 8000);
    if (r.ok) {
      const b = r.data || {};
      setBody(b);
      setForm(Object.fromEntries(BODY_FIELDS.map(([k]) => [k, b[k] ?? '']).concat([['foot', b.foot ?? ''], ['note', b.note ?? '']])));
    } else {
      setMsg({ kind: 'bad', text: `Não foi possível ler os pesos: ${r.reason || r.error}` });
    }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setBusy(true);
    const b = {};
    for (const [k] of BODY_FIELDS) {
      const v = form[k];
      b[k] = (v === '' || v === null || v === undefined) ? null : Number(v);
    }
    b.foot = (form.foot || '').trim() || null;
    b.note = (form.note || '').trim() || null;
    const r = await link.cmd('tune.op', { op: 'save_body', body: b }, 8000);
    setBusy(false);
    if (r.ok) { setBody(r.data); setMsg({ kind: 'ok', text: 'Salvo no Studio. Os dados serão incluídos ao exportar o perfil.' }); }
    else setMsg({ kind: 'bad', text: `Não foi possível salvar: ${r.reason || r.error}` });
  };

  const slots = tune?.models?.slots || [];
  const rollers = tune?.models?.rollers || [];
  return html`<div class="board mmod" aria-label="Modelos">
    <h2>Modelos e perfil do robô</h2>
    <a href="#/models" style="font-size:13px;color:var(--blue)">Abrir o gerenciamento de modelos para importar modelos ou configurar botões →</a>
    ${slots.map((s) => html`<div class=${'slot' + (s.error ? ' err' : '')}>
      <div><span class="nm">${s.label}</span>${s.active ? ' · Em uso' : s.loaded ? ' · Carregado' : ' · Não instalado'}${s.rounds ? ` · ${s.rounds} ciclos` : ''}</div>
      <div class="meta">${s.name ? s.name : '—'}${s.task ? ` · ${s.task}` : ''}${s.sha12 ? ` · ${s.sha12}` : ''}${s.commit ? ` · ${s.commit}` : ''}</div>
      ${s.exec ? html`<div class="meta">Configuração de execução: amplitude ${num(s.exec.action_scale, 2)} · cabeça ${num(s.exec.head_lowpass, 2)} · pernas ${num(s.exec.legs_lowpass, 2)}</div>` : null}
      ${s.error ? html`<div class="meta" style="color:var(--danger)">${s.error}</div>` : null}
    </div>`)}
    ${rollers.length ? html`<div class="rol">${rollers.map((r) => html`<span>${r.label}: ${r.installed ? (r.rounds ? `${r.rounds} ciclos` : 'Instalada') : 'Não instalada'}</span>`)}</div>` : null}

    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">
      <a class="btn primary" href="/api/profile" style="display:inline-flex;align-items:center;text-decoration:none">Exportar perfil do MicroDuck (JSON)</a>
      <span class="msg" style="color:var(--text-2)">Para treinamento: orientação da IMU, posições neutras dos servos, P/D/limite de torque, modelo de marcha e pesos abaixo.</span>
    </div>

    <div class="body">
      ${BODY_FIELDS.map(([k, label, unit]) => html`
        <label>${label}</label>
        <span style="display:flex;align-items:center;gap:8px">
          <${Stepper} value=${form ? form[k] : ''} min=${0} max=${5000} step=${0.1}
            aria-label=${label} unit=${unit} onChange=${(v) => setForm({ ...form, [k]: v })} />
        </span>`)}
      <span class="k">Material da sola</span>
      <span><input type="text" maxlength="40" value=${form ? form.foot : ''} aria-label="Material da sola"
        onInput=${(e) => setForm({ ...form, foot: e.target.value })} /></span>
      <span class="k">Observações</span>
      <span><input type="text" maxlength="200" value=${form ? form.note : ''} aria-label="Observações"
        onInput=${(e) => setForm({ ...form, note: e.target.value })} /></span>
      <span></span>
      <div class="note">Os pesos são incluídos no perfil exportado. Se um peso for desconhecido, deixe-o como null (não use 0). Uma estimativa é suficiente para o treinamento.</div>
    </div>

    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px">
      <button class="btn primary" type="button" disabled=${!form || busy} onClick=${save}>Salvar pesos</button>
      ${msg ? html`<span class=${'msg ' + msg.kind}>${msg.text}</span>` : null}
    </div>
  </div>`;
}
