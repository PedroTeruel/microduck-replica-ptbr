// Página de servos: o servo-web foi integrado por completo ao Studio.
//
// Layout:
// - À esquerda: visualização 3D fixa na tela e, abaixo, um cartão de ações frequentes: calibrar, desfazer, aplicar poses oficiais, ativar ou liberar todos os servos e parar.
// - À direita: 15 servos em três grupos (perna esquerda, perna direita e cabeça/pescoço), com colunas alinhadas; clique em uma linha para ver tensão, carga, corrente, deslocamento, P/D e direção.
// - Na parte inferior, a seção recolhida “Mais” reúne movimento, poses salvas, ferramentas avançadas (exportar registradores, alterar ID etc.) e registros.
// Sem assumir o barramento, os dados vêm do programa principal e são somente leitura. O Studio só assume o barramento ao iniciar o ajuste dos servos; nesse modo, o programa principal para e o controle fica indisponível.
// O backend é studio/servo_ops.py, adaptado de server.py do servo-web.
import { html, Component, useState, useEffect, useRef, useCallback } from './vendor/preact-htm.module.js';
import { Duck3D, JOINT_NAMES } from './duck3d.js';
import { drawServoLabels } from './labels.js';
import { TwoStep } from './confirm.js';
import { Stepper } from './stepper.js';

// Poses oficiais de referência: keyframes de microduck_rl scene.xml, compartilhados com o servo-web, em radianos e na ordem de JOINT_NAMES.
const POSES = {
  zero: { label: 'Posição zero', rad: Array(15).fill(0) },
  stand: { label: 'Em pé', rad: [0, -0.0873, -0.4579, -0.0049, 0.453, 0.3491, 0.3491, 0, 0, 0, 0, 0.0873, 0.4579, 0.0049, -0.453] },
  sit: { label: 'Sentado', rad: [0, 0, -0.5236, 1.0472, 0, 0.5, 1.6, 0, 0, 0, 0, 0, 0.5236, -1.0472, 0] },
  fold: { label: 'Recolhido', rad: [0, 0, 1.57, 1.57, 0, 1, 1, 0, 0, 0, 0, 0, -1.57, -1.57, 0] },
};
const IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14];       // Ordem de JOINT_NAMES.
const ID_OF = Object.fromEntries(JOINT_NAMES.map((n, i) => [n, IDS[i]]));
const NAME_OF = Object.fromEntries(IDS.map((id, i) => [id, JOINT_NAMES[i]]));
const GROUP_OF = (id) => (id >= 30 ? 'H' : id >= 20 ? 'L' : 'R');
const SEL_COLOR = { R: '#E5484D', L: '#2F7CF6', H: '#F5B400' };
const GROUPS = [['L', 'Perna esquerda', '20–24'], ['R', 'Perna direita', '10–14'], ['H', 'Cabeça e pescoço', '30–34']];
const DANGER = { 5: 'ID: pode causar conflito; conecte somente este servo ao barramento antes de alterar', 6: 'Taxa de transmissão: a alteração interrompe a comunicação', 8: 'Nível de resposta: com valor 0, o servo não responde aos comandos de gravação',
  9: 'Limite mínimo de ângulo', 11: 'Limite máximo de ângulo', 19: 'Condição de alívio (proteção): desativar a proteção contra superaquecimento e sobrecorrente impede o alívio automático', 33: 'Modo de operação: no modo de velocidade, o servo gira continuamente' };
const REGS = [[41, 'Aceleração', 1, 'SRAM'], [46, 'Velocidade de operação', 2, 'SRAM'], [48, 'Limite de torque', 2, 'SRAM'],
  [50, 'P do controle de posição (em operação)', 1, 'SRAM'], [51, 'D do controle de posição (em operação)', 1, 'SRAM'], [21, 'P do controle de posição', 1, 'EEPROM'],
  [22, 'D do controle de posição', 1, 'EEPROM'], [23, 'I do controle de posição', 1, 'EEPROM'], [13, 'Limite máximo de temperatura', 1, 'EEPROM'], [19, 'Condição de alívio', 1, 'EEPROM'],
  [28, 'Corrente de proteção', 2, 'EEPROM'], [9, 'Limite mínimo de ângulo', 2, 'EEPROM'], [11, 'Limite máximo de ângulo', 2, 'EEPROM'], [8, 'Nível de resposta', 1, 'EEPROM'],
  [33, 'Modo de operação', 1, 'EEPROM'], [5, 'ID', 1, 'EEPROM'], [6, 'Taxa de transmissão', 1, 'EEPROM']];

const fmt = (v, d = 0) => (typeof v === 'number' && isFinite(v) ? v.toFixed(d) : '—');
const sign = (v, d = 1) => (typeof v === 'number' ? `${v > 0 ? '+' : ''}${v.toFixed(d)}` : '—');
let calibHandler = null;      // A ServoPage configura este handler para reutilizar a mesma confirmação de calibração em todos os pontos.

// ---------------- 3D ----------------

