// Robô 3D no palco. O modelo vem de servo-web/model/ (exportação oficial do CAD; consulte model/NOTICE.md).
//
// Regras de interação (review-design-v3 V2 e V7):
// - Mostra o estado atual: ângulos das articulações vêm do fluxo de estado; o corpo inclina conforme a gravidade da IMU, sem girar.
// - Arraste para girar e mantenha a vista na posição escolhida; “Recentralizar” restaura o ângulo padrão.
// - Toque em um servo para selecioná-lo e destacá-lo, sem ampliar o modelo:
//   As 15 peças xl330 representam as carcaças dos servos; cada uma é associada ao eixo de articulação mais próximo.
//   Ao tocar em outra peça, seleciona o servo que a movimenta. Deslocamentos acima de 6 pixels são tratados como arrasto.
// - Redesenha apenas quando há mudanças: renderizar continuamente mais de 400 mil faces a 60 fps sobrecarrega computadores e celulares.
// - Dados desatualizados são indicados pela classe .stale no canvas (esmaecido e semitransparente).
import * as THREE from './vendor/three/three.module.js';
import { OrbitControls } from './vendor/three/addons/OrbitControls.js';
import { RoomEnvironment } from './vendor/three/addons/RoomEnvironment.js';
import { toCreasedNormals } from './vendor/three/addons/BufferGeometryUtils.js';

export const JOINT_NAMES = ['left_hip_yaw', 'left_hip_roll', 'left_hip_pitch', 'left_knee', 'left_ankle',
  'neck_pitch', 'head_pitch', 'head_yaw', 'head_roll', 'mouth',
  'right_hip_yaw', 'right_hip_roll', 'right_hip_pitch', 'right_knee', 'right_ankle'];

const VIEWS = { front34: [-30, 12], back: [180, 12], back34: [205, 14], front: [0, 8] };

function materialFor(rgba) {
  const [r, g, b] = rgba;
  const near = (a, bb, c) => Math.abs(r - a) < 0.04 && Math.abs(g - bb) < 0.04 && Math.abs(b - c) < 0.04;
  let color, rough = 0.5;
  if (near(0.98, 0.71, 0.0)) { color = '#F5B400'; rough = 0.42; }            // Peça impressa amarela
  else if (near(0.29, 0.29, 0.29)) { color = '#5E6167'; rough = 0.58; }      // Servo
  else if (near(0.35, 0.38, 0.40)) { color = '#4C5157'; rough = 0.55; }
  else if (near(0.26, 0.28, 0.30)) { color = '#2F3338'; rough = 0.4; }
  else if (near(0.54, 0.85, 0.83)) { color = '#86D3CC'; rough = 0.6; }       // Solado
  else if (r > 0.75 && g > 0.75 && b > 0.75) { color = '#ECECE8'; rough = 0.5; } // Carcaça branca
  else color = new THREE.Color(r, g, b).getStyle();
  return new THREE.MeshStandardMaterial({ color: new THREE.Color(color), roughness: rough, metalness: 0, envMapIntensity: 0.55 });
}

