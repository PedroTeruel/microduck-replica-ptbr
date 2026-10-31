import { html, useState, useEffect, useRef } from './vendor/preact-htm.module.js';
import { CameraLink } from './camera-link.js';

if (typeof document !== 'undefined' && !document.getElementById('sensors-css')) {
  const sheet = document.createElement('link');
  sheet.id = 'sensors-css'; sheet.rel = 'stylesheet';
  sheet.href = new URL('./sensors.css', import.meta.url).href;
  document.head.appendChild(sheet);
}

const emptyTof = (state, reason, extra = {}) => ({ ...extra, state, reason, zones: [], valid_count: null, nearest_mm: null, farthest_mm: null });
const finite = n => typeof n === 'number' && Number.isFinite(n);

export function tofSnapshot(data) {
  if (!data || !['ready', 'waiting', 'unavailable', 'error'].includes(data.state)) return emptyTof('error', 'Dados retornados pelo ToF inválidos.');
  const info = { sensor: typeof data.sensor === 'string' ? data.sensor : null, simulated: data.simulated === true,
    hz: finite(data.hz) ? data.hz : null, seq: data.seq, age_ms: data.age_ms };
  if (data.state !== 'ready') return emptyTof(data.state, data.reason || '', info);
  if (data.rows !== 8 || data.cols !== 8 || !Array.isArray(data.distance_mm) || data.distance_mm.length !== 64 ||
    !Array.isArray(data.status) || data.status.length !== 64 || !data.distance_mm.every(finite) ||
    !data.status.every(n => Number.isInteger(n) && n >= 0 && n <= 255) || !finite(data.age_ms) || data.age_ms < 0) {
    return emptyTof('error', 'Formato do quadro ToF inválido. Aguardando a próxima leitura completa de 8 × 8.', info);
  }
  if (data.age_ms >= 3000) return emptyTof('stale', 'Leitura expirada. Aguardando um novo quadro ToF.', info);
  const zones = data.status.map((status, i) => {
    const raw_mm = data.distance_mm[i];
    const kind = status === 255 ? 'no_target' : (status === 5 || status === 9) && raw_mm > 0 ? 'range' : 'unusable';
    return { kind, mm: kind === 'range' ? raw_mm : null, status, raw_mm };
  });
  const values = zones.filter(z => z.kind === 'range').map(z => z.mm);
  return { ...info, state: 'ready', reason: '', zones, valid_count: values.length,
    nearest_mm: values.length ? Math.min(...values) : null, farthest_mm: values.length ? Math.max(...values) : null };
}

export function cameraSource(config, producer) {
  const configured = config?.source === 'test' ? 'Configuração: imagem de teste' : config?.source === 'camera' ? 'Configuração: câmera' : 'Origem da configuração desconhecida';
  const simulated = producer?.simulated === true || producer?.simulated === 'true';
  return { label: simulated ? `${configured} · dispositivo simulado no sistema` : configured, verified: false,
    note: config?.source === 'test' ? 'A configuração atual usa um padrão de teste. A reprodução do vídeo não confirma a conexão de uma câmera real.'
      : simulated ? 'O sistema está identificado explicitamente como um dispositivo simulado.'
        : 'A origem vem da configuração, que é somente leitura. Confira a imagem para confirmar se a câmera real está funcionando.' };
}

