// Rótulos dos servos no modelo 3D: número, português e inglês, com linhas apontando para os eixos.
// Servos 10 a 18 aparecem somente na página Servos, na postura de referência “posição zero”; perna direita em vermelho, esquerda em azul e cabeça/pescoço em amarelo, conforme o diagrama fornecido pelo usuário.
// Peças ocultas pelo corpo ou por outros componentes usam linha tracejada e marcador vazado; considera-se obstruído quando outra peça cruza a linha da câmera ao eixo a mais de 3 cm.
// O eixo fica dentro do servo; por isso, ignoramos o primeiro contato com a própria carcaça usando essa margem de 3 cm.
import * as THREE from './vendor/three/three.module.js';

export const TAGS = {
  right_hip_yaw: [10, 'Guinada do quadril direito', 'Right Hip Yaw', 'R'], right_hip_roll: [11, 'Rolagem do quadril direito', 'Right Hip Roll', 'R'],
  right_hip_pitch: [12, 'Inclinação do quadril direito', 'Right Hip Pitch', 'R'], right_knee: [13, 'Joelho direito', 'Right Knee', 'R'],
  right_ankle: [14, 'Tornozelo direito', 'Right Ankle', 'R'],
  left_hip_yaw: [20, 'Guinada do quadril esquerdo', 'Left Hip Yaw', 'L'], left_hip_roll: [21, 'Rolagem do quadril esquerdo', 'Left Hip Roll', 'L'],
  left_hip_pitch: [22, 'Inclinação do quadril esquerdo', 'Left Hip Pitch', 'L'], left_knee: [23, 'Joelho esquerdo', 'Left Knee', 'L'],
  left_ankle: [24, 'Tornozelo esquerdo', 'Left Ankle', 'L'],
  neck_pitch: [30, 'Inclinação do pescoço', 'Neck Pitch', 'H'], head_pitch: [31, 'Inclinação da cabeça', 'Head Pitch', 'H'],
  head_yaw: [32, 'Guinada da cabeça', 'Head Yaw', 'H'], head_roll: [33, 'Rolagem da cabeça', 'Head Roll', 'H'], mouth: [34, 'Bico', 'Mouth', 'H'],
};
const COLOR = { R: '#E5484D', L: '#2F7CF6', H: '#F5B400' };

/** Desenha os rótulos dentro da caixa (elemento de palco). duck é uma instância carregada de Duck3D. Retorna uma função de limpeza. */
export function drawServoLabels(duck, box) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'sv-lines');
  box.appendChild(svg);
  const tags = [];
  const ray = new THREE.Raycaster();
  const hiddenCache = {};
  let dragging = false;

  function layout() {
    const W = box.clientWidth, H = box.clientHeight;
    if (!W || !H || !duck.ready) return;
    duck.scene.updateMatrixWorld(true);
    const meshes = [];
    if (!dragging) duck.content.traverse((o) => { if (o.isMesh) meshes.push(o); });
    const pts = [];
    for (const [name, [id, cn, en, side]] of Object.entries(TAGS)) {
      const j = duck.joints[name];
      if (!j) continue;
      const world = new THREE.Vector3();
      j.pivot.getWorldPosition(world);
      // A verificação de oclusão (raios contra mais de 400 mil faces) roda somente quando o modelo está parado; durante o giro, reutiliza o resultado anterior para evitar travamentos.
      if (!dragging || !(id in hiddenCache)) {
        const dir = world.clone().sub(duck.camera.position);
        const dist = dir.length();
        ray.set(duck.camera.position, dir.normalize());
        const hit = ray.intersectObjects(meshes, false)[0];
        hiddenCache[id] = !!hit && hit.distance < dist - 0.03;
      }
      const v = world.clone().project(duck.camera);
      pts.push({ id, cn, en, side, hidden: hiddenCache[id], x: (v.x + 1) / 2 * W, y: (1 - v.y) / 2 * H });
    }
    // Uma coluna por perna; a posição esquerda/direita depende da projeção. Cabeça e pescoço são distribuídos pelas duas colunas a partir da linha central da cabeça.
    // Cabeça e pescoço ficam acima, ordenados pela altura para evitar cruzamento das linhas; as pernas seguem a numeração (10, 11, 12…).
    const avg = (s) => { const xs = pts.filter((p) => p.side === s).map((p) => p.x); return xs.reduce((a, b) => a + b, 0) / (xs.length || 1); };
    const rightOnLeft = avg('R') < avg('L'), headX = avg('H');
    const cols = [[], []];
    for (const p of pts) cols[(p.side === 'H' ? p.x < headX : (p.side === 'R') === rightOnLeft) ? 0 : 1].push(p);
    const gap = Math.min(46, (H - 60) / Math.max(cols[0].length, cols[1].length, 1));
    for (const col of cols) {
      col.sort((a, b) => ((a.side === 'H') !== (b.side === 'H') ? (a.side === 'H' ? -1 : 1) : a.side === 'H' ? a.y - b.y : a.id - b.id));
      let y = 34;
      for (const p of col) { p.ty = Math.max(y, Math.min(p.y, H - 26)); y = p.ty + gap; }
      let lim = H - 26;
      for (let i = col.length - 1; i >= 0; i--) { col[i].ty = Math.min(col[i].ty, lim); lim = col[i].ty - gap; }
    }
    tags.forEach((t) => t.remove());
    tags.length = 0;
    let lines = '';
    cols.forEach((col, ci) => {
      for (const p of col) {
        const el = document.createElement('div');
        el.className = `sv-tag ${p.side}`;
        el.innerHTML = `<span class="id">${p.id}</span><span><div class="cn">${p.cn}</div><div class="en">${p.en}</div></span>`;
        box.appendChild(el);
        tags.push(el);
        const w = el.offsetWidth;
        const lx = ci === 0 ? 14 : W - 14 - w;
        el.style.left = `${lx}px`;
        el.style.top = `${p.ty - 17}px`;
        const ax = ci === 0 ? lx + w : lx, mid = ci === 0 ? ax + 24 : ax - 24;
        lines += `<polyline points="${ax},${p.ty} ${mid},${p.ty} ${p.x},${p.y}" fill="none" stroke="${COLOR[p.side]}" stroke-width="2"${p.hidden ? ' stroke-dasharray="6 5"' : ''}/>`
          + `<circle cx="${p.x}" cy="${p.y}" r="4" fill="${p.hidden ? 'none' : '#fff'}" stroke="${COLOR[p.side]}" stroke-width="2"/>`;
      }
    });
    svg.innerHTML = lines;
  }

  let raf = 0;
  const schedule = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(layout); };
  const onStart = () => { dragging = true; };
  const onEnd = () => { dragging = false; schedule(); };
  duck.controls.addEventListener('change', schedule);
  duck.controls.addEventListener('start', onStart);
  duck.controls.addEventListener('end', onEnd);
  const ro = new ResizeObserver(schedule);
  ro.observe(box);
  schedule();
  return () => {
    cancelAnimationFrame(raf);
    duck.controls.removeEventListener('change', schedule);
    duck.controls.removeEventListener('start', onStart);
    duck.controls.removeEventListener('end', onEnd);
    ro.disconnect();
    tags.forEach((t) => t.remove());
    svg.remove();
  };
}
