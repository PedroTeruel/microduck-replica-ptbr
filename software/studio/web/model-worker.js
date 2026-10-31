// Decodifica o modelo 3D em uma thread de segundo plano (o carregamento do modelo causava travamentos ao atualizar a página).
//
// O modelo tem 317 mil faces: restaura vértices quantizados e calcula normais suavizadas (expande para 950 mil vértices, agrupa posições e calcula a média das faces com até 30° de diferença).
// Na thread principal, isso trava a página por um ou dois segundos. Aqui, a interface continua responsiva e recebe os arrays por transferência, sem cópia.
// O algoritmo de normais suavizadas segue three.js BufferGeometryUtils.toCreasedNormals e produz o mesmo resultado.
// Não importa three: workers não usam importmap e não resolvem o nome de pacote “three”.
//
// Também otimiza o carregamento em celulares:
// - Salva o resultado no IndexedDB; só recalcula quando model.json mudar.
// - Mescla vértices com posição e normal iguais e usa índices, reduzindo vértices, memória de vídeo e trabalho por quadro.
const DB = 'studio-model', STORE = 'decoded', VERSION = 3;

self.onmessage = async (e) => {
  try {
    const base = e.data.base;
    const text = await (await fetch(base + 'model.json')).text();
    const key = `v${VERSION}:${text.length}:${hash(text)}`;
    const cached = await idbGet(key);
    if (cached) {
      self.postMessage({ ok: true, mj: cached.mj, meshes: cached.meshes, cached: true });
      return;
    }
    const mj = JSON.parse(text);
    const bin = await (await fetch(base + 'meshes.bin')).arrayBuffer();
    const meshes = {};
    const transfer = [];
    for (const [name, m] of Object.entries(mj.meshes)) {
      const q = new Int16Array(bin, m.voff, m.nverts * 3);
      const pos = new Float32Array(m.nverts * 3);
      for (let i = 0; i < m.nverts; i++) for (let k = 0; k < 3; k++) {
        const span = m.bbox_max[k] - m.bbox_min[k] || 1;
        pos[i * 3 + k] = m.bbox_min[k] + (q[i * 3 + k] + 32768) / 65535 * span;
      }
      const idx = m.index_bytes === 2 ? new Uint16Array(bin, m.ioff, m.ntris * 3) : new Uint32Array(bin, m.ioff, m.ntris * 3);
      meshes[name] = creasedIndexed(pos, q, idx, Math.PI / 6);
    }
    await idbPut(key, { mj, meshes });            // Primeiro armazena (clonagem estruturada), depois transfere para a página.
    for (const m of Object.values(meshes)) transfer.push(m.position.buffer, m.normal.buffer, m.index.buffer);
    self.postMessage({ ok: true, mj, meshes }, transfer);
  } catch (err) {
    self.postMessage({ ok: false, error: String(err && err.message || err) });
  }
};

