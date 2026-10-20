// 总览的「连 WiFi」卡片、设置里的 WiFi 一栏（任务 10b）。
// 鸭子开着热点时，手机连热点、打开 Studio，选家里的 WiFi、填密码；Studio 先关热点，再让 configd net.connect。
// 热点开关、net.* 都在后端（studio/net.py）；这里只管选网、确认、把「断开以后还能看」的话留在屏幕上。
import { html, useState, useEffect } from './vendor/preact-htm.module.js';
import { ConfirmBox } from './confirm.js';

const CSS = `
.wifi-card { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.wifi-card h2 { margin: 0; font-size: 17px; font-weight: 600; }
.wifi-settings { padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.wifi-settings h2 { margin: 0; font-size: 15px; font-weight: 600; }
.wifi-lead { margin: 0; font-size: 13px; line-height: 1.6; color: var(--text-2); }
.wifi-last-try { padding: 9px 12px; border-radius: 10px; background: #FFF1F1; box-shadow: inset 0 0 0 1px rgba(215, 0, 21, .18);
  color: var(--danger); font-size: 14px; line-height: 1.55; }
.wifi-list { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.wifi-net, .wifi-manual { border-radius: 12px; background: #F7F7FA; min-width: 0; overflow: hidden; }
.wifi-net.on { background: #EEF5FF; box-shadow: inset 0 0 0 1px rgba(0, 113, 227, .22); }
.wifi-net-head, .wifi-manual-head { width: 100%; min-height: 48px; padding: 8px 12px; border: 0; background: transparent;
  display: flex; align-items: center; gap: 10px; text-align: left; font-size: 16px; color: var(--text); }
.wifi-manual-head { color: var(--text-2); font-size: 14px; }
.wifi-name { flex: 1; min-width: 0; overflow-wrap: anywhere; line-height: 1.3; }
.wifi-name b { font-weight: 600; }
.wifi-sub { display: block; margin-top: 2px; font-size: 12px; color: var(--text-2); font-weight: 400; }
.wifi-badge { flex: none; font-size: 11px; padding: 1px 7px; border-radius: 999px; background: #E3F6EA; color: #1E7B3A; }
.wifi-lock { flex: none; font-size: 13px; opacity: .75; }
.wifi-bars { flex: none; width: 22px; height: 16px; display: inline-flex; align-items: flex-end; gap: 2px; }
.wifi-bars i { flex: 1; border-radius: 1px; background: #D5D5DB; height: 4px; }
.wifi-bars i:nth-child(2) { height: 7px; }
.wifi-bars i:nth-child(3) { height: 11px; }
.wifi-bars i:nth-child(4) { height: 15px; }
.wifi-bars i.on { background: var(--blue); }
.wifi-row-body { padding: 0 12px 12px; display: flex; flex-direction: column; gap: 8px; }
.wifi-psk-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.wifi-psk, .wifi-manual-name, .wifi-manual-psk { width: 100%; min-width: 0; height: 44px; padding: 0 12px;
  border: 1px solid #D2D2D7; border-radius: 10px; background: #FFF; color: var(--text); font: inherit; font-size: 16px; }
.wifi-show { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; color: var(--text-2); }
.wifi-btn { min-height: 40px; padding: 0 16px; border: 0; border-radius: 999px; background: #E5E5EA;
  color: var(--text); font: inherit; font-size: 14px; }
.wifi-btn.primary { background: var(--blue); color: #FFF; font-weight: 600; }
.wifi-btn:disabled { opacity: .45; }
.wifi-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.wifi-note { font-size: 13px; color: var(--text-2); line-height: 1.5; }
.wifi-msg { font-size: 13px; line-height: 1.5; color: var(--danger); }
.wifi-switching { padding: 12px 14px; border-radius: 12px; background: #FFF7EC; box-shadow: inset 0 0 0 1px #F5DDBF;
  font-size: 14px; line-height: 1.6; }
.wifi-switching b { display: block; margin-bottom: 4px; font-size: 15px; }
.wifi-switching p { margin: 2px 0 0; }
.wifi-now { display: flex; flex-direction: column; gap: 4px; font-size: 14px; line-height: 1.55; }
.wifi-now .big { font-size: 16px; font-weight: 600; }
.wifi-saved-row { display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 4px 0; border-top: 1px solid var(--line); }
.wifi-saved-row .wifi-name { font-size: 15px; }
.wifi-flow { margin-top: 4px; padding-top: 12px; border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; }
@media (max-width: 700px) {
  .wifi-card, .wifi-settings { padding: 14px 14px; }
  .wifi-net-head { min-height: 52px; padding: 10px 12px; }
  .wifi-btn { min-height: 44px; }
  .wifi-psk, .wifi-manual-name, .wifi-manual-psk { height: 46px; }
}
`;
if (!document.getElementById('wifi-css')) {
  const s = document.createElement('style');
  s.id = 'wifi-css';
  s.textContent = CSS;
  document.head.appendChild(s);
}