function ServoStage({ sv, pose, setPose, selected, onSelect }) {
  const boxRef = useRef(null), canvasRef = useRef(null), duckRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [moved, setMoved] = useState(false);

  useEffect(() => {
    const d = new Duck3D(canvasRef.current, { view: 'front', centerX: 0.5, centerY: 0.52, fill: 0.82 });
    duckRef.current = d;
    d.onUserMove = () => setMoved(true);
    d.onPick = (name) => ID_OF[name] && onSelect(ID_OF[name]);
    d.load('model/').then(() => setReady(true)).catch(() => {});
    return () => d.dispose();
  }, []);

  // Modo em tempo real: converte a leitura em radianos (direção × (leitura − 2048) × 2π / 4096); poses de referência usam keyframes oficiais.
  useEffect(() => {
    const d = duckRef.current;
    if (!d || !ready) return;
    if (pose === 'live') {
      if (!sv?.rows?.length) return;
      d.setJoints(sv.rows.map((r) => (r.raw == null ? 0 : r.dir * (r.raw - 2048) * 2 * Math.PI / 4096)));
    } else {
      d.setJoints(POSES[pose].rad);
    }
    d.setGravity(null);
  }, [sv, pose, ready]);

  useEffect(() => {
    if (!ready) return;
    duckRef.current.select(selected ? NAME_OF[selected] : null, selected ? SEL_COLOR[GROUP_OF(selected)] : null);
  }, [selected, ready]);

  useEffect(() => {
    if (!ready || pose !== 'zero') return undefined;
    return drawServoLabels(duckRef.current, boxRef.current);
  }, [ready, pose]);

  return html`<div class="sv-stage" ref=${boxRef}>
    <canvas ref=${canvasRef}></canvas>
    <div class="sv-poses" role="tablist" aria-label="Visualização 3D">
      ${[['live', 'Ao vivo'], ...Object.entries(POSES).map(([k, p]) => [k, p.label])].map(([k, label]) =>
        html`<button role="tab" aria-selected=${pose === k} class=${pose === k ? 'on' : ''} onClick=${(e) => { e.currentTarget.blur(); setPose(k); }}>${label}</button>`)}
    </div>
    ${!ready ? html`<span class="sv-loading">Carregando modelo 3D…</span>` : null}
    <span class="sv-note">${pose !== 'live' ? 'Pose de referência · não representa a posição atual do MicroDuck' : 'Arraste para girar · clique em um servo para selecioná-lo'}</span>
    ${moved ? html`<button class="reset-view" onClick=${(e) => { e.currentTarget.blur(); duckRef.current?.resetView(); setMoved(false); }}>Redefinir visão</button>` : null}
  </div>`;
}

// A linha do cabeçalho mostra P, D e limite de torque, iguais aos do programa principal.
// Diferenças causadas por alterações manuais nos registradores ou por servos já ativados são destacadas. Ver servo_ops.gains_view no backend.
function GainsLine({ g }) {
  const man = g.manual || [], off = g.differ_on || [];
  return html`<div class="sv-sub sv-gains" title=${g.detail + (g.warn ? '\n' + g.warn : '')}>
    Ganhos: P${g.kp} · D${g.kd} · limite de torque ${g.limit} (igual ao programa principal · ${g.source})${
    g.warn ? html` · <span class="sv-warn">Arquivo de parâmetros inválido; usando os padrões do programa principal (consulte os registros)</span>` : null}${
    man.length ? html` · <span class="sv-warn">Alterações manuais diferentes do programa principal: ${man.map((m) => `#${m.id} ${m.what || 'registrador'}=${m.value} (registrador ${m.addr})`).join(', ')}</span>`
      : off.length ? html` · <span class="sv-warn">${off.map((i) => '#' + i).join(' ')} estão ativados com ganhos diferentes (libere e ative novamente para aplicar estes valores)</span>` : null}
  </div>`;
}

function Why() {
  return html`<section class="board sv-card sv-why">
    <h3>Por que posicionar o robô e calibrar a posição zero?</h3>
    <ol>
      <li>Cada servo tem um codificador com 4.096 posições por volta, de 0 a 4095. O disco estriado pode ser montado em ângulos diferentes; uma diferença de um ou dois dentes já representa vários graus.</li>
      <li><b>Calibrar</b> significa posicionar o MicroDuck conforme a imagem acima, na posição zero oficial (pernas estendidas, cabeça alinhada e boca fechada), e gravar <b>2048</b> como posição atual em cada servo.</li>
      <li>Após a calibração, a leitura 2048 indica que a articulação está na posição zero. O programa oficial, as políticas de marcha treinadas e o Studio <b>usam 2048 como zero</b> para calcular os ângulos.</li>
      <li>Sem calibrar, a política pode considerar a perna estendida quando ela está alguns graus dobrada. O robô pode andar torto, raspar no chão ou cair.</li>
      <li>O robô não detecta como as peças foram montadas. Uma pessoa precisa posicioná-lo conforme a referência oficial e fazer esta calibração.</li>
    </ol>
  </section>`;
}

// ---------------- Os 15 servos, alinhados nas mesmas colunas ----------------

function commDot(r) {
  const c = r.comm || {};
  const tip = c.asked == null
    ? `${c.missed} perdas no total · ${c.streak} consecutivas (contagem do programa principal)`
    : `${c.asked} solicitações · ${c.ok} respostas · ${c.missed} perdas · máximo de ${c.max_streak} consecutivas${c.alarm ? ` · alerta ${c.alarm}` : ''}`;
  const kind = !r.fresh || c.streak >= 3 ? 'bad' : c.asked != null && c.missed > 0 && c.missed / Math.max(c.asked, 1) > 0.01 ? 'warn' : 'ok';
  return html`<span class=${'sv-dot ' + kind} title=${tip}></span>`;
}

function tempClass(r) {
  if (typeof r.temp !== 'number' || typeof r.temp_limit !== 'number' || !r.temp_limit) return '';
  if (r.temp >= r.temp_limit) return 'bad';
  if (r.temp >= r.temp_limit - 10) return 'warn';
  return '';
}

