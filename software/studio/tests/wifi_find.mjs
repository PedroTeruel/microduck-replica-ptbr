// 连 WiFi 以后找鸭子的新地址（任务 17）：web/wifi.js 的探测逻辑（真代码，不是抄的），假时钟、假探测一幕一幕跑，
// 结果用 JSON 打到 stdout，由 tests/test_wifi_find.py 判断。
// 单独跑：node tests/wifi_find.mjs   （不需要装包；wifi.js 在 Node 里不碰 document）
const W = await import(new URL('../web/wifi.js', import.meta.url).href);

const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

/** 假时钟：setTimeout 排进队列，advance 一格一格往前拨（每格之后把 Promise 跑完） */
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

/** 一幕：probeAt(url, t) 决定这一下成不成（true / false / 'hang' 一直不回 / 'defer' 先挂着、手动放）。 */
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

// 1. 找到了：.local 6 秒以后才通 → 那一下就跳、停下，之后不再探
out.found = await scene({ urls: URLS, probeAt: (u, t) => u.includes('.local') && t >= 6000,
  run: async (c) => { await c.advance(20000); } });

// 2. 一直找不到：3 分钟到了放弃（回调一次），之后不再探
out.timeout = await scene({ urls: URLS, probeAt: () => false, run: async (c) => { await c.advance(200000); } });

// 3. 热点回来了（页面重新连上原来的地址）：stop 以后不再探；停之前发出去、停之后才回「通了」的也不算
out.stop = await scene({ urls: URLS, probeAt: (u, t) => (t === 4000 && u.includes('.local') ? 'defer' : false),
  run: async (c, f, deferred) => {
    await c.advance(5000);
    f.stop();
    for (const ok of deferred) ok(true);
    await c.advance(30000);
  } });

// 4. 一个地址挂着不回（连不上的地址可能几十秒才报错）：它回话之前不再探它，另一个照常每 2 秒探
out.hang = await scene({ urls: URLS, probeAt: (u) => (u.includes('.local') ? 'hang' : false),
  run: async (c) => { await c.advance(10000); } });

// 5. probeImage：new Image() 加载 <地址>probe.svg?t=<时间>；onload → 通，onerror → 不通，都不来 → 超时算不通
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