const SEC = { open: '开放', wep: 'WEP', wpa_psk: 'WPA2', wpa3_sae: 'WPA3', enterprise: '企业认证' };
const secLabel = (sec) => SEC[sec] || (sec ? '加密' : '');
const pskFormatOk = (v) => v === '' || (v.length >= 8 && v.length <= 63) || /^[0-9a-fA-F]{64}$/.test(v);
const pskOk = (v) => v !== '' && pskFormatOk(v);

function Bars({ signal }) {
  const n = typeof signal === 'number' ? (signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1) : 0;
  return html`<span class="wifi-bars" title=${typeof signal === 'number' ? '信号 ' + signal : '信号不知道'}
    aria-label=${typeof signal === 'number' ? '信号 ' + signal : '信号不知道'}>
    ${[1, 2, 3, 4].map((i) => html`<i class=${i <= n ? 'on' : ''}></i>`)}</span>`;
}

function minutesSince(at) {
  if (typeof at !== 'number') return null;
  return Math.max(1, Math.round((Date.now() / 1000 - at) / 60));
}

// 确认框里的几行：热点卡片和设置里的「换一个 WiFi」只在第一句不同
function confirmLines(net, ssid, variant) {
  const url = net.url_local || '';
  const host = net.hostname || '';
  const back = variant === 'switch'
    ? '没连上：这个页面会断开；热点马上就回来，手机重新连鸭子热点就能看到原因。'
    : `没连上：热点马上就回来，手机重新连 ${net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : '鸭子自己的热点'} 就能看到原因。`;
  const first = variant === 'switch'
    ? `鸭子会断开现在的 WiFi 去连「${ssid}」，这个页面会断开。`
    : `鸭子会关掉热点，去连「${ssid}」。你的手机会断开。`;
  return [first,
    `连上以后：手机连回家里 WiFi，打开 ${url} 。`,
    `打不开（安卓手机常见）：去路由器后台的设备列表找 ${host}，用它的 IP 打开。`,
    back];
}

function LastTry({ net }) {
  const lt = net.last_try;
  if (!lt || lt.ok !== false) return null;
  const why = lt.reason_text || '没连上';
  const ssid = net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : '鸭子热点';
  return html`<div class="wifi-last-try" role="alert">上次连「${lt.ssid || '这个 WiFi'}」没成功：${why}
    ${net.mode === 'hotspot' ? html`<div>热点马上就回来，手机重新连 ${ssid} 就能看到原因。</div>` : null}</div>`;
}

function Switching({ net, ssid, variant }) {
  return html`<div class="wifi-switching" role="status">
    <b>正在切换……手机马上会断开</b>
    ${confirmLines(net, ssid || '这个 WiFi', variant).map((line) => html`<p>${line}</p>`)}
  </div>`;
}