function Row({ r, open, selected, onSelect, op, follow, setHint }) {
  const [drag, setDrag] = useState(null);           // Valor durante o arraste; após soltar, volta à leitura real em 0,6 s.
  const last = useRef(0), release = useRef(null);
  const send = (v, force) => {
    if (!open) return;
    if (r.torque !== 1) { setHint(`${r.id} ${r.cn}: torque desativado. O servo não se moverá pelo controle deslizante; ative “Manter” primeiro.`); return; }
    const now = performance.now();
    if (!force && now - last.current < 50) return;   // Envia no máximo uma vez a cada 50 ms.
    last.current = now;
    op({ op: 'goal', id: r.id, pos: v }, 3000, true);
  };
  const onInput = (e) => { const v = +e.target.value; setDrag(v); clearTimeout(release.current); if (follow) send(v, false); };
  const onDone = (e) => { const v = +e.target.value; send(v, true); clearTimeout(release.current); release.current = setTimeout(() => setDrag(null), 600); };
  const val = drag ?? r.raw ?? 2048;
  const stop = (e) => e.stopPropagation();
  const c = r.comm || {};
  return html`<div class=${'sv-row' + (r.fresh ? '' : ' stale') + (selected ? ' sel ' + r.group : '')} onClick=${() => onSelect(selected ? null : r.id)}>
    <span class=${'sv-id ' + r.group}>${r.id}</span>
    <span class="sv-name" title=${r.en}>${r.cn}</span>
    <input class="sv-slider" type="range" min="0" max="4095" step="1" value=${val} disabled=${!open}
      aria-label=${`${r.cn} posição desejada`} onClick=${stop} onInput=${onInput} onChange=${onDone} />
    <span class="num r">${fmt(drag ?? r.raw)}</span>
    <span class="num r sv-deg">${r.deg == null ? '—' : sign(r.deg) + '°'}</span>
    <span class=${'num r ' + tempClass(r)} title=${r.temp_limit ? `Limite de temperatura deste servo: ${r.temp_limit} °C` : ''}>${fmt(r.temp)}°C</span>
    <label class=${'sv-switch' + (r.torque === 1 ? ' on' : '')} onClick=${stop} title=${r.torque === 1 ? 'Servo mantendo a posição; clique para liberar' : 'Servo liberado; clique para manter (alinhe com a posição atual antes de ativar o torque)'}>
      <input type="checkbox" checked=${r.torque === 1} disabled=${!open}
        onChange=${(e) => op({ op: 'torque', on: e.target.checked ? 1 : 0, ids: [r.id] })} />
      <span>${r.torque === 1 ? 'Manter' : 'Liberar'}</span>
    </label>
    <button class="sv-mini" disabled=${!open} onClick=${(e) => { stop(e); calibHandler && calibHandler(String(r.id)); }}
      title="Calibrar posição central: define a posição atual deste servo como zero (2048) e mantém a posição ao terminar">Centro</button>
    ${commDot(r)}
    ${selected ? html`<div class="sv-more num" onClick=${stop}>
      <span>Tensão <b>${fmt(r.volt, 1)} V</b></span><span>Carga <b>${fmt(r.load)}</b></span>
      ${r.current_ma != null ? html`<span>Corrente <b>${fmt(r.current_ma)} mA</b></span>` : null}
      ${r.offset != null ? html`<span title="Registrador 31: deslocamento da posição zero armazenado no servo">Deslocamento <b>${r.offset}</b></span>` : null}
      ${r.p_run != null ? html`<span title=${`P / D / limite de torque em operação (leituras de RAM 50 / 51 / 48; antes de ativar o torque, o Studio grava os valores do programa principal; destaque amarelo indica diferença). P / D armazenados na EEPROM (21 / 22): ${r.p ?? '?'} / ${r.d ?? '?'}`}>P/D/torque <b class=${r.gains_ok === false ? 'warn' : ''}>${r.p_run}/${r.d_run}/${r.limit ?? '?'}</b></span>`
        : r.p != null ? html`<span title="P / D do controle de posição (registradores 21 / 22)">P/D <b>${r.p}/${r.d}</b></span>` : null}
      <span>Comunicação <b>${c.missed ?? 0} perdas${c.asked != null ? ` / ${c.asked} solicitações` : ''}</b></span>
      ${r.status ? html`<span class="sv-alarm">Bits de estado ${r.status}</span>` : null}
      <span class="sv-spacer"></span>
      <span>Direção</span><button class="sv-mini" disabled=${!open} onClick=${() => op({ op: 'set_dir', id: r.id, dir: -r.dir })}
        title="Direção ±: define para qual lado do modelo a leitura aumenta (afeta apenas a exibição e a conversão; não move o servo)">${r.dir > 0 ? '+1' : '−1'}</button>
    </div>` : null}
  </div>`;
}

// Os dados dos servos chegam 10 vezes por segundo. Só redesenha a linha quando algo muda; redesenhar a página inteira prejudica a visualização 3D.
const rowSig = (p) => { const r = p.r, c = r.comm || {};
  return [r.raw, r.deg, r.volt, r.temp, r.load, r.current_ma, r.torque, r.fresh, r.dir, r.offset, r.p, r.d, r.status,
    r.p_run, r.d_run, r.limit, r.gains_ok, c.missed, c.streak, p.open, p.selected, p.follow].join('|'); };
class RowPure extends Component {
  shouldComponentUpdate(next) { return rowSig(next) !== rowSig(this.props) || next.op !== this.props.op; }
  render(props) { return html`<${Row} ...${props} />`; }
}

function ServoList({ sv, open, selected, onSelect, op, follow, setHint }) {
  const rows = sv.rows || [];
  return html`<section class="board sv-list">
    <div class="sv-row sv-headrow"><span></span><span>Servo</span><span>Posição (arraste)</span><span class="r">Leitura</span><span class="r">Ângulo</span>
      <span class="r">Temperatura</span><span>Torque</span><span></span><span></span></div>
    ${GROUPS.map(([g, label, range]) => {
      const gr = rows.filter((r) => r.group === g);
      const hold = gr.filter((r) => r.torque === 1).length;
      return html`<div class="sv-group">
        <div class="sv-grouphead"><span class=${'sv-gdot ' + g}></span>${label}<span class="sv-small">${range}</span>
          ${hold ? html`<span class="sv-hold-n">Mantendo ${hold}</span>` : null}</div>
        ${gr.map((r) => html`<${RowPure} key=${r.id} r=${r} open=${open} selected=${r.id === selected} onSelect=${onSelect}
          op=${op} follow=${follow} setHint=${setHint} />`)}
      </div>`;
    })}
  </section>`;
}