// Calcula normais suavizadas e mescla vértices em uma passagem (a primeira carga demorava 8 s).
// A normal de cada canto é a média das normais das faces coincidentes que formam até 30° com sua face, como em three.js toCreasedNormals.
// Considera posições coincidentes quando suas coordenadas quantizadas são iguais; evita a busca lenta em uma grade de 1 cm usada pelo three.
// Mescla cantos com posição e normal iguais em um vértice indexado; cantos em arestas permanecem separados quando as normais diferem.
function creasedIndexed(pos, q, idx, creaseAngle) {
  const creaseDot = Math.cos(creaseAngle);
  const nTri = idx.length / 3;
  const faceN = new Float32Array(nTri * 3);
  for (let t = 0; t < nTri; t++) {
    const a = idx[t * 3] * 3, b = idx[t * 3 + 1] * 3, c = idx[t * 3 + 2] * 3;
    const cbx = pos[c] - pos[b], cby = pos[c + 1] - pos[b + 1], cbz = pos[c + 2] - pos[b + 2];
    const abx = pos[a] - pos[b], aby = pos[a + 1] - pos[b + 1], abz = pos[a + 2] - pos[b + 2];
    let x = cby * abz - cbz * aby, y = cbz * abx - cbx * abz, z = cbx * aby - cby * abx;
    const len = Math.hypot(x, y, z) || 1;
    faceN[t * 3] = x / len; faceN[t * 3 + 1] = y / len; faceN[t * 3 + 2] = z / len;
  }
  // Posição coincidente → faces que a utilizam (coordenadas quantizadas combinadas em uma chave numérica sem colisões).
  const posKey = (v) => (q[v * 3] + 32768) * 4294967296 + (q[v * 3 + 1] + 32768) * 65536 + (q[v * 3 + 2] + 32768);
  const groups = new Map();
  for (let t = 0; t < nTri; t++) {
    for (let k = 0; k < 3; k++) {
      const key = posKey(idx[t * 3 + k]);
      const g = groups.get(key);
      if (g) g.push(t); else groups.set(key, [t]);
    }
  }
  const P = [], N = [], index = new Uint32Array(idx.length);
  const seen = new Map();                       // Chave da posição → [[nx,ny,nz,novo índice], ...] (normalmente um ou dois itens).
  let u = 0;
  for (let t = 0; t < nTri; t++) {
    const fx = faceN[t * 3], fy = faceN[t * 3 + 1], fz = faceN[t * 3 + 2];
    for (let k = 0; k < 3; k++) {
      const v = idx[t * 3 + k], key = posKey(v);
      let x = 0, y = 0, z = 0;
      for (const g of groups.get(key)) {
        const gx = faceN[g * 3], gy = faceN[g * 3 + 1], gz = faceN[g * 3 + 2];
        if (fx * gx + fy * gy + fz * gz > creaseDot) { x += gx; y += gy; z += gz; }
      }
      const len = Math.hypot(x, y, z) || 1;
      x /= len; y /= len; z /= len;
      let list = seen.get(key), j = -1;
      if (list) {
        for (const e of list) if (Math.abs(e[0] - x) < 1e-3 && Math.abs(e[1] - y) < 1e-3 && Math.abs(e[2] - z) < 1e-3) { j = e[3]; break; }
      } else { list = []; seen.set(key, list); }
      if (j < 0) {
        j = u++;
        list.push([x, y, z, j]);
        P.push(pos[v * 3], pos[v * 3 + 1], pos[v * 3 + 2]);
        N.push(x, y, z);
      }
      index[t * 3 + k] = j;
    }
  }
  return { position: new Float32Array(P), normal: new Float32Array(N), index: u < 65536 ? new Uint16Array(index) : index };
}

function hash(t) {
  let h = 2166136261;
  for (let i = 0; i < t.length; i++) { h ^= t.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(16);
}

// A leitura/gravação no IndexedDB é opcional; em navegação privada ou com armazenamento desativado, funciona recalculando sempre.
function idbOpen() {
  return new Promise((resolve) => {
    try {
      const r = indexedDB.open(DB, 1);
      r.onupgradeneeded = () => r.result.createObjectStore(STORE);
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => resolve(null);
    } catch { resolve(null); }
  });
}
async function idbGet(key) {
  const db = await idbOpen();
  if (!db) return null;
  return new Promise((resolve) => {
    try {
      const q = db.transaction(STORE).objectStore(STORE).get(key);
      q.onsuccess = () => resolve(q.result || null);
      q.onerror = () => resolve(null);
    } catch { resolve(null); }
  });
}
async function idbPut(key, value) {
  const db = await idbOpen();
  if (!db) return;
  await new Promise((resolve) => {
    try {
      const tx = db.transaction(STORE, 'readwrite');
      const st = tx.objectStore(STORE);
      st.clear();                                   // Mantém apenas uma cópia e remove versões antigas.
      st.put(value, key);
      tx.oncomplete = tx.onerror = tx.onabort = () => resolve();
    } catch { resolve(); }
  });
}
