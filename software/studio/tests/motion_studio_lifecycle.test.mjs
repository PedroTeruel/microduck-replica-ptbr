import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

let sequence = 0;
async function mount({motion = {state:'idle', idle_available:{ok:true}}, send = async () => ({ok:true, data:{session_id:'started'}})} = {}) {
  const calls = [], effects = [], cleanups = [], buttons = new Map(), events = new Map(), linkEvents = new Set();
  const activityEvents = new Set();
  const activity = {active:true, subscribe:fn => {activityEvents.add(fn); return () => activityEvents.delete(fn);}};
  const link = {status:'open', on:fn => {linkEvents.add(fn); return () => linkEvents.delete(fn);},
    cmd:(_, args) => {calls.push(args); return send(args);}};
  globalThis.window = {addEventListener:(name, fn) => events.set(name, fn), removeEventListener:name => events.delete(name)};
  globalThis.__motionHarness = {
    html:(strings, ...values) => {
      if (strings[0].trim().startsWith('<button type="button" class=')) {
        buttons.set(`${values[1]}:${values[2] || ''}`, values.find(value => typeof value === 'function'));
      }
      return {strings, values};
    },
    useEffect:fn => effects.push(fn), useRef:value => ({current:value}),
    useState:value => [typeof value === 'function' ? value() : value, () => {}],
  };
  let source = await readFile(new URL('../web/motion-studio.js', import.meta.url), 'utf8');
  source = source.replace(/import \{ html, useEffect, useRef, useState \} from [^;]+;/,
    'const {html, useEffect, useRef, useState} = globalThis.__motionHarness;');
  for (const file of ['motion-heartbeat.js', 'audio-ui-state.js']) {
    source = source.replace(`'./${file}'`, JSON.stringify(new URL(`../web/${file}`, import.meta.url).href));
  }
  const {MotionStudio} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}#${sequence++}`);
  MotionStudio({pad:{motion_studio:motion, audio:{available:true, listening:true, music:true}}, link, activity});
  for (const effect of effects) {const cleanup = effect(); if (cleanup) cleanups.push(cleanup);}
  return {calls, click:(action, kind = '') => buttons.get(`${action}:${kind}`)(),
    blur:() => events.get('blur')(),
    inactive:() => {activity.active = false; for (const fn of activityEvents) fn({active:false});},
    disconnect:() => {link.status = 'closed'; for (const fn of linkEvents) fn({t:'_status', status:'closed'});},
    dispose:() => {for (const cleanup of cleanups.reverse()) cleanup();}};
}
const flush = async () => {await Promise.resolve(); await Promise.resolve();};
const music = {state:'idle_motion', idle_kind:'music', idle_running:true, session_id:'live', owner:{mine:true}};

test('confirmed standalone music survives component blur, inactivity and unmount', async () => {
  const x = await mount({motion:music});
  try {x.blur(); x.inactive(); await flush(); assert.deepEqual(x.calls, []);}
  finally {x.dispose();}
  assert.deepEqual(x.calls, []);
});

test('ordinary lively blur sends a token-bound stop', async () => {
  const x = await mount({motion:{...music, idle_kind:'lively'}});
  try {x.blur(); await flush(); assert.equal(x.calls.at(-1).action, 'stop');}
  finally {x.dispose();}
});

test('foreground-authorized music start may finish after blur without a stop', async () => {
  let reply;
  const x = await mount({send:args => args.action === 'idle_start' ? new Promise(resolve => {reply = resolve;}) : Promise.resolve({ok:true})});
  try {
    const request = x.click('idle_start', 'music'); x.blur(); x.inactive();
    reply({ok:true, data:{session_id:'started'}}); await request; await flush();
    assert.deepEqual(x.calls.map(call => call.action), ['idle_start']);
  } finally {x.dispose();}
  assert.deepEqual(x.calls.map(call => call.action), ['idle_start']);
});

for (const ending of ['disconnect', 'dispose']) {
  test(`unconfirmed music start late reply is stopped after ${ending}`, async () => {
    let reply;
    const x = await mount({send:args => args.action === 'idle_start' ? new Promise(resolve => {reply = resolve;}) : Promise.resolve({ok:true})});
    const request = x.click('idle_start', 'music'); x[ending]();
    reply({ok:true, data:{session_id:'late'}}); await request; await flush();
    assert.deepEqual(x.calls.at(-1), {op:'motion', action:'stop', session_id:'late'});
    if (ending !== 'dispose') x.dispose();
  });
}