// A decodificação do modelo leva algumas centenas de milissegundos no celular; é feita uma vez e reutilizada ao voltar à página.
// A geometria é compartilhada por todas as instâncias Duck3D e não é liberada no dispose individual.
let modelCache = null;
// Decodifica e calcula as normais no worker model-worker.js para não travar a página; usa a thread principal como alternativa.
function loadInWorker(base) {
  return new Promise((resolve, reject) => {
    let w;
    try { w = new Worker(new URL('./model-worker.js', import.meta.url)); } catch (e) { reject(e); return; }
    w.onmessage = (e) => {
      w.terminate();
      if (!e.data.ok) { reject(new Error(e.data.error)); return; }
      const geoms = {};
      for (const [name, m] of Object.entries(e.data.meshes)) {
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(m.position, 3));
        g.setAttribute('normal', new THREE.BufferAttribute(m.normal, 3));
        if (m.index) g.setIndex(new THREE.BufferAttribute(m.index, 1));
        geoms[name] = g;
      }
      window.__model = { cached: !!e.data.cached, at: performance.now() };   // Depuração: instante em que o modelo ficou pronto e se veio do cache
      resolve({ mj: e.data.mj, geoms });
    };
    w.onerror = (e) => { w.terminate(); reject(new Error(e.message || 'Falha no worker')); };
    w.postMessage({ base: new URL(base, location.href).href });
  });
}
async function loadModel(base) {
  if (!modelCache) {
    modelCache = loadInWorker(base).catch(() => (async () => {
      const mj = await (await fetch(base + 'model.json')).json();
      const bin = await (await fetch(base + 'meshes.bin')).arrayBuffer();
      const geoms = {};
      for (const [name, m] of Object.entries(mj.meshes)) {
        const q = new Int16Array(bin, m.voff, m.nverts * 3);
        const pos = new Float32Array(m.nverts * 3);
        for (let i = 0; i < m.nverts; i++) for (let k = 0; k < 3; k++) {
          const span = m.bbox_max[k] - m.bbox_min[k] || 1;
          pos[i * 3 + k] = m.bbox_min[k] + (q[i * 3 + k] + 32768) / 65535 * span;
        }
        const idx = m.index_bytes === 2 ? new Uint16Array(bin, m.ioff, m.ntris * 3) : new Uint32Array(bin, m.ioff, m.ntris * 3);
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        g.setIndex(new THREE.BufferAttribute(idx, 1));
        geoms[name] = toCreasedNormals(g, Math.PI / 6);     // Suaviza as faces
      }
      return { mj, geoms };
    })()).catch((e) => { modelCache = null; throw e; });
  }
  return modelCache;
}

const same = (a, b, eps) => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) < eps);

