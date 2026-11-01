import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';

const moduleUrl = new URL('../web/models.js', import.meta.url);
const ui = existsSync(moduleUrl) ? await import(moduleUrl) : {};
const view = {
  slots: [
    { slot: 'walk', label: 'Andar / manter posição', model_id: 'walk-default' },
    { slot: 'ground_pick', label: 'Abaixar-se para pegar um objeto', model_id: 'duck-new' },
    { slot: 'roulade', label: 'Cambalhota para a frente', model_id: 'flip-default' },
  ],
  items: [{ id: 'duck-new', name: 'Meu modelo para pegar objetos' }, { id: 'flip-default', name: 'Cambalhota integrada' }],
  bindings: [{ button: 'a', label: 'A', slot: 'roulade', skill: 'roulade', model_id: 'flip-default' }],
};

test('using an installed model never presents it as currently executing', () => {
  assert.equal(typeof ui.modelState, 'function', 'model status helper must exist');
  assert.deepEqual(ui.modelState({ installed: true, slots: ['ground_pick'], running: false }), ['Instalado', 'Selecionado']);
  assert.deepEqual(ui.modelState({ installed: true, slots: [], running: true }), ['Instalado', 'Em execução']);
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
  assert.equal(choice.currentLabel, 'Cambalhota para a frente · Cambalhota integrada');
  assert.equal(choice.targetLabel, 'Abaixar-se para pegar um objeto · Meu modelo para pegar objetos');
  assert.equal(ui.bindingChoice(view, 'a', 'roulade').already, true);
});

test('walking cannot be assigned to a skill button and reserved buttons cannot be changed', () => {
  assert.equal(typeof ui.bindingChoice, 'function', 'binding decision helper must exist');
  assert.equal(ui.bindingChoice(view, 'a', 'walk').valid, false);
  assert.equal(ui.bindingChoice(view, 'start', 'ground_pick').valid, false);
});

test('missing runtime capabilities disable changes and retain a useful reason', () => {
  assert.equal(typeof ui.operationAvailability, 'function', 'operation capability helper must exist');
  const unavailable = ui.operationAvailability({ error: 'O programa principal não está conectado' });
  assert.equal(unavailable.select, false);
  assert.equal(unavailable.import, false);
  assert.equal(unavailable.reason, 'O programa principal não está conectado');
  assert.equal(ui.operationAvailability({ capabilities: { rename: true, select: false, reason: 'Desligue os motores primeiro' } }).rename, true);
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
  finish({ ok: true, data: { items: [{ name: 'Nome antigo' }] } });
  assert.equal(await refresh, null);
});

test('a stale failed refresh cannot turn a successful model operation into an offline page', async () => {
  assert.equal(typeof ui.createModelReader, 'function', 'model refresh ordering helper must exist');
  let fail;
  const reader = ui.createModelReader(() => new Promise((resolve, reject) => { fail = reject; }));
  const refresh = reader.read();
  reader.invalidate();
  fail(new Error('A solicitação anterior expirou'));
  assert.equal(await refresh, null);
  const current = ui.createModelReader(async () => { throw new Error('A solicitação atual expirou'); });
  await assert.rejects(current.read(), /A solicitação atual expirou/);
});