export function WifiFlow({ net, link, variant = 'card' }) {
  const [scan, setScan] = useState({ networks: [], loading: true, error: null, cached: false, scan_at: null });
  const [sel, setSel] = useState(null);
  const [psk, setPsk] = useState('');
  const [show, setShow] = useState(false);
  const [manual, setManual] = useState(false);
  const [manualName, setManualName] = useState('');
  const [manualPsk, setManualPsk] = useState('');
  const [manualShow, setManualShow] = useState(false);
  const [confirm, setConfirm] = useState(null);        // {ssid, psk}
  const [trying, setTrying] = useState(null);
  const [switching, setSwitching] = useState(false);
  const [startedAt, setStartedAt] = useState(0);
  const [msg, setMsg] = useState(null);

  const rescan = async () => {
    setScan((s) => ({ ...s, loading: true, error: null }));
    const r = await link.cmd('net.op', { op: 'scan' }, 25000);
    if (!r.ok) {
      setScan({ networks: [], loading: false, error: r.reason || r.error || '读不到 WiFi 列表', cached: false, scan_at: null });
      return;
    }
    const d = r.data || {};
    setScan({ networks: Array.isArray(d.networks) ? d.networks : [], loading: false, error: null,
      cached: !!d.cached, scan_at: d.scan_at || null });
  };
  useEffect(() => {
    let alive = true;
    (async () => {
      await link.whenOpen();
      if (alive) await rescan();
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!switching) return;
    const lt = net.last_try;
    if (lt && typeof lt.at === 'number' && startedAt && lt.at * 1000 >= startedAt - 2000) setSwitching(false);
    else if (!net.busy && startedAt && Date.now() - startedAt > 12000) setSwitching(false);
  }, [net.busy, net.last_try ? net.last_try.at : null]);

  // 确认框在卡片最下面：手机上点了「连接」看不到它，弹出时滚过去
  useEffect(() => {
    if (!confirm) return;
    const e = document.querySelector('.wifi-confirm-wrap');
    if (e && e.scrollIntoView) e.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [confirm]);

  const pick = (n) => {
    if (sel === n.ssid) { setSel(null); setPsk(''); return; }
    setSel(n.ssid); setPsk(''); setShow(false); setMsg(null);
  };
  const ask = (ssid, pass, locked = false) => {
    if (!ssid) { setMsg('先填 WiFi 名字'); return; }
    if (locked && !pass) { setMsg('这个 WiFi 加密了，要填密码'); return; }
    if (!pskFormatOk(pass)) { setMsg('WiFi 密码要 8–63 个字符，或者 64 位十六进制'); return; }
    setMsg(null);
    setConfirm({ ssid, psk: pass });
  };
  const start = async () => {
    if (!confirm) return;
    const { ssid, psk: pass } = confirm;
    setConfirm(null); setTrying(ssid); setStartedAt(Date.now()); setSwitching(true); setMsg(null);
    const r = await link.cmd('net.op', { op: 'connect', ssid, psk: pass }, 20000);
    if (!r.ok) { setSwitching(false); setMsg(r.reason || r.error || '没发出去'); }
  };

  const nets = scan.networks || [];
  const ago = scan.cached ? minutesSince(scan.scan_at) : null;
  const busy = switching || net.busy === 'connecting';
  return html`<div class="wifi-flow">
    ${busy ? html`<${Switching} net=${net} ssid=${trying || (net.last_try && net.last_try.ssid)} variant=${variant} />` : null}
    ${scan.error ? html`<div class="wifi-msg">${scan.error}</div>` : null}
    <div class="wifi-list">
      ${nets.map((n) => {
        const on = sel === n.ssid;
        const open = n.security === 'open';
        const needs = !open;
        const can = open || pskOk(psk);
        return html`<div class=${'wifi-net' + (on ? ' on' : '')} data-ssid=${n.ssid}>
          <button class="wifi-net-head" type="button" aria-expanded=${on ? 'true' : 'false'} onClick=${() => pick(n)}>
            <${Bars} signal=${n.signal} />
            <span class="wifi-name"><b>${n.ssid}</b><span class="wifi-sub">${secLabel(n.security)}${n.saved ? ' · 已保存' : ''}</span></span>
            ${n.saved ? html`<span class="wifi-badge">已保存</span>` : null}
            ${open ? null : html`<span class="wifi-lock" title="${secLabel(n.security)}">🔒</span>`}
          </button>
          ${on ? html`<div class="wifi-row-body">
            ${needs ? html`<div class="wifi-psk-row">
              <input class="wifi-psk" type=${show ? 'text' : 'password'} value=${psk} autocomplete="new-password"
                placeholder="家里 WiFi 的密码" onInput=${(e) => setPsk(e.target.value)} />
              <label class="wifi-show"><input type="checkbox" checked=${show} onChange=${(e) => setShow(e.target.checked)} /> 显示密码</label>
            </div>${n.saved ? html`<div class="wifi-note">已保存；鸭子每次连都要密码（官方配网程序的规矩）。</div>` : null}`
              : html`<div class="wifi-note">这是开放网络，不用密码。</div>`}
            <div class="wifi-actions"><button class="wifi-btn primary wifi-connect" type="button" disabled=${!can || busy}
              onClick=${() => ask(n.ssid, needs ? psk : '', needs)}>连接</button></div>
          </div>` : null}
        </div>`;
      })}
    </div>
    <div class="wifi-manual">
      <button class="wifi-manual-head" type="button" aria-expanded=${manual ? 'true' : 'false'} onClick=${() => setManual(!manual)}>
        ${manual ? '收起' : '其他网络（手动输入名字）'}
      </button>
      ${manual ? html`<div class="wifi-row-body">
        <input class="wifi-manual-name" value=${manualName} placeholder="WiFi 名字" onInput=${(e) => setManualName(e.target.value)} />
        <input class="wifi-manual-psk" type=${manualShow ? 'text' : 'password'} value=${manualPsk}
          placeholder="密码（开放网络留空）" autocomplete="new-password" onInput=${(e) => setManualPsk(e.target.value)} />
        <label class="wifi-show"><input type="checkbox" checked=${manualShow} onChange=${(e) => setManualShow(e.target.checked)} /> 显示密码</label>
        <div class="wifi-actions"><button class="wifi-btn primary wifi-manual-connect" type="button" disabled=${busy || !manualName}
          onClick=${() => ask(manualName, manualPsk)}>连接</button></div>
      </div>` : null}
    </div>
    <div class="wifi-actions">
      <button class="wifi-btn wifi-rescan" type="button" disabled=${scan.loading || busy} onClick=${rescan}>
        ${scan.loading ? '正在扫描…' : '重新扫描'}</button>
      ${ago ? html`<span class="wifi-note">这是 ${ago} 分钟前扫的</span>` : null}
    </div>
    ${msg ? html`<div class="wifi-msg">${msg}</div>` : null}
    ${confirm ? html`<div class="wifi-confirm-wrap"><${ConfirmBox} cls="wifi-confirm" lines=${confirmLines(net, confirm.ssid, variant)}
      confirmLabel=${'断开去连「' + confirm.ssid + '」'} onCancel=${() => setConfirm(null)} onConfirm=${start} /></div>` : null}
  </div>`;
}

export function WifiCard({ net, link, secure }) {
  if (!net || !net.known || net.mode !== 'hotspot') return null;
  return html`<section class="board wifi-card" aria-label="连 WiFi">
    <h2>连 WiFi</h2>
    <p class="wifi-lead">现在是鸭子自己的热点（${net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : 'Microduck'}）。
      选家里的 WiFi、填密码，鸭子就连过去；之后在家里 WiFi 下打开 ${net.url_local || 'duck-xxxx.local'} 。</p>
    <${LastTry} net=${net} />
    <${WifiFlow} net=${net} link=${link} />
    ${secure === false ? html`<div class="wifi-note" role="note">热点密码大家都知道，附近的人也能连上控制鸭子；在外面演示前，去「更多」设个登录密码</div>` : null}
  </section>`;
}

export function WifiSettings({ net, link }) {
  const [flow, setFlow] = useState(false);
  const [scan, setScan] = useState(null);
  const [forget, setForget] = useState(null);
  const [msg, setMsg] = useState(null);
  const load = async () => {
    const r = await link.cmd('net.op', { op: 'scan' }, 25000);
    setScan(r.ok ? (r.data || { networks: [] }) : { networks: [], error: r.reason || r.error });
  };
  useEffect(() => {
    if (!net || !net.known) return undefined;
    let alive = true;
    (async () => { await link.whenOpen(); if (alive) await load(); })();
    return () => { alive = false; };
  }, [net && net.known]);
  if (!net || !net.known) return null;
  const saved = (scan && scan.networks ? scan.networks : []).filter((n) => n.saved);
  const doForget = async (ssid) => {
    setForget(null); setMsg(null);
    const r = await link.cmd('net.op', { op: 'forget', ssid }, 15000);
    if (!r.ok) { setMsg(r.reason || r.error || '没忘掉'); return; }
    setMsg(r.data && r.data.removed === false ? `鸭子本来就没记着「${ssid}」` : `忘掉了「${ssid}」`);
    load();
  };
  const current = net.mode === 'hotspot' ? '鸭子自己的热点' : (net.ssid || '没连着 WiFi');
  return html`<div class="board wifi-settings" aria-label="WiFi 设置">
    <h2>WiFi</h2>
    <${LastTry} net=${net} />
    <div class="wifi-now">
      <div class="big">现在：${current}</div>
      ${net.mode === 'hotspot' ? html`<div>热点 ${net.hotspot && net.hotspot.ssid ? net.hotspot.ssid : '—'} · 密码 ${net.hotspot && net.hotspot.psk ? net.hotspot.psk : '—'}</div>`
        : net.mode === 'wifi' ? html`<div class="wifi-actions"><${Bars} signal=${net.signal} /><span>信号 ${net.signal ?? '—'}</span><span>IP ${net.ip4 || '—'}</span></div>`
          : html`<div>现在没连着 WiFi。</div>`}
      <div>地址：<a href=${net.url_local}>${(net.url_local || '').replace(/^https?:\/\//, '') || '—'}</a></div>
    </div>
    <div class="wifi-actions"><button class="wifi-btn primary" type="button" onClick=${() => setFlow(!flow)}>
      ${flow ? '收起' : '换一个 WiFi'}</button></div>
    ${flow ? html`<div class="wifi-flow"><${WifiFlow} net=${net} link=${link} variant="switch" /></div>` : null}
    <div>
      <div class="wifi-note">已保存的网络</div>
      ${scan && scan.error ? html`<div class="wifi-msg">${scan.error}</div>` : null}
      ${saved.length ? saved.map((n) => html`<div class="wifi-saved-row">
        <span class="wifi-name">${n.ssid}</span>
        ${n.ssid === net.ssid ? html`<span class="wifi-badge">正在用</span>` : null}
        <button class="wifi-btn wifi-forget" type="button" data-ssid=${n.ssid}
          onClick=${() => n.ssid === net.ssid ? setForget(n.ssid) : doForget(n.ssid)}>忘掉</button>
      </div>`) : html`<div class="wifi-note">${scan ? '还没有已保存的 WiFi。' : '读取中…'}</div>`}
    </div>
    ${msg ? html`<div class="wifi-note">${msg}</div>` : null}
    ${forget ? html`<div class="wifi-confirm-wrap"><${ConfirmBox} cls="wifi-confirm"
      lines=${[`忘掉「${forget}」以后鸭子会断开；没有别的 WiFi 可连的话，1 分钟后开热点。`]}
      confirmLabel="忘掉" onCancel=${() => setForget(null)} onConfirm=${() => doForget(forget)} /></div>` : null}
  </div>`;
}