// ---------------- Ações frequentes (abaixo do 3D) ----------------

// Seletor de servo sincronizado com a visualização 3D e a tabela.
function ServoPick({ selected, onSelect, rows }) {
  return html`<select class="sv-pick" value=${selected ?? ''} onChange=${(e) => onSelect(e.target.value === '' ? null : +e.target.value)}>
    <option value="">Selecione um servo</option>
    ${GROUPS.map(([g, label]) => html`<optgroup label=${label}>${(rows || []).filter((r) => r.group === g).map((r) =>
      html`<option value=${r.id}>${r.id} · ${r.cn}</option>`)}</optgroup>`)}
  </select>`;
}

// Barra de ações baseada no servo-web.
function Toolbar({ open, op, link, motion, setMotion, idle, setIdle, follow, setFollow, poses, setHint, syncSliders, main }) {
  const ms = { seconds: motion.seconds, mode: motion.mode, acc: motion.acc };
  // Prefere uma pose salva com esse nome (ajustada no robô); se não houver pose em pé, usa a pose oficial.
  const named = (word) => poses.find((p) => p.name.includes(word));
  const goNamed = (word, fallbackKey) => {
    const p = named(word);
    if (p) op({ op: 'go_pose', file: p.file, ...ms });
    else if (fallbackKey) op({ op: 'official', key: fallbackKey, ...ms });
    else setHint(`Não há uma pose chamada “${word}”. Posicione o robô e salve uma pose com esse nome na seção “Mais”.`);
  };
  return html`<div class="sv-toolbar">
    <button class="btn-ok" disabled=${!open} onClick=${() => op({ op: 'torque', on: 1 })} title="Alinhe primeiro com a posição atual para evitar um movimento brusco">Ativar torque em todos</button>
    <button class="btn-danger" disabled=${!open} onClick=${(e) => { e.currentTarget.blur(); link.cmd('relax', {}, 7000); }}
      title="Parada de emergência desta página (também pela tecla Espaço): libera os 15 servos e confirma a leitura. O torque não será reativado automaticamente; clique em “Ativar torque em todos” ou “Manter” para retomar">Desativar torque em todos</button>
    <button class="btn-light" onClick=${syncSliders}>Alinhar controles à posição atual</button>
    <button class="btn-light" disabled=${!open} onClick=${() => op({ op: 'official', key: 'zero', ...ms })}
      title="Posição zero: pernas estendidas, pés verticais, cabeça alinhada e boca fechada. A referência oficial define 2048 para cada servo">Voltar à posição zero (2048)</button>
    <button class="btn-light" disabled=${!open} onClick=${() => goNamed('\u7ad9\u59ff', 'stand')}
      title="Usa a pose salva correspondente; se não houver, usa a pose oficial em pé">Em pé</button>
    <button class="btn-light" disabled=${!open} onClick=${() => goNamed('\u7f29\u8d77\u6765', null)} title="Usa a pose salva recolhida">Recolher</button>
    <button class="btn-light" disabled=${!open} onClick=${async () => { const r = await op({ op: 'idle', on: !idle }); if (r.ok) setIdle(!idle); }}
      title="Pequenos movimentos aleatórios da cabeça: inclinar, balançar, acenar, abrir a boca e olhar para os lados. Move apenas os servos 30–34">${idle ? '⏹ Parar movimentos' : '🦆 Movimentos'}</button>
    <button class="btn-light" disabled=${!open} onClick=${() => op({ op: 'scan', ids: '20-24,30-34,10-14' })}>Verificar novamente</button>
    <button class="btn-stop" disabled=${!open} onClick=${() => op({ op: 'stop' })} title="Interrompe a transição ou os movimentos e mantém a posição atual">Parar</button>
    <span class="sv-inline">Duração <${Stepper} value=${motion.seconds} min=${0} max=${30} step=${0.5}
      onChange=${(v) => setMotion({ ...motion, seconds: v === '' ? 0 : v })} unit="s" aria-label="Duração" /></span>
    <label class="sv-inline"><input type="checkbox" checked=${follow} onChange=${(e) => setFollow(e.target.checked)} /> Acompanhar arraste</label>
    ${main}
  </div>`;
}

function CalibCard({ open, op, selected, onSelect, rows }) {
  const [ids, setIds] = useState('20-24,30-34,10-14');
  return html`<section class="board sv-card sv-calib">
    <div class="sv-form">
      <span class="sv-label">Calibrar um servo</span>
      <div class="sv-ctrl">
        <${ServoPick} selected=${selected} onSelect=${onSelect} rows=${rows} />
        <button class="btn-dark" disabled=${!open || !selected} onClick=${() => calibHandler && calibHandler(String(selected))}>Calibrar posição zero deste servo</button>
        <span class="sv-small">Você também pode clicar em “Centro” na linha do servo.</span>
      </div>
      <span class="sv-label">Calibração em lote</span>
      <div class="sv-ctrl">
        <input type="text" value=${ids} onInput=${(e) => setIds(e.target.value)} title="Quais servos calibrar" class="sv-ids" />
        <button class="btn-dark" disabled=${!open} onClick=${() => calibHandler && calibHandler(ids)}>Calibrar seleção</button>
        <button class="btn-light" disabled=${!open} onClick=${() => { if (window.confirm('Desfazer a última calibração e restaurar os deslocamentos salvos no backup?')) op({ op: 'undo' }, 30000); }}>Desfazer última calibração</button>
      </div>
      <span></span><p class="sv-small">Posicione o MicroDuck na posição zero oficial (pernas estendidas, cabeça alinhada e boca fechada). A posição atual será definida como 2048. Confira a prévia antes de gravar; ao terminar, os servos manterão a posição.</p>
    </div>
  </section>`;
}

