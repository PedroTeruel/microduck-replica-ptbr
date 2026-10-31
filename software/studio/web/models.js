// A biblioteca de modelos só é atualizada após a confirmação do servidor; instalação, seleção e execução são estados distintos.
import { html, useState, useEffect, useLayoutEffect, useRef } from './vendor/preact-htm.module.js';
import { ConfirmBox } from './confirm.js';

if (typeof document !== 'undefined' && !document.getElementById('models-css')) {
  const sheet = document.createElement('link');
  sheet.id = 'models-css';
  sheet.rel = 'stylesheet';
  sheet.href = new URL('./models.css', import.meta.url).href;
  document.head.appendChild(sheet);
}

const BUTTONS = [
  { button: 'a', label: 'A' }, { button: 'x', label: 'X' },
  { button: 'lb', label: 'LB' }, { button: 'rb', label: 'RB' },
  { button: 'dpad_down', label: 'Direcional para baixo' },
];
const SKILL_SLOTS = ['sitstand', 'ground_pick', 'kick_left', 'kick_right', 'roulade'];
const CAPTURE_ROLES = { south: 'a', west: 'x', lb: 'lb', rb: 'rb', dd: 'dpad_down' };
const taskLabel = (item) => item?.task_label || ({ walk: 'Andar / manter posição', sitstand: 'Sentar / levantar',
  ground_pick: 'Abaixar-se para pegar um objeto', kick_left: 'Chute com a perna esquerda', kick_right: 'Chute com a perna direita', roulade: 'Cambalhota para a frente',
  stand: 'Ficar em pé sem apoio' }[item?.suggested_slot || item?.task]) || item?.task || 'Finalidade não confirmada';
const keyLabel = (button) => BUTTONS.find(b => b.button === button)?.label || button;
const itemName = (view, id) => view?.items?.find(item => item.id === id)?.name || '';
const slotName = (view, slot) => view?.slots?.find(s => s.slot === slot)?.label || slot;
const actionLabel = (view, slot) => {
  const s = view?.slots?.find(s => s.slot === slot);
  const name = itemName(view, s?.model_id);
  return name ? `${s.label} · ${name}` : s?.label || slot || 'Não atribuído';
};

export function modelState(item) {
  const states = item.installed ? ['Instalado'] : ['Arquivo indisponível'];
  if (item.slots?.length) states.push('Selecionado');
  if (item.running === true) states.push('Em execução');
  return states;
}

export function modelSlots(view, item) {
  // Mostra somente finalidades cuja compatibilidade foi confirmada pelo servidor; modelos não recebem acesso indiscriminado a todas as finalidades.
  const allowed = item.allowed_slots || (item.suggested_slot ? [item.suggested_slot] : []);
  return (view?.slots || []).filter(slot => allowed.includes(slot.slot));
}

export function bindingChoice(view, button, slot) {
  if (!BUTTONS.some(b => b.button === button) || !SKILL_SLOTS.includes(slot)) {
    return { valid: false, reason: 'Esta finalidade não pode ser atribuída a um botão de ação. Para caminhar, use os controles originais de ficar em pé e caminhar.' };
  }
  const target = view?.slots?.find(s => s.slot === slot);
  if (!target?.model_id || target.error) return { valid: false, reason: 'Selecione primeiro um modelo disponível para esta ação.' };
  const current = view?.bindings?.find(b => b.button === button);
  const occupied = Boolean(current?.slot || current?.skill);
  const already = current?.slot === slot;
  const currentLabel = current?.slot ? actionLabel(view, current.slot) : current?.skill || 'Não atribuído';
  return { valid: true, already, conflict: occupied && !already,
    currentLabel, targetLabel: actionLabel(view, slot) };
}

export function operationAvailability(view) {
  const c = view?.capabilities || {};
  return { import: c.import === true, select: c.select === true,
    rename: c.rename === true, delete: c.delete === true,
    reason: c.reason || view?.error || 'Ainda não foi possível obter o estado do gerenciamento de modelos. Atualize a página e tente novamente.' };
}