export function createTofReader({ request, onValue, intervalMs = 500, staleMs = 3000,
  now = () => performance.now(), setTimeout = globalThis.setTimeout, clearTimeout = globalThis.clearTimeout }) {
  let generation = 0, timer = null, staleTimer = null, controller = null, active = false;
  const stop = () => { active = false; generation++; clearTimeout(timer); clearTimeout(staleTimer); controller?.abort(); controller = null; };
  const read = async current => {
    if (!active || current !== generation) return;
    const requestStartedAt = now();
    controller = new AbortController();
    try {
      const result = await request(controller.signal);
      if (!active || current !== generation) return;
  if (!result?.ok) throw Error(typeof result?.error === 'string' ? result.error : 'Falha ao ler o ToF.');
      const data = result.data;
      const serverAge = data?.age_ms;
      const received = finite(serverAge) && serverAge >= 0
        ? { ...data, age_ms: serverAge + Math.max(0, now() - requestStartedAt) } : data;
      const value = tofSnapshot(received);
      clearTimeout(staleTimer);
      onValue({ ...value, receivedAt: now(), updatedAt: Date.now() });
      if (value.state === 'ready') staleTimer = setTimeout(() => {
        if (active && current === generation) onValue(emptyTof('stale', 'Leitura expirada. Aguardando um novo quadro ToF.'));
      }, Math.max(0, staleMs - value.age_ms));
    } catch (error) {
      if (active && current === generation) {
        clearTimeout(staleTimer);
        onValue(emptyTof('error', error?.name === 'AbortError' ? 'Tempo esgotado ao ler o ToF. Verifique a conexão com o serviço.' : error.message || 'Conexão com o ToF perdida.'));
      }
    } finally {
      if (active && current === generation) { controller = null; timer = setTimeout(() => read(current), intervalMs); }
    }
  };
  return { start() { stop(); active = true; onValue(emptyTof('loading', 'Lendo o ToF…')); read(generation); }, stop };
}

function useVisible() {
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden');
  useEffect(() => {
    const change = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', change);
    return () => document.removeEventListener('visibilitychange', change);
  }, []);
  return visible;
}

const uncheckedBand = (reason = 'Toque para ver detalhes') => ({ state: 'unknown', word: 'Não verificado', small: reason });
const checkingBand = () => ({ state: 'checking', word: 'Verificando', small: 'Apenas leitura do estado' });

export function cameraBandStatus(data) {
  if (data?.service_state === 'offline') return { state: 'offline', word: 'Desconectada', small: 'O serviço de vídeo não respondeu' };
  if (data?.service_state !== 'online') return uncheckedBand();
  if (data.source === 'test') return { state: 'test', word: 'Imagem de teste', small: 'Serviço de vídeo conectado' };
  return { state: 'online', word: 'Serviço conectado', small: data.source === 'camera' ? 'Toque para conferir a imagem' : 'Origem da imagem não confirmada' };
}

export function tofBandStatus(data) {
  const view = tofSnapshot(data);
  if (view.state === 'ready') return view.simulated ? { state: 'simulated', word: 'Dados simulados', small: 'Toque para ver o mapa de distância' }
    : { state: 'online', word: 'Conectado', small: 'Toque para ver o mapa de distância' };
  if (view.state === 'unavailable') return { state: 'offline', word: 'Desconectado', small: 'Sensor ou serviço indisponível' };
  if (view.state === 'waiting') return { state: 'waiting', word: 'Aguardando dados', small: 'Serviço respondeu' };
  if (view.state === 'stale') return uncheckedBand('A última leitura expirou');
  return { state: 'error', word: 'Falha na leitura', small: 'Toque para ver detalhes' };
}