// ---------------- Mais (seção recolhida) ----------------

function MoreArea({ open, op, motion, setMotion, follow, setFollow, poses, setPoses, selected, onSelect, sv, dirs, link }) {
  const [name, setName] = useState('');
  const ms = { seconds: motion.seconds, mode: motion.mode, acc: motion.acc };
  return html`<details class="board sv-more-area">
    <summary>Mais: movimento, poses salvas, ferramentas avançadas e registros</summary>
    <div class="sv-more-grid">
      <section class="sv-form">
        <span class="sv-label">Poses oficiais</span>
        <div class="sv-ctrl">
          ${Object.entries(POSES).map(([k, p]) => html`<button class="btn-light" disabled=${!open} onClick=${() => {
            if (k === 'fold' && !window.confirm('Pose recolhida: os joelhos dobram apenas 88° (a referência oficial de 90° encosta nas peças). Não use sem calibrar a posição zero; alguns graus de diferença podem fazer os joelhos baterem nas peças. Continuar?')) return;
            op({ op: 'official', key: k, ...ms });
          }}>Aplicar: ${p.label}</button>`)}
        </div>
        <span class="sv-label">Modo de movimento</span>
        <div class="sv-ctrl"><select value=${motion.mode} onChange=${(e) => setMotion({ ...motion, mode: e.target.value })}>
          <option value="profile">Suave (o servo segue uma curva trapezoidal)</option><option value="stream">Fluxo contínuo (comandos enviados passo a passo)</option></select>
          <span class="sv-inline">Aceleração <${Stepper} value=${motion.acc} min=${1} max=${254}
            onChange=${(v) => setMotion({ ...motion, acc: v === '' ? 0 : v })} aria-label="Aceleração" /></span></div>
        <span class="sv-label">Poses salvas</span>
        <div class="sv-ctrl sv-chips">
          ${poses.length ? poses.map((p) => html`<span class="sv-chip"><button disabled=${!open} onClick=${() => op({ op: 'go_pose', file: p.file, ...ms })} title=${p.time}>${p.name}</button>
            <button class="x" disabled=${!open} title="Excluir (mover para a lixeira; é possível recuperar)" onClick=${async () => { if (!window.confirm(`Excluir a pose “${p.name}”?`)) return; const r = await op({ op: 'delete_pose', file: p.file }); if (r.ok) setPoses(r.data.poses); }}>×</button></span>`)
            : html`<span class="sv-small">Nenhuma pose salva.</span>`}
        </div>
        <span></span>
        <div class="sv-ctrl"><input type="text" placeholder="Nome da pose, por exemplo: recolhido" value=${name} onInput=${(e) => setName(e.target.value)} />
          <button class="btn-light" disabled=${!open || !name.trim()} onClick=${async () => { const r = await op({ op: 'save_pose', name }); if (r.ok) { setPoses(r.data.poses); setName(''); } }}>Salvar posição atual</button></div>
      </section>
      <${Tools} open=${open} op=${op} selected=${selected} onSelect=${onSelect} sv=${sv} dirs=${dirs} />
    </div>
    <${LogBox} link=${link} />
  </details>`;
}

function Tools({ open, op, selected, onSelect, sv, dirs }) {
  const sel = selected ?? 20;
  const [newId, setNewId] = useState('');
  const [reg, setReg] = useState(41);
  const [size, setSize] = useState(1);
  const [val, setVal] = useState('');
  const [unlock, setUnlock] = useState(false);
  const [scanIds, setScanIds] = useState('20-24,30-34,10-14');
  const [out, setOut] = useState(null);
  const online = new Set((sv.rows || []).filter((r) => r.fresh).map((r) => r.id));
  const run = async (args, t) => { const r = await op(args, t); if (r.ok && r.data) setOut({ op: args.op, ...r.data }); };
  const copyDirs = () => {
    const line = 'directions = [' + IDS.map((id) => ((dirs[id] ?? -1) < 0 ? -1 : 1)).join(', ') + ']';
    navigator.clipboard?.writeText(line);
    setOut({ op: 'note', text: `Copiado: ${line} (directions em [bus.feetech] de robotd.toml, na ordem 20–24, 30–34, 10–14)` });
  };
  return html`<section class="sv-form">
    <span class="sv-label">Servo</span>
    <div class="sv-ctrl"><${ServoPick} selected=${sel} onSelect=${(id) => onSelect(id ?? 20)} rows=${sv.rows} /></div>
    <span class="sv-label">Avançado</span>
    <div class="sv-ctrl">
      <button class="btn-light" disabled=${!open} onClick=${() => run({ op: 'dump', id: sel })}>Exportar registradores</button>
      <button class="btn-light" disabled=${!open} onClick=${() => { if (window.confirm(`Reiniciar o servo ${sel}? O torque será desativado e ele voltará em cerca de 0,8 s.`)) run({ op: 'reboot', id: sel }); }}>Reiniciar</button>
      <button class="btn-light" onClick=${copyDirs}>Copiar tabela de direção do robotd</button>
    </div>
    <span class="sv-label">Alterar ID</span>
    <div class="sv-ctrl"><span>${sel} →</span>
      <select value=${newId} onChange=${(e) => setNewId(e.target.value)}>
        <option value="">Selecione o novo ID</option>
        ${Array.from({ length: 254 }, (_, i) => i).filter((i) => i !== sel).map((i) => html`<option value=${i}>${i}${online.has(i) ? ' (em uso)' : ''}</option>`)}
      </select>
      <button class="btn-danger" disabled=${!open || newId === ''} onClick=${() => {
        if (online.has(+newId)) { window.alert(`O ID ${newId} já está em uso por outro servo e causará conflito.`); return; }
        if (window.confirm(`Alterar o ID ${sel} para ${newId}? O ideal é deixar somente este servo conectado ao barramento durante a alteração.`)) run({ op: 'set_id', old: sel, new: +newId });
      }}>Gravar ID</button></div>
    <span class="sv-label">Gravar registrador</span>
    <div class="sv-ctrl"><select value=${reg} onChange=${(e) => { const r = REGS.find((x) => x[0] === +e.target.value); setReg(+e.target.value); setSize(r ? r[2] : 1); setUnlock(r ? r[3] === 'EEPROM' : false); }}>
        ${REGS.map(([a, n, s, area]) => html`<option value=${a}>${a} · ${n} (${s} byte(s), ${area})</option>`)}</select>
      <input type="number" value=${val} onInput=${(e) => setVal(e.target.value)} placeholder="Valor" style="width:80px" />
      <label class="sv-inline"><input type="checkbox" checked=${unlock} onChange=${(e) => setUnlock(e.target.checked)} /> Desbloquear gravação</label>
      <button class=${DANGER[reg] ? 'btn-danger' : 'btn-light'} disabled=${!open || val === ''} onClick=${() => {
        if (DANGER[reg] && !window.confirm(`Atenção: ${DANGER[reg]}\nGravar o valor ${val} no registrador ${reg} do servo ${sel}?`)) return;
        run({ op: 'write_reg', id: sel, addr: +reg, size, value: +val, unlock });
      }}>Gravar</button></div>
    ${DANGER[reg] ? html`<span></span><p class="sv-warn">Registrador ${reg}: ${DANGER[reg]}</p>` : null}
    <span class="sv-label">Barramento</span>
    <div class="sv-ctrl">
      <button class="btn-light" disabled=${!open} onClick=${() => run({ op: 'timing', n: 200 }, 30000)}>Teste de temporização ×200</button>
      <button class="btn-light" disabled=${!open} onClick=${() => run({ op: 'scan_all' }, 30000)}>Verificar todos os IDs (0–253)</button>
      <input type="text" value=${scanIds} onInput=${(e) => setScanIds(e.target.value)} style="width:140px" />
      <button class="btn-light" disabled=${!open} onClick=${() => run({ op: 'scan', ids: scanIds })}>Verificar</button>
    </div>
    ${out ? html`<span></span><${ToolOut} out=${out} />` : null}
  </section>`;
}