export function captureKey(previous, live) {
  if (!previous || live?.state !== 'attached' || (live.last_ms != null && live.last_ms > 1500)) return null;
  const pressed = Object.keys(CAPTURE_ROLES).filter(role => live.buttons?.[role]);
  if (pressed.length !== 1 || previous[pressed[0]]) return null;
  return CAPTURE_ROLES[pressed[0]];
}

export function createModelReader(api) {
  let revision = 0;
  return {
    invalidate() { revision += 1; },
    async read() {
      const started = revision;
      try {
        const response = await api('/api/models');
        return started === revision ? response : null;
      } catch (error) {
        if (started === revision) throw error;
        return null;
      }
    },
  };
}

export function captureAllowed(view) {
  const rows = view?.bindings || [];
  const safeSkills = new Set(['', 'ground_pick', 'sit_toggle', 'kick_left', 'kick_right', 'roulade']);
  // A escuta paralela não intercepta as ações originais do padd; stand_test pode ativar os motores diretamente para levantar o robô quando estão sem força.
  return rows.length === BUTTONS.length && BUTTONS.every(({ button }) => {
    const matches = rows.filter(row => row.button === button);
    return matches.length === 1 && !matches[0].error && safeSkills.has(matches[0].skill);
  });
}

function ModelItem({ item, view, cap, busy, onOp, onConfirm, onBind }) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(item.name || '');
  const allowed = modelSlots(view, item);
  const [chosen, setChosen] = useState(allowed[0]?.slot || '');
  useEffect(() => { if (!renaming) setName(item.name || ''); }, [item.name, renaming]);
  const selectedSlot = allowed.find(s => s.slot === chosen) || allowed[0];
  const selected = (item.slots || []).map(slot => slotName(view, slot));
  const bound = (item.buttons || []).map(b => keyLabel(typeof b === 'string' ? b : b.button));
  const bindable = (item.slots || []).filter(slot => SKILL_SLOTS.includes(slot));
  const current = selectedSlot?.model_id === item.id;
  const removeReason = item.reason || (item.slots?.length ? 'Este modelo ainda está em uso. Selecione outro modelo ou restaure o modelo integrado antes de excluí-lo.' : 'Não é possível excluir agora.');
  return html`<article class="models-item" data-model-id=${item.id} data-model-name=${item.name} aria-label=${`Modelo ${item.name}`}>
    <div class="models-item-head">
      <div class="models-item-title"><h3 data-model-title>${item.name}</h3><span class="models-source">${item.source === 'builtin' ? 'Integrados' : 'Importado pelo usuário'}</span></div>
      <div class="models-tags">${modelState(item).map(state => html`<span class=${`models-tag ${state === 'Em execução' ? 'running' : state === 'Selecionado' ? 'selected' : ''}`}>${state}</span>`)}</div>
    </div>
    <p class="models-purpose">Finalidade: ${taskLabel(item)}</p>
    ${selected.length ? html`<p class="models-note">Em uso para: ${selected.join(', ')}${bound.length ? ` · Botões do controle: ${bound.join(', ')}` : ''}</p>` : null}
    ${renaming ? html`<form class="models-rename" onSubmit=${async e => {
      e.preventDefault();
      if (await onOp({ op: 'rename', id: item.id, name: name.trim() }, 'Nome salvo')) setRenaming(false);
    }}>
      <label>Nome de exibição<input type="text" value=${name} maxLength="80" aria-label=${`Nome do modelo ${item.name}`} onInput=${e => setName(e.target.value)} disabled=${busy} /></label>
      <button class="models-btn primary" type="submit" disabled=${busy || !cap.rename || !name.trim()}>Salvar nome</button>
      <button class="models-btn" type="button" disabled=${busy} onClick=${() => setRenaming(false)}>Cancelar renomeação</button>
    </form>` : null}
    <div class="models-item-actions">
      ${allowed.length > 1 ? html`<label class="models-slot-choice">Usar em<select value=${selectedSlot?.slot} aria-label=${`Finalidade de ${item.name}`} onChange=${e => setChosen(e.target.value)} disabled=${busy || !cap.select}>
        ${allowed.map(s => html`<option value=${s.slot}>${s.label}</option>`)}
      </select></label>` : null}
      <button class=${`models-btn ${current ? '' : 'primary'}`} type="button" data-model-action="select" aria-label=${`Usar ${item.name}`}
        disabled=${busy || !cap.select || !item.installed || !selectedSlot || current}
        title=${!cap.select ? cap.reason : current ? 'Este modelo já está selecionado para esta finalidade' : !selectedSlot ? 'Nenhuma finalidade compatível disponível' : `Usar como${selectedSlot.label}`}
        onClick=${() => onOp({ op: 'select', id: item.id, slot: selectedSlot.slot }, `“${item.name}” foi selecionado; nenhuma ação será iniciada automaticamente`)}>${current ? 'Selecionado' : 'Usar este modelo'}</button>
      <button class="models-btn" type="button" aria-label=${`Renomear ${item.name}`} disabled=${busy || !cap.rename} onClick=${() => setRenaming(!renaming)}>Renomear</button>
      ${bindable.length ? html`<button class="models-btn" type="button" data-model-action="bind" aria-label=${`Configurar botão para ${item.name}`} disabled=${busy || !cap.select}
        onClick=${() => onBind(bindable[0])}>Configurar botão</button>` : null}
      ${item.source !== 'builtin' ? html`<button class="models-btn danger" type="button" data-model-action="delete" aria-label=${`Excluir ${item.name}`}
        disabled=${busy || !cap.delete || !item.can_delete} title=${!item.can_delete ? removeReason : !cap.delete ? cap.reason : undefined}
        onClick=${() => onConfirm({ title: `Excluir “${item.name}”?`, lines: ['Para usar novamente após a exclusão, será necessário importar o pacote do modelo outra vez.'],
          label: 'Confirmar exclusão', args: { op: 'delete', id: item.id }, success: 'Modelo excluído' })}>Excluir</button>` : null}
    </div>
    ${item.source !== 'builtin' && !item.can_delete ? html`<p class="models-note">Não é possível excluir: ${removeReason}</p>` : null}
    ${!item.installed && item.reason ? html`<p class="models-error">${item.reason}</p>` : null}
    <details class="models-details"><summary>Detalhes do modelo</summary><dl>
      <dt>Finalidade</dt><dd>${taskLabel(item)}</dd>
      <dt>Impressão digital do arquivo</dt><dd>${item.sha12 || item.sha256 || 'Não informado'}</dd>
      ${item.path ? html`<dt>Local do arquivo</dt><dd>${item.path}</dd>` : null}
      ${item.rounds != null ? html`<dt>Ciclos de treinamento</dt><dd>${item.rounds}</dd>` : null}
      ${item.commit ? html`<dt>Versão de treinamento</dt><dd>${item.commit}</dd>` : null}
      <dt>Identificador</dt><dd>${item.id}</dd>
    </dl></details>
  </article>`;
}