/** Low-frequency presence checks only. No video pipeline or service-start requests. */
export function createSensorBandReader({ request, onValue, intervalMs = 10000, staleMs = 20000,
  now = () => performance.now(), setTimeout = globalThis.setTimeout, clearTimeout = globalThis.clearTimeout }) {
  let generation = 0, active = false, timer = null;
  const controllers = new Set(), expiry = new Map();
  let values = { camera: checkingBand(), tof: checkingBand() };
  const emit = (kind, value) => { values = { ...values, [kind]: value }; onValue(values); };
  const stop = () => {
    active = false; generation++; clearTimeout(timer);
    for (const timeout of expiry.values()) clearTimeout(timeout);
    expiry.clear(); for (const controller of controllers) controller.abort(); controllers.clear();
  };
  const readOne = async (kind, current) => {
    const controller = new AbortController(), started = now(); controllers.add(controller);
    let value;
    try {
      const result = await request(kind, controller.signal);
      if (!active || current !== generation) return;
      if (!result?.ok) throw Error('Falha na leitura');
      const elapsed = Math.max(0, now() - started), data = result.data;
      value = kind === 'camera' ? (elapsed >= staleMs ? uncheckedBand('O resultado da verificação expirou') : cameraBandStatus(data))
        : tofBandStatus(finite(data?.age_ms) && data.age_ms >= 0 ? { ...data, age_ms: data.age_ms + elapsed } : data);
    } catch {
      if (!active || current !== generation) return;
      value = { state: 'error', word: 'Falha na leitura', small: 'Toque para ver detalhes' };
    } finally { controllers.delete(controller); }
    if (!active || current !== generation) return;
    clearTimeout(expiry.get(kind)); emit(kind, value);
    expiry.set(kind, setTimeout(() => {
      if (active && current === generation) emit(kind, uncheckedBand('Estado expirado; aguardando nova verificação'));
    }, staleMs));
  };
  const read = async current => {
    await Promise.allSettled(['camera', 'tof'].map(kind => readOne(kind, current)));
    if (active && current === generation) timer = setTimeout(() => read(current), intervalMs);
  };
  return { start() {
    stop(); active = true; values = { camera: checkingBand(), tof: checkingBand() }; onValue(values); read(generation);
  }, stop };
}

