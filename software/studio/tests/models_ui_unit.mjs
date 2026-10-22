import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';

const moduleUrl = new URL('../web/models.js', import.meta.url);
const ui = existsSync(moduleUrl) ? await import(moduleUrl) : {};
const view = {
  slots: [
    { slot: 'walk', label: '走路 / 保持', model_id: 'walk-default' },
    { slot: 'ground_pick', label: '低头捡东西', model_id: 'duck-new' },
    { slot: 'roulade', label: '前滚翻', model_id: 'flip-default' },
  ],
  items: [{ id: 'duck-new', name: '我的捡东西' }, { id: 'flip-default', name: '内置前滚翻' }],
  bindings: [{ button: 'a', label: 'A', slot: 'roulade', skill: 'roulade', model_id: 'flip-default' }],
};

test('using an installed model never presents it as currently executing', () => {
  assert.equal(typeof ui.modelState, 'function', 'model status helper must exist');
  assert.deepEqual(ui.modelState({ installed: true, slots: ['ground_pick'], running: false }), ['已安装', '当前选用']);
  assert.deepEqual(ui.modelState({ installed: true, slots: [], running: true }), ['已安装', '正在执行']);
});

test('a model can only be offered in server-approved purposes', () => {
  assert.equal(typeof ui.modelSlots, 'function', 'compatible purpose helper must exist');
  assert.deepEqual(ui.modelSlots(view, { allowed_slots: ['ground_pick', 'unknown'], suggested_slot: 'walk' }).map(s => s.slot), ['ground_pick']);
  assert.deepEqual(ui.modelSlots(view, { task: 'unknown' }), []);
});

test('a bound key requires an explicit replacement decision that names the old action', () => {
  assert.equal(typeof ui.bindingChoice, 'function', 'binding decision helper must exist');
  const choice = ui.bindingChoice(view, 'a', 'ground_pick');
  assert.equal(choice.valid, true);
  assert.equal(choice.conflict, true);
  assert.equal(choice.currentLabel, '前滚翻 · 内置前滚翻');
  assert.equal(choice.targetLabel, '低头捡东西 · 我的捡东西');
  assert.equal(ui.bindingChoice(view, 'a', 'roulade').already, true);
});

test('walking cannot be assigned to a skill button and reserved buttons cannot be changed', () => {
  assert.equal(typeof ui.bindingChoice, 'function', 'binding decision helper must exist');
  assert.equal(ui.bindingChoice(view, 'a', 'walk').valid, false);
  assert.equal(ui.bindingChoice(view, 'start', 'ground_pick').valid, false);
});

test('missing runtime capabilities disable changes and retain a useful reason', () => {
  assert.equal(typeof ui.operationAvailability, 'function', 'operation capability helper must exist');
  const unavailable = ui.operationAvailability({ error: '主程序没连接' });
  assert.equal(unavailable.select, false);
  assert.equal(unavailable.import, false);
  assert.equal(unavailable.reason, '主程序没连接');
  assert.equal(ui.operationAvailability({ capabilities: { rename: true, select: false, reason: '请先卸力' } }).rename, true);
});

test('physical key capture only accepts a fresh supported rising edge after a baseline', () => {
  assert.equal(typeof ui.captureKey, 'function', 'physical key capture helper must exist');
  const frame = buttons => ({ state: 'attached', buttons, last_ms: 0 });
  assert.equal(ui.captureKey(null, frame({ south: true })), null);
  assert.equal(ui.captureKey({ south: true }, frame({ south: true })), null);
  assert.equal(ui.captureKey({}, frame({ start: true })), null);
  assert.equal(ui.captureKey({}, frame({ south: true })), 'a');
  assert.equal(ui.captureKey({}, frame({ dd: true })), 'dpad_down');
  assert.equal(ui.captureKey({}, { ...frame({ west: true }), state: 'off' }), null);
  assert.equal(ui.captureKey({}, { ...frame({ west: true }), last_ms: 4000 }), null);
  assert.equal(ui.captureKey({}, frame({ south: true, west: true })), null);
});

test('physical capture falls back to the selector when a key can directly start recovery', () => {
  assert.equal(typeof ui.captureAllowed, 'function');
  const bindings = ['a', 'x', 'lb', 'rb', 'dpad_down'].map(button => ({ button, skill: '' }));
  assert.equal(ui.captureAllowed({ bindings }), true);
  bindings[2].skill = 'stand_test'; // robot.do has an explicit enable-independent recovery path.
  assert.equal(ui.captureAllowed({ bindings }), false);
  assert.equal(ui.captureAllowed({ bindings: [] }), false);
});

test('a refresh started before a model change cannot replace the confirmed result', async () => {
  assert.equal(typeof ui.createModelReader, 'function', 'model refresh ordering helper must exist');
  let finish;
  const reader = ui.createModelReader(() => new Promise(resolve => { finish = resolve; }));
  const refresh = reader.read();
  reader.invalidate(); // A rename/select/upload has started after this request.
  finish({ ok: true, data: { items: [{ name: '旧名称' }] } });
  assert.equal(await refresh, null);
});

test('a stale failed refresh cannot turn a successful model operation into an offline page', async () => {
  assert.equal(typeof ui.createModelReader, 'function', 'model refresh ordering helper must exist');
  let fail;
  const reader = ui.createModelReader(() => new Promise((resolve, reject) => { fail = reject; }));
  const refresh = reader.read();
  reader.invalidate();
  fail(new Error('旧请求超时'));
  assert.equal(await refresh, null);
  const current = ui.createModelReader(async () => { throw new Error('当前请求超时'); });
  await assert.rejects(current.read(), /当前请求超时/);
});