function BindingRow({ binding, view, busy, cap, preset, onBind, onOp }) {
  const candidates = (view.slots || []).filter(s => SKILL_SLOTS.includes(s.slot) && s.model_id && !s.error);
  const [slot, setSlot] = useState(binding?.slot || '');
  const button = binding.button;
  useEffect(() => { setSlot(binding.slot || ''); }, [binding.slot]);
  useEffect(() => { if (preset?.slot) setSlot(preset.slot); }, [preset?.tick]);
  const choice = bindingChoice(view, button, slot);
  const current = binding.slot ? actionLabel(view, binding.slot) : binding.skill || 'Não atribuído';
  return html`<div class="models-binding" data-button=${button}>
    <div class="models-binding-current"><kbd>${keyLabel(button)}</kbd><span>${current}</span></div>
    <div class="models-binding-controls">
      <select value=${slot} aria-label=${`Atribuir ação ao botão ${keyLabel(button)}`} disabled=${busy || !cap.select} onChange=${e => setSlot(e.target.value)}>
        <option value="">Selecione uma ação…</option>${candidates.map(s => html`<option value=${s.slot}>${actionLabel(view, s.slot)}</option>`)}
      </select>
      <button class="models-btn" type="button" data-model-action="bind" aria-label=${`Configurar botão ${keyLabel(button)}`} disabled=${busy || !cap.select || !choice.valid || choice.already}
        onClick=${() => onBind(button, slot)}>${choice.already ? 'Atribuído' : 'Atribuir'}</button>
      <button class="models-btn" type="button" aria-label=${`Remover atribuição do botão ${keyLabel(button)}`} disabled=${busy || !cap.select || !(binding.slot || binding.skill)}
        onClick=${() => onOp({ op: 'unbind', button }, `A atribuição do botão ${keyLabel(button)} foi removida`)}>Remover atribuição</button>
    </div>
  </div>`;
}

