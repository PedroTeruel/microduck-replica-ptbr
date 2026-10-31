import { html, useEffect, useRef, useState } from './vendor/preact-htm.module.js';
import { createMotionHeartbeat, isBackgroundMusic, motionTime } from './motion-heartbeat.js';
import { musicMotionLabel } from './audio-ui-state.js';

if (typeof document !== 'undefined' && !document.getElementById('motion-studio-css')) {
  const sheet = document.createElement('link');
  sheet.id = 'motion-studio-css'; sheet.rel = 'stylesheet';
  sheet.href = new URL('./motion-studio.css', import.meta.url).href;
  document.head.appendChild(sheet);
}

const LABELS = { idle: 'Pronto para iniciar', recording: 'Gravando', record_paused: 'Gravação pausada', draft: 'Rascunho para salvar',
  playing: 'Reproduzindo', play_paused: 'Reprodução pausada', idle_motion: 'Em movimento' };
const START = { record_start: 'recording', play: 'playing', idle_start: 'idle_motion' };
const RUNNING = new Set(['recording', 'record_paused', 'playing', 'play_paused', 'idle_motion']);

export function MotionStudio({ pad, link, activity }) {
  const motion = pad?.motion_studio;
  const [active, setActive] = useState(activity.active);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(null);
  const [name, setName] = useState('');
  const [selected, setSelected] = useState('');
  const [loops, setLoops] = useState(1);
  const [editing, setEditing] = useState(null);
  const [rename, setRename] = useState('');
  const [deleting, setDeleting] = useState(null);
  const focused = useRef(true), alive = useRef(false), epoch = useRef(0), busy = useRef(false);
  const expectedStop = useRef(false), lease = useRef(null);
  const currentMotion = useRef(motion), backgroundStart = useRef(false);
  currentMotion.current = motion;
  const state = motion?.state || 'idle';
  const owned = !!motion?.owner?.mine;
  const other = !!motion?.owner && !owned;
  const running = RUNNING.has(state);
  const recording = state === 'recording' || state === 'record_paused';
  const playing = state === 'playing' || state === 'play_paused';
  const clips = motion?.recordings || [];
  const chosen = clips.find(clip => clip.id === selected);
  const ready = active && link.status === 'open' && !pending && !other;

  useEffect(() => {
    alive.current = true;
    lease.current = createMotionHeartbeat({
      send: args => link.cmd('pad.op', args, 800),
      isActive: () => activity.active && focused.current,
      isConnected: () => link.status === 'open',
      onError: reason => { if (alive.current && !expectedStop.current) setError(reason); },
    });
    const interrupt = reason => {
      if (reason === 'inactive' && (backgroundStart.current ||
          (currentMotion.current?.owner?.mine && isBackgroundMusic(currentMotion.current)))) {
        lease.current?.interrupt(reason);
        return;
      }
      epoch.current += 1; busy.current = false; setPending(null);
      backgroundStart.current = false;
      lease.current?.interrupt(reason);
    };
    const offActivity = activity.subscribe(({ active: value }) => {
      setActive(value); if (!value) interrupt('inactive');
    });
    const offLink = link.on(message => { if (message.t === '_status' && message.status !== 'open') interrupt('disconnect'); });
    const blur = () => { focused.current = false; interrupt('inactive'); };
    const focus = () => { focused.current = true; };
    window.addEventListener('blur', blur); window.addEventListener('focus', focus);
    return () => {
      alive.current = false; epoch.current += 1;
      offActivity(); offLink(); window.removeEventListener('blur', blur); window.removeEventListener('focus', focus);
      lease.current?.dispose(); lease.current = null;
    };
  }, [link, activity]);

  useEffect(() => { lease.current?.sync(motion); }, [motion?.session_id, state, owned, motion?.idle_kind]);
  useEffect(() => {
    if (!clips.some(clip => clip.id === selected)) setSelected(clips[0]?.id || '');
  }, [clips, selected]);

  const command = async (action, params = {}) => {
    if (busy.current && action !== 'stop') return null;
    if (!activity.active || !focused.current || link.status !== 'open') { setError('Volte à área do controle e restabeleça a conexão para continuar.'); return null; }
    const mine = ++epoch.current;
    const startingBackground = action === 'idle_start' && params.kind === 'music' && !recording;
    backgroundStart.current = startingBackground;
    busy.current = true; setPending(action); setError(null);
    const ending = action === 'stop' || action === 'record_finish' || (action === 'idle_stop' && !recording);
    if (ending) expectedStop.current = true;
    else if (START[action]) expectedStop.current = false;
    try {
      const request = { op: 'motion', action,
        ...(motion?.session_id && RUNNING.has(state) ? { session_id: motion.session_id } : {}), ...params };
      const result = await link.cmd('pad.op', request, 8000);
      if (!alive.current || epoch.current !== mine ||
          (!startingBackground && (!activity.active || !focused.current))) {
        if (START[action] && result?.ok && result.data?.session_id) {
          void link.cmd('pad.op', { op: 'motion', action: 'stop', session_id: result.data.session_id }, 1000);
        }
        return null;
      }
      if (!result?.ok) { if (ending) expectedStop.current = false; setError(result?.reason || result?.error || 'Não foi possível concluir a ação.'); return result; }
      if (ending) lease.current?.sync(null);
      if (START[action] && result.data?.session_id) {
        lease.current?.sync({ state: action === 'idle_start' && recording ? state : START[action],
          idle_kind: action === 'idle_start' ? params.kind || 'lively' : null,
          session_id: result.data.session_id, owner: { mine: true } });
      }
      if (action === 'save') setName('');
      if (action === 'rename') setEditing(null);
      if (action === 'delete') setDeleting(null);
      return result;
    } catch (err) {
      if (alive.current && mine === epoch.current) setError(err?.message || 'A conexão foi interrompida durante a ação.');
      return null;
    } finally {
      if (alive.current && mine === epoch.current) {
        busy.current = false; backgroundStart.current = false; setPending(null);
      }
    }
  };
  const button = (action, label, enabled = true, params = {}, className = 'btn-light') => html`
    <button type="button" class=${className} data-motion=${action} data-motion-kind=${params.kind || null} disabled=${!ready || !enabled}
      onClick=${() => command(action, params)}>${pending === action ? 'Processando…' : label}</button>`;
  const idleCanStart = !running || state === 'recording';
  const hasDraft = state === 'draft' && !!motion?.draft;
  const max = recording ? 60 : Math.max(0.1, motion?.duration_s || 0.1);
  const progress = Math.max(0, Math.min(max, motion?.elapsed_s || 0));

  return html`<section id="motion-studio" class="pd-motion" data-state=${state} data-loop=${motion?.loop || 0} aria-label="Gravação e reprodução de movimentos">
    <div class="motion-heading"><h4>Gravação e reprodução de movimentos</h4>
      <span class=${`motion-state ${state === 'recording' ? 'is-recording' : ''}`} role="status">${musicMotionLabel(motion) || LABELS[state] || 'Estado não confirmado'}</span>
    </div>
      ${!motion ? html`<p class="pd-small-p">A função de movimentos ainda não está pronta. Verifique novamente após conectar.</p>` : html`
      ${other ? html`<p class="pd-small-p pd-why">${motion.owner.by || 'Outra página'} está usando os movimentos. Interrompa ou assuma o controle antes de continuar.</p>` : null}
      ${error || motion.error ? html`<p class="motion-error" role="alert">${error || motion.error}</p>` : null}
      ${motion.library_warning ? html`<p class="motion-library-warning" role="status">${motion.library_warning}</p>` : null}
      <div class="motion-toolbar">
        ${!recording && !playing && state !== 'draft' ? button('record_start', 'Iniciar gravação', motion.record_available?.ok) : null}
        ${state === 'recording' ? button('record_pause', 'Pausar gravação', owned) : null}
        ${state === 'record_paused' ? button('record_resume', 'Continuar gravação', owned) : null}
        ${recording ? button('record_finish', 'Finalizar gravação', owned) : null}
        ${motion.idle_running ? button('idle_stop', motion.idle_kind === 'music' ? 'Parar movimento ao som da música' : 'Parar movimento', owned) :
          button('idle_start', 'Movimento', idleCanStart && state !== 'draft' && motion.idle_available?.ok)}
        ${!motion.idle_running ? button('idle_start', 'Movimento ao som da música', idleCanStart && state !== 'draft' && motion.idle_available?.ok
          && pad?.audio?.available && pad?.audio?.listening && pad?.audio?.music, {kind:'music'}) : null}
        ${running ? html`<button type="button" class="motion-stop" data-motion="stop" disabled=${!active || !owned || link.status !== 'open'}
          onClick=${() => command('stop', { session_id: motion.session_id })}>Parar movimento atual</button>` : null}
      </div>
      ${motion.posture_step ? html`<p class="motion-posture" data-motion-posture=${motion.posture_step.target} role="status">
        ${motion.posture_step.label}</p>` : null}
      ${!running && !hasDraft && motion.record_available?.why ? html`<p class="pd-small-p pd-why">${motion.record_available.why}</p>` : null}
      ${!motion.idle_running && !motion.idle_available?.ok && motion.idle_available?.why && motion.idle_available.why !== motion.record_available?.why
        ? html`<p class="pd-small-p">Movimento: ${motion.idle_available.why}</p>` : null}
      ${running ? html`<div class="motion-progress"><progress max=${max} value=${progress} aria-label="Progresso do movimento"></progress>
        <span class="num">${motionTime(motion.elapsed_s)}${playing ? ` / ${motionTime(motion.duration_s)} · repetição ${motion.loop || 1}/${motion.loops || 1}` : recording ? ' / 1:00.0' : ''}</span></div>` : null}
      ${hasDraft ? html`<form class="motion-save" onSubmit=${e => { e.preventDefault(); void command('save', { name: name.trim() }); }}>
        <p>Gravação concluída: ${motionTime(motion.draft.duration_s)}${motion.draft.reason ? ` · ${motion.draft.reason}` : ''}</p>
        <label>Nome do movimento<input name="motion-name" value=${name} maxLength="32" placeholder="Ex.: Cumprimentar" autoComplete="off"
          onInput=${e => setName(e.currentTarget.value)} disabled=${!!pending || other} /></label>
        <div class="motion-toolbar">${button('save', 'Salvar movimento', !!name.trim(), { name: name.trim() }, 'btn-primary')}
          ${button('discard', 'Descartar gravação', !other)}</div>
      </form>` : null}
      <div class="motion-library">
        <div class="motion-heading"><b>Movimentos salvos</b><small>${clips.length} / 20</small></div>
        ${clips.length ? html`<label>Selecionar movimento<select aria-label="Selecionar movimento salvo" value=${selected} disabled=${running || !!pending || other}
          onChange=${e => { setSelected(e.currentTarget.value); setEditing(null); setDeleting(null); }}>
          ${clips.map(clip => html`<option key=${clip.id} value=${clip.id}>${clip.name} · ${motionTime(clip.duration_s)}</option>`)}
        </select></label>
        <div class="motion-toolbar"><label class="motion-repeat">Repetições<select aria-label="Número de repetições" value=${loops}
          disabled=${running || !!pending || other} onChange=${e => setLoops(Number(e.currentTarget.value))}>
          ${[1, 3, 5].map(count => html`<option value=${count}>${count} vez(es)</option>`)}</select></label>
          ${button('play', 'Iniciar reprodução', !!chosen && state === 'idle', { id: selected, loops }, 'btn-primary')}
          ${state === 'playing' ? button('pause', 'Pausar reprodução', owned) : null}
          ${state === 'play_paused' ? button('resume', 'Continuar reprodução', owned) : null}
        </div>
        ${chosen ? html`<p class="motion-clip-name">${chosen.name} <small>${motionTime(chosen.duration_s)}</small></p>
          <div class="motion-toolbar"><button type="button" class="btn-light" data-motion="rename_open" disabled=${!ready || running || hasDraft}
            onClick=${() => { setEditing(chosen.id); setRename(chosen.name); setDeleting(null); }}>Renomear</button>
          <button type="button" class="btn-light" data-motion="delete_open" disabled=${!ready || running || hasDraft}
            onClick=${() => { setDeleting(chosen.id); setEditing(null); }}>Excluir</button></div>` : null}
        ${editing && chosen?.id === editing ? html`<form class="motion-edit" onSubmit=${e => { e.preventDefault(); void command('rename', { id: editing, name: rename.trim() }); }}>
          <label>Novo nome<input name="motion-rename" value=${rename} maxLength="32" autoComplete="off" disabled=${!!pending}
            onInput=${e => setRename(e.currentTarget.value)} /></label><div class="motion-toolbar">
          ${button('rename', 'Salvar nome', !!rename.trim() && !running, { id: editing, name: rename.trim() })}
          <button type="button" class="btn-light" disabled=${!!pending} onClick=${() => setEditing(null)}>Cancelar renomeação</button></div>
        </form>` : null}
        ${deleting && chosen?.id === deleting ? html`<div class="motion-edit" role="group" aria-label="Confirmar exclusão do movimento">
          <p>Excluir “${chosen.name}”?</p><div class="motion-toolbar">${button('delete', 'Confirmar exclusão', !running, { id: deleting })}
          <button type="button" class="btn-light" disabled=${!!pending} onClick=${() => setDeleting(null)}>Manter movimento</button></div></div>` : null}`
          : html`<p class="pd-small-p">Ainda não há movimentos salvos. Grave um movimento e dê um nome a ele.</p>`}
      </div>
      ${motion.last_result ? html`<p class="pd-small-p motion-result" role="status">${motion.last_result}</p>` : null}
      <p class="pd-small-p motion-note">Cada gravação pode ter até 60 s. Os comandos e o ritmo são registrados, mas o trajeto pode variar durante a reprodução.
        É possível gravar o joystick, a cabeça, o corpo, o bico, sons e os movimentos de sentar e levantar; chutes, giros e ações de pegar objetos ainda não são gravados.
        Sentar e levantar são reproduzidos até a postura desejada, e a sequência aguarda a confirmação do estado. Parar cancela as etapas seguintes; um movimento de sentar ou levantar já iniciado será concluído pelo programa principal.
        O movimento simples executa apenas pequenos gestos da cabeça e do bico. Sair da área do controle, alternar para o segundo plano, tirar o foco ou perder a conexão interrompe os comandos seguintes; para continuar, inicie novamente.</p>
      <p class="pd-small-p motion-note">O movimento ao som da música acompanha o ritmo com pequenos gestos da cabeça; o corpo depende do modelo de movimento. Sem um ritmo nítido, o sistema aguarda. Quando a música ou a escuta para, o Microduck volta à posição inicial.
        Depois de iniciado de forma independente, o movimento continua ao tirar o foco, alternar para o segundo plano, sair da área do controle ou navegar para outra página. Fechar a página ou perder a conexão o interrompe.
        Durante uma gravação com música, mantenha a página em primeiro plano e a área do controle visível; sair dela interrompe a gravação. Volte para consultar o estado e parar o movimento.
        O movimento também para conforme as regras atuais de controle quando alguém usa o joystick da página, inicia outro movimento ou assume o controle físico.</p>
    `}
  </section>`;
}