function ToolOut({ out }) {
  if (out.op === 'note') return html`<p class="sv-small">${out.text}</p>`;
  if (out.op === 'timing') return html`<p class="sv-out num">Temporização: ${out.n} × ${out.ids} servos · mínimo ${out.min_ms} ms · média ${out.avg_ms} ms · p99 ${out.p99_ms} ms · máximo ${out.max_ms} ms · leituras perdidas ${out.fails}</p>`;
  if (out.op === 'scan' || out.op === 'scan_all') return html`<p class="sv-out">${out.found.length} servos conectados: ${out.found.join(', ') || 'nenhum'}${out.lost?.length ? `; sem resposta: ${out.lost.join(', ')}` : ''}</p>`;
  if (out.op === 'set_id') return html`<p class="sv-out">${out.ok ? 'Concluído; o novo ID respondeu ao ping.' : 'O novo ID não respondeu ao ping.'}</p>`;
  if (out.op === 'write_reg') return html`<p class="sv-out">Antes ${out.old} → leitura de retorno ${out.new}${out.same ? ' ✓' : ' (o valor lido difere do valor gravado)'}</p>`;
  if (out.op === 'dump') {
    const md = ['| Endereço | Nome | Área | Valor |', '|---|---|---|---|', ...out.rows.map((r) => `| ${r.addr} | ${r.name} | ${r.area} | ${r.value} |`)].join('\n');
    const download = () => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], { type: 'application/json' }));
      a.download = `HD-1910-id${out.id}-regs-${new Date().toISOString().slice(0, 10)}.json`; a.click();
    };
    return html`<div class="sv-out">
      <div class="sv-ctrl"><b>Registradores do servo #${out.id}</b><button class="btn-light" onClick=${download}>Baixar JSON</button>
        <button class="btn-light" onClick=${() => navigator.clipboard?.writeText(md)}>Copiar tabela Markdown</button></div>
      <div class="sv-dump">${out.rows.map((r) => html`<span class=${DANGER[r.addr] ? 'danger' : ''}><i>${r.addr}</i> ${r.name} <b class="num">${r.value}</b></span>`)}</div>
    </div>`;
  }
  return null;
}

function LogBox({ link }) {
  const [items, setItems] = useState([]);
  useEffect(() => link.on((m) => {
    if (m.t === 'log' && ['\u603b\u7ebf', '\u6821\u51c6', '\u5b89\u5168', '\u547d\u4ee4'].includes(m.entry.cat)) setItems((xs) => [m.entry, ...xs].slice(0, 60));
  }), []);
  return html`<div class="sv-logwrap">
    <div class="sv-label">Registros <span class="sv-small">(barramento, calibração e segurança; todos estão na página “Registros” à esquerda)</span></div>
    <div class="sv-log">${items.length ? items.map((e) => html`<div key=${e.n} class=${e.level}><span class="num">${e.t}</span> [${e.cat}] ${e.msg}${e.raw ? html` <small>${e.raw}</small>` : null}</div>`)
      : html`<span class="sv-small">Nenhum registro disponível.</span>`}</div>
  </div>`;
}