export function ModelsPage({ api, csrf, link, live }) {
  const [view, setView] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState('');
  const [message, setMessage] = useState(null);
  const [file, setFile] = useState(null);
  const [name, setName] = useState('');
  const [upload, setUpload] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [preset, setPreset] = useState(null);
  const [capture, setCapture] = useState(null);
  const [captureNote, setCaptureNote] = useState('');
  const [seconds, setSeconds] = useState(20);
  const [stableBindings, setStableBindings] = useState('');
  const mounted = useRef(true);
  const working = useRef(false);
  const refreshing = useRef(false);
  const fileInput = useRef(null);
  const request = useRef(null);
  const reader = useRef(null);
  if (!reader.current) reader.current = createModelReader(api);
  const confirmArea = useRef(null);
  const bindingsArea = useRef(null);

  const load = async (quiet = false) => {
    if (refreshing.current || working.current) return;
    refreshing.current = true;
    if (!quiet) setLoading(true);
    try {
      const r = await reader.current.read();
      if (!r) return;
      if (!r.ok || !r.data) throw new Error(r.error || (r.status === 401 ? 'A sessão expirou. Entre novamente.' : 'Não foi possível obter o estado do gerenciamento de modelos.'));
      if (mounted.current) { setView(r.data); setLoadError(''); }
    } catch (e) {
      if (mounted.current) setLoadError(e.name === 'AbortError' ? 'O tempo para carregar a lista de modelos se esgotou. Atualize a página e tente novamente.' : e.message || 'Falha na conexão. Atualize a página e tente novamente.');
    } finally {
      refreshing.current = false;
      if (mounted.current) setLoading(false);
    }
  };
  useEffect(() => {
    mounted.current = true;
    load();
    const timer = setInterval(() => { if (document.visibilityState !== 'hidden') load(true); }, 5000);
    return () => { mounted.current = false; clearInterval(timer); request.current?.abort(); };
  }, []);
  useEffect(() => {
    if (confirm) { confirmArea.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
  }, [confirm]);

  const captureFingerprint = JSON.stringify((view?.bindings || []).map(({ button, skill, error }) => [button, skill, error]));
  const safeCapture = captureAllowed(view);
  useEffect(() => {
    if (!safeCapture) { setStableBindings(''); return undefined; }
    // O padd relê as atribuições a cada segundo, dando tempo para atualizar ações especiais antigas já gravadas, mas ainda não aplicadas.
    const timer = setTimeout(() => setStableBindings(captureFingerprint), 2000);
    return () => clearTimeout(timer);
  }, [captureFingerprint, safeCapture]);
  const rawCap = { ...operationAvailability(view), capture: safeCapture && stableBindings === captureFingerprint };
  const cap = loadError ? { ...rawCap, import: false, select: false, rename: false, delete: false, reason: loadError } : rawCap;
  const busy = Boolean(pending) || Boolean(capture);
  const onOp = async (args, success) => {
    if (working.current) return false;
    setCapture(null);
    reader.current.invalidate();
    working.current = true;
    setPending('Salvando e confirmando…');
    setMessage(null);
    try {
      const r = await api('/api/models/op', args, 60000);
      if (!r.ok || !r.data) throw new Error(r.error || 'A operação não foi concluída. Atualize a página para conferir o estado atual.');
      if (mounted.current) { setView(r.data); setLoadError(''); setMessage({ kind: 'ok', text: success }); }
      return true;
    } catch (e) {
      if (mounted.current) setMessage({ kind: 'bad', text: e.name === 'AbortError' ? 'O tempo para confirmar o resultado se esgotou. Atualize a página para conferir o estado atual.' : e.message || 'Falha na conexão. Atualize a página para conferir o estado atual.' });
      return false;
    } finally {
      working.current = false;
      if (mounted.current) { setPending(''); setConfirm(null); }
    }
  };

  const doImport = async (e) => {
    e.preventDefault();
    if (working.current || !cap.import || !file) return;
    setMessage(null);
    if (!/\.(zip|tar\.gz|tgz)$/i.test(file.name)) {
      setMessage({ kind: 'bad', text: 'Selecione um pacote de modelo ZIP ou tar.gz. Um arquivo ONNX isolado não inclui as instruções de implantação; compacte-o primeiro.' });
      return;
    }
    working.current = true;
    reader.current.invalidate();
    setPending('Enviando pacote do modelo…');
    setUpload(0);
    try {
      const response = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        request.current = xhr;
        const query = new URLSearchParams({ filename: file.name });
        if (name.trim()) query.set('name', name.trim());
        xhr.open('POST', `/api/models/import?${query}`);
        xhr.withCredentials = true;
        xhr.setRequestHeader('Content-Type', 'application/octet-stream');
        xhr.setRequestHeader('X-CSRF', csrf || '');
        xhr.timeout = 180000;
        xhr.upload.onprogress = event => {
          if (!mounted.current) return;
          const percent = event.lengthComputable ? Math.round(event.loaded / event.total * 100) : null;
          setUpload(percent);
          setPending(percent === 100 ? 'Envio concluído. Validando e instalando…' : 'Enviando pacote do modelo…');
        };
        xhr.upload.onload = () => { if (mounted.current) { setUpload(100); setPending('Envio concluído. Validando e instalando…'); } };
        xhr.onload = () => {
          try { resolve({ status: xhr.status, ...JSON.parse(xhr.responseText) }); }
          catch { reject(new Error('O servidor não retornou um resultado válido. Atualize a página para confirmar se foi instalado.')); }
        };
        xhr.onerror = () => reject(new Error('A conexão de envio foi interrompida. Atualize a página para confirmar a instalação antes de tentar novamente.'));
        xhr.ontimeout = () => reject(new Error('O envio ou a validação excedeu o tempo limite. Atualize a página para confirmar a instalação antes de tentar novamente.'));
        xhr.onabort = () => reject(new Error('Envio cancelado.'));
        xhr.send(file);
      });
      if (!response.ok || !response.data) throw new Error(response.error || 'O modelo não foi instalado. Tente novamente.');
      if (mounted.current) {
        setView(response.data); setLoadError(''); setFile(null); setName('');
        if (fileInput.current) fileInput.current.value = '';
        setMessage({ kind: 'ok', text: 'Modelo instalado. A seleção atual só muda quando você escolhe “Usar este modelo”; a importação não inicia nenhuma ação automaticamente.' });
      }
    } catch (err) {
      if (mounted.current) setMessage({ kind: 'bad', text: err.message || 'O modelo não foi instalado.' });
    } finally {
      working.current = false; request.current = null;
      if (mounted.current) { setPending(''); setUpload(null); }
    }
  };

  const bind = (button, slot) => {
    const choice = bindingChoice(view, button, slot);
    if (!choice.valid) { setMessage({ kind: 'bad', text: choice.reason }); return; }
    if (choice.already) return;
    if (choice.conflict) {
      setConfirm({ title: `O botão ${keyLabel(button)} já está atribuído a uma ação`,
        lines: [`Atual: ${choice.currentLabel}`, `Novo: ${choice.targetLabel}`, 'Após a substituição, este botão deixará de acionar a ação anterior.'],
        label: 'Substituir atribuição', args: { op: 'bind', button, slot, replace: true }, success: `A atribuição do botão ${keyLabel(button)} foi atualizada` });
    } else onOp({ op: 'bind', button, slot }, `O botão ${keyLabel(button)} foi atribuído a “${choice.targetLabel}”`);
  };
  const jumpBind = slot => {
    if (!cap.select || !live || !link) {
      setMessage({ kind: 'bad', text: cap.reason || 'Conecte o MicroDuck e confirme que os motores estão sem força.' });
      return;
    }
    setPreset({ slot, tick: Date.now() });
    bindingsArea.current?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    if (!cap.capture) {
      setMessage({ kind: 'warn', text: safeCapture ? 'Verificando a configuração do controle. Você pode clicar em “Configurar botão” novamente mais tarde ou usar o menu abaixo.' : 'Há uma ação especial atribuída ou a configuração dos botões está incompleta. Use o menu abaixo para atribuir um botão.' });
      bindingsArea.current?.querySelector('select')?.focus({ preventScroll: true });
      return;
    }
    setCapture({ slot, started: Date.now() });
    setCaptureNote('Aguardando o controle… solte todos os botões e pressione um botão de ação.');
    setSeconds(20);
    bindingsArea.current?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };
  // Prepare o listener enquanto a mensagem de captura está visível para não perder o primeiro botão entre a renderização e o efeito comum.
  useLayoutEffect(() => {
    if (!capture || !link) return undefined;
    let previous = null;
    let released = false;
    let done = false;
    const cancel = text => {
      if (done) return;
      done = true;
      setCapture(null);
      if (text) setMessage({ kind: 'bad', text });
    };
    const visible = () => { if (document.visibilityState !== 'visible') cancel('Captura de botão cancelada: a página foi para segundo plano.'); };
    const watch = () => {
      if (!done && document.visibilityState === 'visible' && link.status === 'open') link.cmd('pad.op', { op: 'watch' }, 3000);
    };
    // Reutiliza apenas a frequência das amostras e a assinatura paralela; não assume o controle remoto nem envia comandos de ação ou movimento.
    link.setPadCapture(true);
    watch();
    const off = link.on(message => {
      if (done) return;
      if (message.t === '_status' && message.status !== 'open') { cancel('Captura de botão cancelada: a conexão com o MicroDuck foi interrompida.'); return; }
      if (message.t === 'state' && (message.estop?.state !== 'confirmed' || message.robotd_ok === false)) {
        cancel('Captura de botão cancelada: confirme primeiro que os motores do MicroDuck estão sem força.'); return;
      }
      if (message.t !== 'pad') return;
      const input = message.live;
      if (input?.state !== 'attached') {
        previous = null; released = false;
        setCaptureNote('Controle físico ainda não detectado. Conecte o controle e pressione um botão ou cancele para usar o menu abaixo.');
        return;
      }
      const buttons = input.buttons || {};
      if (!released) {
        previous = { ...buttons };
        released = !Object.values(buttons).some(Boolean);
        setCaptureNote(released ? 'Pressione A, X, LB, RB ou o direcional para baixo; aguarde um instante e solte.' : 'Solte todos os botões do controle primeiro.');
        return;
      }
      const key = captureKey(previous, input);
      previous = { ...buttons };
      if (key) {
        done = true;
        setCapture(null);
        link.setPadCapture(false);
        bind(key, capture.slot);
      }
    });
    const timer = setInterval(() => {
      const left = Math.max(0, 20 - Math.floor((Date.now() - capture.started) / 1000));
      setSeconds(left);
      if (!left) cancel('O tempo de espera pelo botão se esgotou. Clique novamente em “Configurar botão” ou use o menu abaixo.');
    }, 250);
    const watchTimer = setInterval(watch, 2000);
    document.addEventListener('visibilitychange', visible);
    return () => { done = true; off(); clearInterval(timer); clearInterval(watchTimer); document.removeEventListener('visibilitychange', visible); link.setPadCapture(false); };
  }, [capture?.started]);
  useEffect(() => {
    if (capture && (!cap.select || !cap.capture || !live)) {
      setCapture(null);
      setMessage({ kind: 'bad', text: 'Captura de botão cancelada: mantenha a conexão e confirme que os motores do MicroDuck estão sem força.' });
    }
  }, [cap.select, cap.capture, live]);
  const items = view?.items || [];
  const groups = [['imported', 'Importado pelo usuário'], ['builtin', 'Integrados']];

  return html`<section class="models-page" aria-label="Gerenciamento de modelos" aria-busy=${busy || loading} data-capture-ready=${cap.capture ? 'true' : 'false'}>
    <header class="models-heading"><div><h1>Gerenciamento de modelos</h1><p>Instale modelos treinados no MicroDuck e escolha a finalidade e os botões do controle.</p></div>
      <button class="models-btn" type="button" aria-label="Atualizar lista de modelos" disabled=${busy || loading} onClick=${() => load()}>${loading ? 'Carregando…' : 'Atualizar'}</button>
    </header>
    ${loadError || view?.error ? html`<div class="models-notice bad" role="alert">${loadError || view.error}</div>` : null}
    ${view && !cap.select && cap.reason !== (loadError || view.error) ? html`<div class="models-notice warn" role="status">${cap.reason}</div>` : null}
    ${message ? html`<div class=${`models-notice ${message.kind}`} role=${message.kind === 'bad' ? 'alert' : 'status'}>${message.text}</div>` : null}
    ${busy ? html`<div class="models-notice progress" role="status">${pending}${upload != null && upload < 100 ? ` ${upload}%` : ''}
      ${upload != null ? html`<progress max="100" value=${upload} aria-label="Progresso do envio do modelo"></progress>` : null}</div>` : null}
    <div ref=${confirmArea}>${confirm ? html`<${ConfirmBox} lines=${[confirm.title, ...confirm.lines]} confirmLabel=${confirm.label} cancelLabel="Cancelar"
      busy=${busy} onCancel=${() => setConfirm(null)} onConfirm=${() => onOp(confirm.args, confirm.success)} cls="models-confirm" />` : null}</div>

    <section class="board models-panel" aria-label="Importar modelo">
      <h2>Importar modelo</h2><p class="models-note">Selecione no computador um pacote de modelo ZIP ou tar.gz. Os modelos integrados serão mantidos e poderão ser restaurados a qualquer momento.</p>
      <form class="models-import" onSubmit=${doImport}>
        <label class="models-file-field">Pacote do modelo<input ref=${fileInput} type="file" accept=".zip,.tar.gz,.tgz" aria-label="Importar pacote do modelo" disabled=${busy || !cap.import}
          onChange=${e => { setFile(e.target.files[0] || null); setMessage(null); }} /></label>
        <label>Nome de exibição (opcional)<input type="text" value=${name} maxLength="80" placeholder="Deixe em branco para usar o nome do pacote" aria-label="Nome do modelo" disabled=${busy || !cap.import}
          onInput=${e => setName(e.target.value)} /></label>
        <button class="models-btn primary" type="submit" aria-label="Importar modelo" disabled=${busy || !cap.import || !file}>Importar modelo</button>
      </form>
      ${view && !cap.import ? html`<p class="models-note models-warning">Não é possível importar no momento: ${view.capabilities?.import_reason || cap.reason}</p>` : null}
      <details class="models-details"><summary>Quais arquivos o pacote do modelo precisa conter?</summary><p>Compacte juntos policy.onnx, manifest.json e deployment-contract.json exportados na mesma implantação. Se houver deployment-execution.json, inclua-o também. A finalidade e a compatibilidade serão verificadas durante a importação.</p></details>
    </section>

    ${!view && loading ? html`<div class="board models-panel models-note">Carregando biblioteca de modelos…</div>` : null}
    ${view ? groups.map(([source, label]) => {
      const group = items.filter(item => item.source === source);
      return html`<section class="board models-panel" aria-label=${label}>
        <div class="models-section-head"><h2>${label}</h2><span class="models-count">${group.length} </span></div>
        ${group.length ? html`<div class="models-list">${group.map(item => html`<${ModelItem} key=${item.id} item=${item} view=${view} cap=${cap} busy=${busy}
          onOp=${onOp} onConfirm=${setConfirm} onBind=${jumpBind} />`)}</div>` : html`<p class="models-note">${source === 'imported' ? 'Nenhum modelo foi importado pelo usuário. Selecione um pacote acima para importar.' : 'Ainda não foi possível carregar os modelos integrados.'}</p>`}
      </section>`;
    }) : null}

    ${view ? html`<section class="board models-panel" aria-label="Finalidades atuais" data-model-slots>
      <h2>Finalidades atuais</h2><p class="models-note">“Selecionado” indica o modelo escolhido para a finalidade; “Em execução” só aparece durante uma ação. Trocar de modelo não ativa os motores automaticamente.</p>
      <div class="models-slot-list">${(view.slots || []).map(slot => html`<div class="models-slot" data-slot=${slot.slot}>
        <div><strong>${slot.label}</strong><p class="models-note">${itemName(view, slot.model_id) || (slot.path ? 'O modelo atual não consta na biblioteca' : 'Não instalado')}${slot.error ? html`<br /><span class="models-error">${slot.error}</span>` : null}</p></div>
        <button class="models-btn" type="button" data-model-action="restore" aria-label=${`Restaurar modelo integrado para ${slot.label}`} disabled=${busy || !cap.select || !slot.default_id || slot.is_default || slot.default_id === slot.model_id}
          title=${!cap.select ? cap.reason : !slot.default_id ? 'A configuração padrão desta finalidade não foi salva' : slot.is_default ? 'A configuração padrão já está em uso' : undefined}
          onClick=${() => setConfirm({ title: slot.default_disabled ? `Restaurar o estado padrão desativado de “${slot.label}”?` : `Restaurar o modelo integrado de “${slot.label}”?`,
            lines: [slot.default_disabled ? 'Nenhum modelo estava carregado para esta finalidade. A restauração a desativará; os modelos importados pelo usuário permanecerão na biblioteca.' : 'Os modelos importados pelo usuário permanecerão na biblioteca e as atribuições dos botões serão mantidas.'],
            label: slot.default_disabled ? 'Restaurar como desativado' : 'Restaurar modelo integrado', args: { op: 'restore', slot: slot.slot },
            success: `${slot.label} restaurado${slot.default_disabled ? 'estado padrão desativado' : 'modelo integrado'}` })}>${slot.default_disabled ? 'Restaurar como desativado' : 'Restaurar integrado'}</button>
      </div>`)}</div>
    </section>` : null}

    ${view ? html`<section ref=${bindingsArea} class="board models-panel models-bindings" aria-label="Botões do controle" id="models-bindings">
      <div class="models-section-head"><h2>Botões do controle</h2><button class="models-btn" type="button" aria-label="Restaurar atribuições padrão" disabled=${busy || !cap.select}
        onClick=${() => setConfirm({ title: 'Restaurar as atribuições padrão destes cinco botões?', lines: ['A, X, LB, RB e o direcional para baixo voltarão às ações padrão do programa principal. Os modelos selecionados não serão alterados.'],
          label: 'Restaurar atribuições padrão', args: { op: 'reset_bindings' }, success: 'Atribuições padrão dos botões restauradas' })}>Restaurar atribuições padrão</button></div>
      <p class="models-note">Primeiro selecione um modelo para a ação e depois escolha um botão. A atribuição acompanha o modelo selecionado para essa ação. Para andar, use os controles originais de ficar em pé e caminhar.</p>
      ${capture ? html`<div class="models-capture" role="status" aria-label="Aguardando botão do controle"><strong>Atribua um botão a “${slotName(view, capture.slot)}” · ${seconds} s</strong>
        <p>${captureNote}</p><button class="models-btn" type="button" aria-label="Cancelar captura do botão" onClick=${() => setCapture(null)}>Cancelar captura do botão</button></div>` : null}
      ${preset ? html`<p class="models-bind-hint" role="status">“${slotName(view, preset.slot)}” foi selecionado. Escolha um botão abaixo e clique em “Atribuir”.</p>` : null}
      ${BUTTONS.map(button => html`<${BindingRow} key=${button.button} binding=${{ ...button, ...(view.bindings || []).find(b => b.button === button.button) }}
        view=${view} busy=${busy} cap=${cap} preset=${preset} onBind=${bind} onOp=${onOp} />`)}
    </section>` : null}
  </section>`;
}