export class Duck3D {
  // pageScroll (palco da visão geral): a página deve continuar rolável, sem o modelo capturar a roda do mouse ou os toques.
  // Desativa o zoom para deixar a roda do mouse para a página; no celular, um dedo rola a página.
  // O canvas usa touch-action: pan-y; um dedo rola e dois giram a vista. No desktop, o mouse continua girando. Ajusta as opções após criar o controle.
  constructor(canvas, { view = 'front34', centerX = 0.61, centerY = 0.5, fill = 0.92, pageScroll = false } = {}) {
    this.canvas = canvas;
    canvas.__duck3d = this;   // Depuração e testes e2e: conta quadros; fora da tela, não renderiza
    this.frames = 0;          // Quadros realmente renderizados
    this.view = view;
    this.centerX = centerX;   // Posição horizontal do centro do robô (deixa espaço para os rótulos à esquerda)
    this.centerY = centerY;   // Posição vertical (no celular, o robô fica acima dos rótulos)
    this.fill = fill;
    this.joints = {};         // Nome da articulação -> { pivot, axis } (nomes iguais a robotd JOINT_NAMES)
    this.dirty = true;
    this.ready = false;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    // Limita a resolução a 1,5× em telas de alta densidade para evitar lentidão e aquecimento ao girar o modelo.
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.01, 20);
    this.camera.up.set(0, 0, 1);
    this.trunk = new THREE.Group();    // Grupo inclinado conforme a IMU
    this.content = new THREE.Group();
    this.trunk.add(this.content);
    this.scene.add(this.trunk);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.enablePan = false;
    this.controls.addEventListener('change', () => { this.dirty = true; });
    this.controls.addEventListener('start', () => { this._snapAt = null; this.onUserMove && this.onUserMove(); });
    this.controls.addEventListener('end', () => { if (this._sel) this._seeThrough(); });
    if (pageScroll) {
      this.controls.enableZoom = false;
      this.controls.touches = { ONE: null, TWO: THREE.TOUCH.DOLLY_ROTATE };   // ONE não é ROTATE nem PAN: um dedo não gira o modelo
      canvas.style.touchAction = 'pan-y';          // O OrbitControls define none durante a construção (OrbitControls.js:36)
    }
    // Não renderiza fora da tela; mantém dirty para redesenhar ao voltar, mesmo com atualizações de estado a 10 Hz.
    this._onScreen = true;
    if (typeof IntersectionObserver !== 'undefined') {
      this._io = new IntersectionObserver((es) => { for (const e of es) this._onScreen = e.isIntersecting; if (this._onScreen) this.dirty = true; });
      this._io.observe(canvas);
    }
    let down = null;
    canvas.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
    canvas.addEventListener('pointerup', (e) => {
      if (!down || !this.onPick || !this.ready) return;
      const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]);
      down = null;
      if (moved < 6) { const j = this.pick(e.clientX, e.clientY); if (j) this.onPick(j); }
    });
    this.servoOf = {};        // Nome da articulação -> peça da carcaça do servo
    this._resize = new ResizeObserver(() => this.resize());
    this._resize.observe(canvas);
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
  }

  async load(base = 'model/') {
    const { mj, geoms } = await loadModel(base);
    if (this._dead) return;
    const mjq = (q) => new THREE.Quaternion(q[1], q[2], q[3], q[0]);
    const objs = [];
    const jointOf = [];       // Articulação que movimenta cada corpo: a própria, se houver, ou a do corpo pai.
    const root = mj.bodies.find((b) => b.parent < 0);
    if (root) { this.trunk.position.set(...root.pos); this.content.position.copy(this.trunk.position).negate(); }
    for (const b of mj.bodies) {
      const node = new THREE.Group();
      node.position.set(...b.pos); node.quaternion.copy(mjq(b.quat));
      let inner = node;
      if (b.joint) {
        const pivot = new THREE.Group(); node.add(pivot); inner = pivot;
        this.joints[b.joint.name] = { pivot, axis: new THREE.Vector3(...b.joint.axis).normalize() };
      }
      jointOf.push(b.joint ? b.joint.name : (b.parent >= 0 ? jointOf[b.parent] : null));
      for (const g of b.geoms) {
        const mesh = new THREE.Mesh(geoms[g.mesh], materialFor(g.rgba));
        mesh.userData.jointOf = jointOf[jointOf.length - 1];
        mesh.userData.servo = g.mesh === 'xl330';
        mesh.position.set(...g.pos); mesh.quaternion.copy(mjq(g.quat)); inner.add(mesh);
      }
      objs.push({ inner });
      if (b.parent < 0) this.content.add(node); else objs[b.parent].inner.add(node);
    }
    this._lights();
    this._mapServos();
    this.ready = true;
    this._frame();
    this.dirty = true;
  }

  _lights() {
    const key = new THREE.DirectionalLight(0xfff0dc, 2.4); key.position.set(0.35, 0.3, 1.4);
    const fill = new THREE.DirectionalLight(0xe4ecff, 0.8); fill.position.set(0.3, -0.8, 0.35);
    const rim = new THREE.DirectionalLight(0xcfe0ff, 1.8); rim.position.set(-0.7, -0.5, 0.6);
    this.scene.add(key, fill, rim, new THREE.HemisphereLight(0xffffff, 0x2a2b2f, 0.35));
    // Sombra suave de contato sob os pés, feita com textura radial em vez de sombras em tempo real (economiza GPU e evita bordas duras).
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const ctx = c.getContext('2d');
    const grd = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
    grd.addColorStop(0, 'rgba(0,0,0,0.55)'); grd.addColorStop(0.5, 'rgba(0,0,0,0.2)'); grd.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = grd; ctx.fillRect(0, 0, 256, 256);
    this.blob = new THREE.Mesh(new THREE.PlaneGeometry(0.3, 0.26),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
    this.scene.add(this.blob);
  }

  /** Ângulos das articulações: robot.state.joints de robotd, em radianos e na ordem JOINT_NAMES; já calibrados, usados sem inverter o sinal.
    * Mapeamento review-impl-plan I13: joints[i] corresponde à articulação do modelo chamada JOINT_NAMES[i]. */
  setJoints(arr) {
    if (!this.ready || !Array.isArray(arr)) return;
    // Quando o robô está parado, os dados quase não mudam; evita redesenhar sem necessidade.
    if (this._lastJoints && same(arr, this._lastJoints, 1e-4)) return;
    this._lastJoints = arr.slice();
    arr.forEach((rad, i) => {
      const j = this.joints[JOINT_NAMES[i]];
      if (j && typeof rad === 'number' && isFinite(rad)) j.pivot.quaternion.setFromAxisAngle(j.axis, rad);
    });
    this.dirty = true;
  }

  /** Direção da gravidade no referencial do corpo (robot.state.safety.gravity; em pé, aproximadamente [0, 0, -1]); null mantém o corpo vertical.
    * setFromUnitVectors usa a rotação mais curta, apenas inclinação e rolagem; o ângulo de guinada é sempre zero. */
  setGravity(g) {
    if (!this.ready) return;
    if (!g) { if (this._lastGravity) { this._lastGravity = null; this.trunk.quaternion.identity(); this.dirty = true; } return; }
    if (this._lastGravity && same(g, this._lastGravity, 1e-4)) return;
    this._lastGravity = g.slice();
    const v = new THREE.Vector3(...g);
    if (v.lengthSq() < 1e-6) return;
    this.trunk.quaternion.setFromUnitVectors(v.normalize(), new THREE.Vector3(0, 0, -1));
    this.dirty = true;
  }

  setView(view) { this.view = view; this._frame(); }

  // Associação entre carcaças de servos e articulações pela proximidade ao eixo, na posição zero após carregar o modelo.
  _mapServos() {
    this.scene.updateMatrixWorld(true);
    const servos = [];
    this.content.traverse((o) => { if (o.isMesh && o.userData.servo) servos.push(o); });
    const pairs = [];
    for (const m of servos) {
      const c = new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3());
      for (const [name, j] of Object.entries(this.joints)) {
        pairs.push([c.distanceTo(j.pivot.getWorldPosition(new THREE.Vector3())), m, name]);
      }
    }
    pairs.sort((a, b) => a[0] - b[0]);
    const usedM = new Set(), usedJ = new Set();
    for (const [, m, name] of pairs) {
      if (usedM.has(m) || usedJ.has(name)) continue;
      usedM.add(m); usedJ.add(name);
      m.userData.joint = name;
      m.userData.baseColor = m.material.color.clone();
      this.servoOf[name] = m;
    }
  }

  /** Articulação atingida pelas coordenadas da tela. Primeiro compara com os 15 servos (inclusive os cobertos pela carcaça da cabeça);
    * se nenhum servo for atingido, identifica a peça e seleciona a articulação que a movimenta. */
  pick(clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2((clientX - r.left) / r.width * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const servo = ray.intersectObjects(Object.values(this.servoOf), false)[0];
    if (servo) return servo.object.userData.joint;
    const meshes = [];
    this.content.traverse((o) => { if (o.isMesh) meshes.push(o); });
    const hit = ray.intersectObjects(meshes, false)[0];
    return hit ? hit.object.userData.jointOf || null : null;
  }

  // Se a carcaça esconder o servo selecionado, torna as peças à frente semitransparentes. Recalcula ao soltar após girar a vista.
  _seeThrough() {
    for (const m of this._ghosted || []) {
      m.material.transparent = false; m.material.opacity = 1; m.material.depthWrite = true; m.material.needsUpdate = true;
    }
    this._ghosted = [];
    if (!this._sel) return;
    this.scene.updateMatrixWorld(true);
    const c = new THREE.Box3().setFromObject(this._sel).getCenter(new THREE.Vector3());
    const dir = c.clone().sub(this.camera.position);
    const dist = dir.length();
    const ray = new THREE.Raycaster(this.camera.position, dir.normalize(), 0, dist);
    const meshes = [];
    this.content.traverse((o) => { if (o.isMesh && o !== this._sel) meshes.push(o); });
    for (const h of ray.intersectObjects(meshes, false)) {
      if (h.distance < dist - 0.004 && !this._ghosted.includes(h.object)) {
        const m = h.object;
        m.material.transparent = true; m.material.opacity = 0.22; m.material.depthWrite = false; m.material.needsUpdate = true;
        this._ghosted.push(m);
      }
    }
    this.dirty = true;
  }

  /** Seleciona um servo: aplica a cor do grupo à carcaça e restaura a cor anterior. name null restaura todas. */
  select(name, color) {
    if (this._sel && this._sel.userData.baseColor) this._sel.material.color.copy(this._sel.userData.baseColor);
    this._sel = name ? this.servoOf[name] || null : null;
    if (this._sel) this._sel.material.color.set(color || '#2F7CF6');
    this._seeThrough();
    this.dirty = true;
  }

  /** Gira suavemente para a vista padrão (botão “Recentralizar” do palco). */
  resetView() { this._snapAt = performance.now(); this.dirty = true; }

  _frame() {
    if (!this.ready) return;
    this.scene.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(this.trunk);
    const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
    this.blob.position.set(center.x, center.y, box.min.z + 0.0008);
    const [azDeg, elDeg] = VIEWS[this.view] || VIEWS.front34;
    const az = THREE.MathUtils.degToRad(azDeg), el = THREE.MathUtils.degToRad(elDeg);
    const fov = THREE.MathUtils.degToRad(this.camera.fov);
    const dist = (size.z / this.fill) / (2 * Math.tan(fov / 2));
    const look = new THREE.Vector3(center.x, center.y, box.min.z + size.z * 0.5);
    this.home = { pos: new THREE.Vector3(look.x + dist * Math.cos(el) * Math.cos(az), look.y + dist * Math.cos(el) * Math.sin(az), look.z + dist * Math.sin(el)), target: look };
    this.camera.position.copy(this.home.pos);
    this.controls.target.copy(look);
    this.controls.update();
    this._applyOffset();
    this.dirty = true;
  }

  // Posiciona o robô em (centerX, centerY), liberando espaço para os rótulos sem mover a câmera.
  _applyOffset() {
    const w = this.canvas.clientWidth || 1, h = this.canvas.clientHeight || 1;
    this.camera.aspect = w / h;
    this.camera.setViewOffset(w, h, (0.5 - this.centerX) * w, (0.5 - this.centerY) * h, w, h);
    this.camera.updateProjectionMatrix();
  }

  resize() {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this._applyOffset();
    this.dirty = true;
  }

  _loop(now) {
    if (this._dead) return;
    if (this._snapAt && now > this._snapAt && this.home) {
      // “Recentralizar” foi acionado: retorna suavemente à vista padrão.
      this.camera.position.lerp(this.home.pos, 0.18);
      this.controls.target.lerp(this.home.target, 0.18);
      if (this.camera.position.distanceTo(this.home.pos) < 1e-4) this._snapAt = null;
      this.dirty = true;
    }
    if (this.controls.update()) this.dirty = true;
    // Não renderiza quando a página está em segundo plano ou o palco sai da tela; mantém dirty para redesenhar ao voltar.
    if (this.dirty && this.ready && !document.hidden && this._onScreen && this.canvas.offsetParent !== null) {
      this.renderer.render(this.scene, this.camera); this.dirty = false; this.frames++;
    }
    requestAnimationFrame(this._loop);
  }

  dispose() {
    this._dead = true;
    this._resize.disconnect();
    if (this._io) this._io.disconnect();
    this.controls.dispose();
    // Libera materiais e texturas desta instância; mantém a geometria compartilhada em cache.
    this.scene.traverse((o) => {
      if (o.material) { o.material.map?.dispose(); o.material.dispose(); }
    });
    this.scene.environment?.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();     // O navegador limita o número de contextos WebGL simultâneos; páginas repetidas poderiam esgotá-los.
  }
}
