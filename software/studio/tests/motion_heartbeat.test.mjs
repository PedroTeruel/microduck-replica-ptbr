import test from 'node:test';
import assert from 'node:assert/strict';
import { createMotionHeartbeat, motionTime } from '../web/motion-heartbeat.js';

const live = (token = 'one') => ({ state: 'recording', session_id: token, owner: { mine: true } });
function setup(send = async () => ({ ok: true })) {
  const calls = [], callbacks = new Set(), errors = [];
  let active = true, connected = true;
  const lease = createMotionHeartbeat({
    send: args => { calls.push(args); return send(args); },
    isActive: () => active, isConnected: () => connected,
    schedule: cb => { callbacks.add(cb); return cb; }, cancel: cb => callbacks.delete(cb),
    onError: e => errors.push(e),
  });
  return { lease, calls, errors, tick: () => [...callbacks].forEach(cb => cb()),
    active: v => { active = v; }, connected: v => { connected = v; }, callbacks };
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

test('heartbeats only the owned live session; paused sessions keep their lease', async () => {
  const x = setup(); x.lease.sync(live()); await flush(); x.tick(); await flush();
  assert.equal(x.calls.filter(c => c.action === 'heartbeat').length, 2);
  x.lease.sync({ ...live(), state: 'record_paused' }); x.tick(); await flush();
  assert.equal(x.calls.at(-1).session_id, 'one');
  x.lease.sync({ ...live(), owner: { mine: false } });
  assert.equal(x.callbacks.size, 0);
});

test('inactive page sends a token-bound stop and cannot restart from stale snapshots', async () => {
  const x = setup(); x.lease.sync(live()); await flush();
  x.active(false); x.tick(); await flush();
  assert.deepEqual(x.calls.at(-1), { op: 'motion', action: 'stop', session_id: 'one' });
  x.active(true); x.lease.sync(live()); x.tick(); await flush();
  assert.equal(x.calls.filter(c => c.action === 'heartbeat').length, 1);
  x.lease.sync(live('two')); await flush();
  assert.equal(x.calls.at(-1).session_id, 'two');
});

test('disconnect stops timer and reconnect never resumes an old session', async () => {
  const x = setup(); x.lease.sync(live()); await flush();
  x.connected(false); x.tick(); await flush(); const count = x.calls.length;
  x.connected(true); x.lease.sync(live()); x.tick(); await flush();
  assert.equal(x.calls.length, count);
});

test('old heartbeat replies cannot cancel a newer token', async () => {
  const replies = []; const x = setup(() => new Promise(resolve => replies.push(resolve)));
  x.lease.sync(live('old')); x.lease.sync(live('new'));
  replies[0]({ ok: false, reason: 'old expired' }); await flush();
  assert.equal(x.errors.length, 0);
  assert.equal(x.calls.filter(c => c.action === 'stop').length, 0);
  replies[1]({ ok: true }); await flush(); x.tick();
  assert.equal(x.calls.at(-1).session_id, 'new');
});

test('a failed live heartbeat stops that session and reports its reason', async () => {
  const x = setup(async args => args.action === 'heartbeat' ? { ok: false, reason: '控制权已变化' } : { ok: true });
  x.lease.sync(live()); await flush();
  assert.equal(x.callbacks.size, 0); assert.deepEqual(x.errors, ['控制权已变化']);
  assert.equal(x.calls.at(-1).action, 'stop');
});

test('disposing while a heartbeat is pending sends one stop and never rearms', async () => {
  let reply; const x = setup(args => args.action === 'heartbeat' ? new Promise(r => { reply = r; }) : Promise.resolve({ ok: true }));
  x.lease.sync(live()); x.lease.dispose(); x.lease.dispose(); reply({ ok: true }); await flush();
  x.lease.sync(live('later')); x.tick();
  assert.equal(x.calls.filter(c => c.action === 'stop').length, 1);
  assert.equal(x.callbacks.size, 0);
});

test('drafts have no automation heartbeat and time formatting rejects bad values', () => {
  const x = setup(); x.lease.sync({ ...live(), state: 'draft' });
  assert.equal(x.calls.length, 0);
  assert.equal(motionTime(65.2), '1:05.2');
  assert.equal(motionTime(NaN), '0:00.0');
  assert.equal(motionTime(-1), '0:00.0');
});

const music = (token = 'music') => ({state:'idle_motion', idle_kind:'music', session_id:token, owner:{mine:true}});

test('standalone music has no action heartbeat and survives foreground interruption', async () => {
  const x = setup(); x.lease.sync(music()); await flush();
  assert.equal(x.calls.length, 0);
  assert.equal(x.callbacks.size, 0);
  x.active(false); x.lease.interrupt('inactive'); x.lease.sync(music()); x.tick(); await flush();
  assert.equal(x.calls.length, 0);
  x.active(true); x.lease.sync(music()); x.lease.interrupt(); await flush();
  assert.deepEqual(x.calls, [{op:'motion', action:'stop', session_id:'music'}]);
});

test('only standalone music survives inactivity; music during recording still stops', async () => {
  const x = setup(); x.lease.sync({...music(), state:'recording'}); await flush();
  x.active(false); x.lease.interrupt('inactive'); await flush();
  assert.equal(x.calls[0].action, 'heartbeat');
  assert.equal(x.calls.at(-1).action, 'stop');
});

test('confirmed music survives component disposal while the socket stays connected', async () => {
  const x = setup(); x.lease.sync(music()); x.lease.dispose(); await flush();
  assert.equal(x.calls.length, 0);
  assert.equal(x.callbacks.size, 0);
});

test('disconnected music token is blocked and never adopted from a stale snapshot', async () => {
  const x = setup(); x.lease.sync(music()); x.connected(false); x.lease.interrupt('disconnect');
  x.connected(true); x.lease.sync(music()); x.lease.interrupt(); await flush();
  assert.equal(x.calls.length, 0);
  x.lease.sync(music('new')); x.lease.interrupt(); await flush();
  assert.deepEqual(x.calls, [{op:'motion', action:'stop', session_id:'new'}]);
});