function CalibDialog({ plan, onOk, onCancel }) {
  const big = plan.rows.filter((r) => r.diff_deg != null && Math.abs(r.diff_deg) > plan.big_deg);
  return html`<div class="sv-modal" role="dialog" aria-modal="true">
    <div class="board sv-modal-box">
      <h2>Calibração da posição zero (referência oficial: 2048)</h2>
      <p class="sv-small">Posicione o MicroDuck na posição zero oficial: pernas estendidas, cabeça alinhada e boca fechada. O torque de cada servo é desativado por alguns milissegundos e reativado ao terminar. ${plan.sim ? '(Demonstração: sem servos conectados; calibração simulada.)' : ''}</p>
      <table class="sv-plan"><thead><tr><th>Servo</th><th class="r">Atual</th><th class="r">Definido como</th><th class="r">Diferença</th></tr></thead>
        <tbody>${plan.rows.map((r) => html`<tr class=${big.includes(r) ? 'big' : ''}><td>${r.id}</td><td class="r num">${fmt(r.pos)}</td>
          <td class="r num">2048</td><td class="r num">${r.diff_deg == null ? 'Indisponível' : sign(r.diff_deg) + '°'}</td></tr>`)}</tbody></table>
      ${big.length ? html`<p class="sv-warn">${big.length} servos têm diferença superior a ${plan.big_deg}°. Uma rotação de meia volta ao montar o disco estriado é normal; se a direção ± estiver invertida, a posição zero gravada ficará incorreta.</p>` : null}
      <div class="sv-modal-btns"><button class="btn-light" onClick=${onCancel}>Cancelar</button>
        <button class="btn-dark" onClick=${() => { if (!big.length || window.confirm(`${big.length} servos têm diferença superior a ${plan.big_deg}°. Deseja calibrar usando as posições atuais?`)) onOk(); }}>Confirmar calibração de ${plan.rows.length} servos</button></div>
    </div>
  </div>`;
}

// ---------------- Página ----------------

// “Devolver ao programa principal” usa confirmação em duas etapas (TwoStep de confirm.js).
// O botão de confirmação aparece ao lado do primeiro clique; clique nele após 700 ms e dentro de 3 s.
// O backend aguarda as operações pendentes, libera e confirma os 15 servos, fecha o barramento e inicia o programa principal, se o assistente estiver disponível.
// A devolução libera os servos imediatamente pelo Studio.
const HANDBACK_ASK = 'Devolver: os 15 servos serão liberados agora e o MicroDuck ficará sem sustentação. Segure ou apoie o robô antes de continuar.';
export function HandBackButton({ link }) {
  const [err, setErr] = useState(null);
  const confirm = async () => {
    setErr(null);
    const r = await link.cmd('servo.close', {}, 90000);     // O assistente aguarda as quatro etapas de inicialização do programa principal (até 60 s).
    if (!r.ok) setErr(r.reason || r.error || 'Não foi possível devolver o controle.');
  };
  return html`<span class="sv-handback"><${TwoStep} label="Devolver ao programa principal" ask=${HANDBACK_ASK} busyLabel="Devolvendo…" onConfirm=${confirm} />${
    err ? html`<span class="sv-warn">${err}</span>` : null}</span>`;
}

