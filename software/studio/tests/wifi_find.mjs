// Encontra o novo endereço do robô após conectar ao Wi-Fi (tarefa 17): executa a lógica real de web/wifi.js com relógio e sondagens simulados.
// Os resultados são enviados em JSON para stdout e verificados por tests/test_wifi_find.py.
// Execução isolada: node tests/wifi_find.mjs (sem dependências; wifi.js não acessa document no Node).
const W = await import(new URL('../web/wifi.js', import.meta.url).href);

const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

/** Relógio simulado: enfileira setTimeout e avança em etapas, resolvendo as Promises depois de cada uma. */
function fakeClock() {
  let now = 0, seq = 0;
  const q = [];
  return {
    now: () => now,
    timers: {
      setTimeout: (f, ms) => { const id = ++seq; q.push({ id, at: now + ms, f }); return id; },
      clearTimeout: (id) => { const i = q.findIndex((x) => x.id === id); if (i >= 0) q.splice(i, 1); },
    },
    async advance(ms) {
      const end = now + ms;
      await flush();
      for (;;) {
        q.sort((a, b) => a.at - b.at || a.id - b.id);
        const n = q[0];
        if (!n || n.at > end) break;
        q.shift();
        now = n.at;
        n.f();
        await flush();
      }
      now = end;
      await flush();
    },
    pending: () => q.length,
  };
}

/** Cenário: probeAt(url, t) determina o resultado (true, false, 'hang' sem resposta ou 'defer' aguardando liberação manual). */
async function scene({ urls, probeAt, run }) {
  const c = fakeClock();
  const calls = [], found = [], gaveUp = [];
  const deferred = [];
  const f = W.startFind({
    urls, now: c.now, timers: c.timers,
    probe: (url) => {
      calls.push({ t: c.now(), url });
      const r = probeAt(url, c.now());
      if (r === 'hang') return new Promise(() => {});
      if (r === 'defer') return new Promise((ok) => deferred.push(ok));
      return Promise.resolve(r);
    },
    onFound: (url) => found.push({ t: c.now(), url }),
    onGiveUp: () => gaveUp.push(c.now()),
  });
  await run(c, f, deferred);
  return { calls, found, gaveUp, stopped: f.stopped, pending: c.pending() };
}

const NET = { hostname: 'duck-0de6', url_host: 'http://duck-0de6:8000/', url_local: 'http://duck-0de6.local:8000/' };
const URLS = W.findUrls(NET);
const out = {
  consts: { every: W.FIND_EVERY_MS, giveUp: W.FIND_GIVEUP_MS, silent: W.FIND_SILENT_MS },
  urls: URLS,
  urlsPort: W.findUrls({ hostname: 'duck-c51b', url_host: 'http://duck-c51b:18080/', url_local: 'http://duck-c51b.local:18080/' }),
  urlsBare: W.findUrls({ hostname: 'duck-c51b' }),
};

// 1. Encontrado: .local só responde após 6 s; navegue e interrompa as sondagens.
out.found = await scene({ urls: URLS, probeAt: (u, t) => u.includes('.local') && t >= 6000,
  run: async (c) => { await c.advance(20000); } });

// 2. Não encontrado: desista após 3 min, chame o callback uma vez e pare as sondagens.
out.timeout = await scene({ urls: URLS, probeAt: () => false, run: async (c) => { await c.advance(200000); } });

// 3. O ponto de acesso voltou e a página reconectou: stop interrompe as sondagens; respostas tardias são ignoradas.
out.stop = await scene({ urls: URLS, probeAt: (u, t) => (t === 4000 && u.includes('.local') ? 'defer' : false),
  run: async (c, f, deferred) => {
    await c.advance(5000);
    f.stop();
    for (const ok of deferred) ok(true);
    await c.advance(30000);
  } });

// 4. Um endereço não responde: não o consulte de novo até obter resposta; continue sondando o outro a cada 2 s.
out.hang = await scene({ urls: URLS, probeAt: (u) => (u.includes('.local') ? 'hang' : false),
  run: async (c) => { await c.advance(10000); } });

// 5. probeImage carrega <endereço>probe.svg?t=<tempo> com new Image(); onload significa conectado, onerror ou timeout significa indisponível.
const made = [];
globalThis.Image = class {
  constructor() { this.onload = null; this.onerror = null; made.push(this); }
  set src(v) { this._src = v; }
  get src() { return this._src; }
};
const pLoad = W.probeImage('http://duck-0de6:8000/', 5000);
made[0].onload();
const pErr = W.probeImage('http://duck-0de6.local:8000/', 5000);
made[1].onerror();
const pSlow = W.probeImage('http://duck-0de6:8000/', 30);
out.image = { srcs: made.map((m) => m.src), load: await pLoad, error: await pErr, timeout: await pSlow,
  handlersCleared: made.every((m) => m.onload === null && m.onerror === null) };

process.stdout.write(JSON.stringify(out));