export function SensorBandCells({ api, active }) {
  const visible = useVisible();
  const [values, setValues] = useState({ camera: checkingBand(), tof: checkingBand() });
  useEffect(() => {
    if (!active || !visible) { setValues({ camera: uncheckedBand(), tof: uncheckedBand() }); return; }
    const reader = createSensorBandReader({ request: (kind, signal) => api(`/api/${kind}`, undefined, 3500, signal), onValue: setValues });
    reader.start(); return () => reader.stop();
  }, [api, active, visible]);
  return ['camera', 'tof'].map(kind => html`<a key=${kind} href=${`#/${kind}`} class=${`band-sensor band-${kind}`} data-state=${values[kind].state}>
    <span class="label">${kind === 'camera' ? 'Câmera' : 'ToF'}</span>
    <span class="word">${values[kind].word}</span><span class="small">${values[kind].small}</span>
  </a>`);
}

const CAMERA_STATES = { loading: 'Lendo informações de conexão…', connecting: 'Conectando à câmera…', signaling: 'Sinalização conectada; aguardando a origem do vídeo…',
  negotiating: 'Negociando a conexão de vídeo…', receiving: 'Trilha de vídeo recebida; aguardando o primeiro quadro…', playing: 'Reproduzindo', stopped: 'Prévia interrompida', hidden: 'Prévia pausada', error: 'Falha na prévia',
  test: 'A origem de teste não está reproduzindo', offline: 'Desconectada', unknown: 'Origem não confirmada' };

export function inlineCameraPolicy(info) {
  if (info?.service_state === 'offline') return { play: false, state: 'offline', message: 'A imagem da câmera está indisponível. Ela aparecerá aqui quando houver conexão.' };
  if (info?.source === 'test') return { play: false, state: 'test', message: 'A imagem de teste está selecionada. A imagem aparecerá aqui quando uma câmera real estiver conectada.' };
  if (info?.source !== 'camera' || info?.service_state !== 'online') return { play: false, state: 'unknown', message: 'A origem da imagem da câmera ainda não foi confirmada. Confira na página da câmera.' };
  return { play: true };
}

function useCameraSession({ api, video, active = true, inline = false }) {
  const camera = useRef(null);
  const [config, setConfig] = useState(null), [connection, setConnection] = useState({ state: 'loading' });
  const [wanted, setWanted] = useState(true), [attempt, setAttempt] = useState(0);
  const visible = useVisible();
  useEffect(() => {
    if (!active || !visible || !wanted) {
      camera.current?.stop(!active || !visible ? 'hidden' : 'stopped');
      setConnection({ state: !active || !visible ? 'hidden' : 'stopped' });
      return;
    }
    const abort = new AbortController(); let disposed = false, retry = null;
    const transport = new CameraLink({ video: video.current, onState: setConnection });
    camera.current = transport;
    setConnection({ state: 'loading' });
    setConfig(null);
    const read = async () => {
      let info;
      try {
        const result = await api('/api/camera', undefined, 3500, abort.signal);
        info = result?.ok ? result.data : { source: 'unknown', error: result?.error || 'Falha ao ler as informações de conexão' };
      } catch (error) { info = { source: 'unknown', error: error.name === 'AbortError' ? 'Tempo esgotado ao ler as informações de conexão' : 'Falha ao ler as informações de conexão' }; }
      if (disposed) return;
      setConfig(info);
      if (inline) {
        const policy = inlineCameraPolicy(info);
        if (!policy.play) {
          setConnection({ state: policy.state, message: policy.message });
          retry = setTimeout(read, 10000);
          return;
        }
      }
      transport.start(info?.signaling_port ?? 8443);
    };
    read();
    return () => { disposed = true; clearTimeout(retry); abort.abort(); transport.stop(); if (camera.current === transport) camera.current = null; };
  }, [api, active, visible, wanted, attempt, inline]);
  return { config, connection, wanted, reconnect: () => { setWanted(true); setAttempt(n => n + 1); },
    stop: () => { camera.current?.stop(); setWanted(false); } };
}

function CameraScreen({ connection, video, compact = false }) {
  const screen = useRef(null), [ratio, setRatio] = useState(16 / 9);
  useEffect(() => {
    const measure = () => {
      const rect = screen.current?.getBoundingClientRect();
      if (rect?.width > 0 && rect?.height > 0) setRatio(old => Math.abs(old - rect.width / rect.height) < 0.001 ? old : rect.width / rect.height);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(screen.current); measure();
    return () => observer.disconnect();
  }, []);
  const rotate = connection.metadata?.rotate || 0;
  const width = connection.width || connection.metadata?.width || 640;
  const height = connection.height || connection.metadata?.height || 480;
  const sideways = rotate === 90 || rotate === 270;
  return html`<div ref=${screen} class="camera-screen" data-playing=${connection.state === 'playing'}
    style=${compact ? null : { aspectRatio: sideways ? `${height} / ${width}` : `${width} / ${height}`,
      maxWidth: `min(100%, ${72 * (sideways ? height / width : width / height)}vh)` }}>
    <video class=${compact ? 'inline-camera-video' : 'camera-video'} ref=${video} muted playsInline autoPlay aria-label="Imagem da câmera do MicroDuck"
      style=${{ width: sideways ? `${100 / ratio}%` : '100%', height: sideways ? `${100 * ratio}%` : '100%', transform: `translate(-50%, -50%) rotate(${rotate}deg)` }}></video>
    ${connection.state !== 'playing' ? html`<div class="camera-placeholder">${connection.error || connection.message || CAMERA_STATES[connection.state] || 'Aguardando imagem'}</div>` : null}
  </div>`;
}

export function InlineCamera({ api, active = false }) {
  const card = useRef(null), video = useRef(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const observer = new IntersectionObserver(entries => setInView(entries.some(entry => entry.isIntersecting)), { threshold: 0 });
    observer.observe(card.current);
    return () => observer.disconnect();
  }, []);
  const { config, connection, reconnect } = useCameraSession({ api, video, active: active && inView, inline: true });
  const source = cameraSource(config, connection.producer);
  return html`<section ref=${card} class="board pd-card inline-camera" aria-labelledby="inline-camera-title">
    <div class="inline-camera-head"><h3 id="inline-camera-title">Câmera</h3>
      <span class="sensor-pill inline-camera-status" role="status" data-state=${connection.state}>${CAMERA_STATES[connection.state] || 'Aguardando imagem'}</span>
      <button class="btn-light inline-camera-retry" type="button" onClick=${reconnect} disabled=${['loading', 'connecting', 'signaling', 'negotiating', 'receiving'].includes(connection.state)}>Verificar novamente</button>
    </div>
    <${CameraScreen} connection=${connection} video=${video} compact />
    <div class="inline-camera-meta"><span class="inline-camera-source">${config ? source.label : 'Imagem à frente do MicroDuck'}</span><a href="#/camera">Abrir página da câmera ›</a></div>
  </section>`;
}

export function CameraPage({ api }) {
  const video = useRef(null);
  const { config, connection, wanted, reconnect, stop } = useCameraSession({ api, video });
  const source = cameraSource(config, connection.producer);
  return html`<section class="sensor-page camera-page" aria-labelledby="camera-title">
    <header class="sensor-heading"><div><h1 id="camera-title">Câmera</h1><p>Veja a imagem de vídeo atual do MicroDuck.</p></div>
      <span class="sensor-pill camera-status" role="status" data-state=${connection.state}>${CAMERA_STATES[connection.state] || connection.state}</span></header>
    <div class="board sensor-board camera-source"><strong>${source.label}</strong><p>${source.note}</p>
      ${config?.error ? html`<p class="sensor-note">${config.error}; ainda vamos tentar conectar ao serviço de vídeo.</p>` : null}</div>
    <div class="sensor-actions">
      <button type="button" class="camera-start sensor-primary" onClick=${reconnect} disabled=${wanted && connection.state !== 'error' && connection.state !== 'stopped'}>Iniciar prévia</button>
      <button type="button" class="camera-stop" onClick=${stop} disabled=${!wanted}>Parar prévia</button>
      <button type="button" class="camera-reconnect" onClick=${reconnect}>Reconectar</button>
    </div>
    <${CameraScreen} connection=${connection} video=${video} />
    <div class="board sensor-board sensor-metrics"><div><span>Imagem real</span><b class="camera-size">${connection.state === 'playing' ? `${connection.width} × ${connection.height}` : '—'}</b></div>
      <div><span>Recepção</span><b class="camera-received">${connection.state === 'playing' ? `Imagem sendo atualizada${connection.frames != null ? ` · ${connection.frames} quadros` : ''}` : 'Aguardando imagem válida'}</b></div></div>
    ${connection.error ? html`<p class="sensor-error" role="alert">${connection.error}</p>` : null}
  </section>`;
}

const TOF_STATES = { loading: 'Conectando', ready: 'Leitura atualizada', waiting: 'Aguardando o primeiro quadro', unavailable: 'Sensor indisponível', error: 'Falha na leitura', stale: 'Leitura expirada', hidden: 'Página oculta; leitura pausada' };
const zoneLabel = (zone, index) => `Linha ${Math.floor(index / 8) + 1}, coluna ${index % 8 + 1}: ${zone.kind === 'range' ? `${zone.mm} milímetros` : zone.kind === 'no_target' ? 'sem alvo' : 'inválido'}; distância bruta ${zone.raw_mm} milímetros, estado ${zone.status}`;
export function TofPage({ api }) {
  const [value, setValue] = useState(emptyTof('loading', 'Lendo o ToF…'));
  const [attempt, setAttempt] = useState(0), [selected, setSelected] = useState(null);
  const visible = useVisible();
  useEffect(() => {
    if (!visible) { setValue(emptyTof('hidden', 'A leitura será retomada automaticamente quando você voltar a esta página.')); return; }
    const reader = createTofReader({ request: signal => api('/api/tof', undefined, 3500, signal), onValue: setValue });
    reader.start(); return () => reader.stop();
  }, [api, visible, attempt]);
  const ready = value.state === 'ready';
  const zones = ready ? value.zones : Array(64).fill(null);
  const selection = ready && selected != null ? value.zones[selected] : null;
  const range = Math.max(1, (value.farthest_mm || 0) - (value.nearest_mm || 0));
  return html`<section class="sensor-page tof-page" aria-labelledby="tof-title">
    <header class="sensor-heading"><div><h1 id="tof-title">Distância ToF</h1><p>Distâncias em 8 × 8 zonas, em milímetros. Exibidas nas linhas e colunas originais do sensor, sem alinhamento com a imagem da câmera.</p></div>
      <span class="sensor-pill tof-status" role="status" data-state=${value.state}>${TOF_STATES[value.state]}</span></header>
    <div class="board sensor-board tof-summary"><div><strong class="tof-sensor">${value.sensor || 'Modelo do sensor não confirmado'}</strong>
      ${value.simulated ? html`<span class="sensor-pill tof-simulated">Dados simulados</span>` : null}</div>
      <p class="tof-reason" role=${value.state === 'error' ? 'alert' : 'status'}>${value.reason || (ready ? 'As cores representam as distâncias válidas deste quadro: tons mais escuros indicam objetos próximos e tons mais claros, objetos distantes.' : 'Aguardando leitura do sensor.')}</p></div>
    <div class="tof-content"><div class="board sensor-board tof-visual">
      <div class="tof-grid" aria-label="Zonas de distância ToF em 8 × 8" aria-busy=${!ready}>${zones.map((zone, i) => html`<button type="button" key=${i}
        class=${`tof-zone ${zone?.kind || 'empty'}`} data-zone=${i} data-kind=${zone?.kind || 'empty'} disabled=${!zone}
        title=${zone ? zoneLabel(zone, i) : 'Ainda não há leitura válida'} aria-label=${zone ? zoneLabel(zone, i) : `Linha ${Math.floor(i / 8) + 1}, coluna ${i % 8 + 1}: sem leitura disponível`}
        aria-pressed=${selected === i && !!zone} onClick=${() => setSelected(i)}
        style=${zone?.kind === 'range' ? { backgroundColor: `hsl(205 70% ${42 + (zone.mm - value.nearest_mm) / range * 38}%)`, color: (zone.mm - value.nearest_mm) / range < .4 ? '#FFF' : '#081E31' } : null}>${zone?.kind === 'range' ? Math.round(zone.mm) : zone?.kind === 'no_target' ? '—' : zone ? '×' : '·'}</button>`)}</div>
      <div class="tof-legend"><span><i class="range"></i>Distância válida</span><span><i class="no_target"></i>Sem alvo —</span><span><i class="unusable"></i>Inválido ×</span></div>
      <p class="tof-zone-detail" aria-live="polite">${selection ? zoneLabel(selection, selected) : 'Selecione uma zona para ver a distância em milímetros e o estado bruto.'}</p>
    </div><div class="board sensor-board sensor-metrics tof-metrics">
      <div><span>Zonas válidas</span><b class="tof-valid">${ready ? `${value.valid_count} / 64` : '—'}</b></div>
      <div><span>Menor distância válida</span><b class="tof-nearest">${ready && value.nearest_mm != null ? `${value.nearest_mm} mm` : '—'}</b></div>
      <div><span>Maior distância válida</span><b class="tof-farthest">${ready && value.farthest_mm != null ? `${value.farthest_mm} mm` : '—'}</b></div>
      <div><span>Atualizado às</span><b class="tof-updated">${ready ? new Date(value.updatedAt).toLocaleTimeString() : '—'}</b></div>
      <div><span>Frequência do sensor</span><b>${ready && value.hz != null ? `${value.hz} Hz` : '—'}</b></div>
    </div></div>
    <div class="sensor-actions"><button type="button" class="tof-refresh" onClick=${() => setAttempt(n => n + 1)}>Ler novamente</button></div>
  </section>`;
}