export function ServoPage({ sv, link, leaveGuards }) {
  const [pose, setPose] = useState('live');
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [hint, setHint] = useState(null);
  const [motion, setMotion] = useState({ seconds: 2, mode: 'profile', acc: 30 });
  const [follow, setFollow] = useState(true);
  const [poses, setPoses] = useState([]);
  const [idle, setIdle] = useState(false);
  const [plan, setPlan] = useState(null);
  const [syncKey, setSyncKey] = useState(0);
  const open = sv?.state === 'open';
  // Alinha os controles deslizantes às leituras reais atuais; normalmente isso também ocorre 0,6 s após soltar.
  const syncSliders = useCallback(() => { setSyncKey((k) => k + 1); setHint('Controles alinhados à posição atual.'); }, []);
  const dirs = Object.fromEntries((sv?.rows || []).map((r) => [r.id, r.dir]));

  // Mantenha estas funções estáveis com useCallback: cada linha só é redesenhada quando seus dados mudam.
  const onSelect = useCallback((id) => setSelected(id), []);
  // Operações dos servos: falhas aparecem no cabeçalho; quiet evita mensagens para operações frequentes dos controles deslizantes.
  const op = useCallback(async (args, timeout = 15000, quiet = false) => {
    const r = await link.cmd('servo.op', args, timeout);
    if (!r.ok) setMsg(r.reason || r.error || 'A operação falhou.');
    else if (!quiet) setMsg(null);
    return r;
  }, []);
  const run = async (name, args = {}) => {
    setBusy(true); setMsg(null);
    const r = await link.cmd(name, args, 15000);
    setBusy(false);
    if (!r.ok) setMsg(r.reason || r.error || 'A operação falhou.');
  };
  // A página assume o controle ao abrir. Ao sair, a sessão permanece se algum servo estiver mantendo torque;
  // sem servos ativos, o controle é devolvido automaticamente. O aviso fixo informa quando a sessão continua aberta.
  // Para devolver manualmente, use “Devolver ao programa principal” e confirme em duas etapas.
  const [ports, setPorts] = useState(null);       // {ports, port, sim}: seleciona a porta serial ao conectar um adaptador USB para TTL ao computador.
  const [pick, setPick] = useState('');
  const loadPorts = async () => {
    const r = await link.cmd('servo.ports', {}, 5000);
    if (r.ok) { setPorts(r.data); setPick((p) => p || (r.data.sim ? 'sim' : r.data.port || '')); }
    return r.ok ? r.data : null;
  };
  useEffect(() => {
    // Com porta serial configurada (no robô, /dev/ttyS2) ou modo simulado, assume ao abrir; no computador, aguarda a seleção da porta e o clique em “Conectar”.
    let alive = true;
    link.whenOpen().then(() => loadPorts()).then((d) => { if (alive && d && (d.port || d.sim)) run('servo.open'); });
    // Ao sair, o backend verifica se algum servo ainda está mantendo torque; devolve o controle somente se nenhum estiver ativo.
    return () => { alive = false; link.cmd('servo.close', { if_idle: true }, 15000); };
  }, []);
  calibHandler = useCallback(async (ids) => {
    const text = Array.isArray(ids) ? ids.join(',') : String(ids);
    const r = await op({ op: 'calib_plan', ids: text });
    if (r.ok) setPlan({ ...r.data, ids: text });
  }, []);
  useEffect(() => { if (open) op({ op: 'poses' }).then((r) => r.ok && setPoses(r.data.poses)); else setIdle(false); }, [open]);
  useEffect(() => { if (!hint) return undefined; const t = setTimeout(() => setHint(null), 4000); return () => clearTimeout(t); }, [hint]);

  const dr = sv?.drop_rate;
  return html`<div class="sv-page">
    <header class="sv-head">
      <div class="sv-titles">
        <div class="sv-titleline">
          <h1>Servos</h1>
          ${sv?.rows ? html`<div class="sv-stats num">
            <div><b>${sv.online}<small>/${sv.total}</small></b><span>Conectados</span></div>
            <div><b>${fmt(sv.avg_volts, 1)}<small> V</small></b><span>Tensão média</span></div>
            <div><b>${open ? fmt(sv.hz, 0) : '—'}<small> Hz</small></b><span>Atualização</span></div>
            <div><b>${open && dr != null ? (dr * 100).toFixed(1) : '—'}<small> %</small></b><span>Quadros perdidos</span></div>
            <div><b>${sv.holding}</b><span>Mantendo posição</span></div>
          </div>` : null}
        </div>
        <div class="sv-sub">${open
          ? html`<b class="sv-live">Ajustando servos</b> · ${sv.port} · Programa principal pausado; controle indisponível${sv.latched ? ' · todos os servos liberados' : ''} · os servos continuam ativos ao sair; clique em “Devolver ao programa principal” para devolver o controle
            <${HandBackButton} link=${link} />`
          : busy ? 'Assumindo o barramento dos servos…'
            : html`Controle não assumido · somente leitura`}
        <span class="sv-port">Porta serial
          <select value=${pick} onFocus=${loadPorts} onChange=${(e) => setPick(e.target.value)} disabled=${open}
            title=${open ? 'Não é possível trocar a porta durante o ajuste dos servos; devolva o controle ao programa principal primeiro.' : ''}>
            <option value="">Selecione uma porta…</option>
            ${(ports?.ports || []).map((p) => html`<option value=${p.device}>${p.device}${p.desc ? ` · ${p.desc}` : ''}</option>`)}
            ${ports?.port && !(ports.ports || []).some((p) => p.device === ports.port) ? html`<option value=${ports.port}>${ports.port}</option>` : null}
            <option value="sim">Demonstração (sem servos conectados)</option>
          </select>
          <button class="btn-light" disabled=${open || busy || !pick} onClick=${() => run('servo.open', { port: pick })}
            title=${open ? 'Não é possível trocar a porta durante o ajuste dos servos; devolva o controle ao programa principal primeiro.' : ''}>${open ? 'Trocar' : 'Conectar'}</button>
        </span></div>
        ${open && sv.gains ? html`<${GainsLine} g=${sv.gains} />` : null}
      </div>
      <div class="sv-actions">
        <${Toolbar} open=${open} op=${op} link=${link} motion=${motion} setMotion=${setMotion} idle=${idle} setIdle=${setIdle}
          follow=${follow} setFollow=${setFollow} poses=${poses} setHint=${setHint} syncSliders=${syncSliders}
          main=${null} />
      </div>
    </header>
    ${msg || sv?.error ? html`<div class="banner bad" role="alert"><b>${msg || 'Não foi possível abrir o barramento dos servos.'}</b><span class="more">${msg ? '' : sv?.error || ''}</span>
      <a href="#" onClick=${(e) => { e.preventDefault(); setMsg(null); }}>Entendi</a></div>` : null}
    ${sv?.marker_error ? html`<div class="banner warn" role="status"><b>Não foi possível gravar o marcador da sessão</b>
      <span class="more">${sv.marker_error}</span></div>` : null}
    ${hint ? html`<div class="banner warn" role="status"><span>${hint}</span></div>` : null}
    <div class="sv-main">
      <div class="sv-left">
        <${ServoStage} sv=${sv} pose=${pose} setPose=${setPose} selected=${selected} onSelect=${onSelect} />
        ${pose === 'zero' ? html`<${Why} />` : null}
      </div>
      <div class="sv-right">
        <${CalibCard} open=${open} op=${op} selected=${selected} onSelect=${onSelect} rows=${sv?.rows} />
        <${ServoList} key=${'list' + syncKey} sv=${sv || { rows: [] }} open=${open} selected=${selected} onSelect=${onSelect} op=${op} follow=${follow} setHint=${setHint} />
      </div>
    </div>
    <${MoreArea} open=${open} op=${op} motion=${motion} setMotion=${setMotion} follow=${follow} setFollow=${setFollow}
      poses=${poses} setPoses=${setPoses} selected=${selected} onSelect=${onSelect} sv=${sv || { rows: [] }} dirs=${dirs} link=${link} />
    ${plan ? html`<${CalibDialog} plan=${plan} onCancel=${() => setPlan(null)} onOk=${async () => {
      const ids = plan.ids; setPlan(null);
      const r = await op({ op: 'calibrate', ids }, 60000);
      if (r.ok) {
        const d = r.data, bad = Object.keys(d.bad || {});
        setHint(`Calibração concluída: ${d.ok.length} servos calibrados${bad.length ? `; falha em ${bad.join(', ')} (consulte os registros)` : ''}. Os servos calibrados estão mantendo a posição.`);
      }
    }} />` : null}
  </div>`;
}
