import test from 'node:test';
import assert from 'node:assert/strict';

let state = {};
try { state = await import('../web/state.js'); } catch (error) {
  if (error.code !== 'ERR_MODULE_NOT_FOUND') throw error;
}
function feature(name) { assert.equal(typeof state[name], 'function', `${name} behavior must exist`); return state[name]; }
const defaults = {num_envs: 2048, iterations: 2000, save_interval: 100, seed: 42, learning_rate: 0.001};

test('short run uses exactly 64 environments and five iterations, retaining the formal settings', () => {
  const form = {kind: 'smoke', config: {...defaults, num_envs: 4096, iterations: 8000}};
  const config = feature('effectiveConfig')(form, defaults);
  assert.equal(config.num_envs, 64);
  assert.equal(config.iterations, 5);
  assert.equal(form.config.num_envs, 4096);
  assert.equal(form.config.iterations, 8000);
});
test('custom advanced settings remain counted independently of disclosure visibility', () => {
  const config = {...defaults, num_envs: 4096, learning_rate: 0.0003};
  assert.deepEqual(feature('advancedChanges')(config, defaults).map(x => x.key).sort(), ['learning_rate', 'num_envs']);
});
test('equivalent numeric input strings do not create phantom customizations', () => {
  assert.equal(feature('advancedChanges')({...defaults, iterations: '2000'}, defaults).length, 0);
});
test('real run cannot offer a pause on an unsupported platform', () => {
  const a = feature('runActions')({status:'running', mode:'real', checkpoints:[]}, {pause_supported:false});
  assert.equal(a.pause, false);
  assert.equal(a.stop, true);
});
test('paused run resumes in place while stopped run needs a saved checkpoint', () => {
  const actions = feature('runActions');
  assert.equal(actions({status:'paused', mode:'demo'}, {}).resume, true);
  assert.equal(actions({status:'stopped', checkpoints:[]}, {}).resume, false);
  assert.equal(actions({status:'stopped', checkpoints:[{id:'10'}]}, {}).resume, true);
});
test('in-flight model operation prevents another export/evaluation', () => {
  const a = feature('runActions')({status:'completed', checkpoints:[{id:'5'}], operation:{status:'running'}}, {});
  assert.equal(a.export, false);
  assert.equal(a.evaluate, false);
});
test('comparison requires the same task and mode and excludes smoke checks', () => {
  const runs = [{id:'a',task_id:'flat',mode:'demo',kind:'train'}, {id:'b',task_id:'flat',mode:'real',kind:'train'}, {id:'c',task_id:'rough',mode:'demo',kind:'train'}, {id:'d',task_id:'flat',mode:'demo',kind:'smoke'}, {id:'e',task_id:'flat',mode:'demo',kind:'train'}];
  assert.deepEqual(feature('comparisonCandidates')(runs, runs[0]).map(x=>x.id), ['e']);
});
test('chart ignores missing/non-finite observations without inventing rewards', () => {
  const data = feature('metricPoints')([{iteration:0},{iteration:1,reward:2},{iteration:2,reward:NaN},{iteration:3,reward:4}], 'reward');
  assert.deepEqual(data, [{x:1,y:2},{x:3,y:4}]);
});
test('profile import accepts only the Studio schema and keeps missing measurements explicit', () => {
  const summarize = feature('profileSummary');
  assert.throws(()=>summarize({schema:'other'}), /档案|schema/);
  const s = summarize({schema:'microduck-studio-duck-profile/v1',duck:{label:'duck-70c3'},body:null});
  assert.equal(s.label, 'duck-70c3');
  assert.equal(s.mass, null);
});

test('formal training requires a smoke check matching learning parameters and archived profile', () => {
  const ready = feature('hasMatchingSmoke');
  const smoke={recipe_id:'flat',mode:'demo',kind:'smoke',status:'completed',config:{...defaults,num_envs:64,iterations:5,save_interval:1}};
  assert.equal(ready([smoke], 'flat', 'demo', defaults, null), true);
  assert.equal(ready([smoke], 'flat', 'demo', {...defaults,seed:43}, null), false);
  assert.equal(ready([smoke], 'flat', 'demo', {...defaults,learning_rate:.0003}, null), false);
  assert.equal(ready([smoke], 'flat', 'real', defaults, null), false);
  const profile={schema:'microduck-studio-duck-profile/v1',duck:{label:'D1'}};
  assert.equal(ready([smoke], 'flat', 'demo', defaults, profile), false);
  assert.equal(ready([{...smoke,profile}], 'flat', 'demo', defaults, {duck:{label:'D1'},schema:profile.schema}), true);
});

test('process controls send no checkpoint payload; stopped resume targets the selected checkpoint', () => {
  const payload=feature('actionPayload'),cp={id:'cp-5'};
  assert.deepEqual(payload({status:'running'},'pause',cp),{});
  assert.deepEqual(payload({status:'paused'},'stop',cp),{});
  assert.deepEqual(payload({status:'paused'},'resume',cp),{});
  assert.deepEqual(payload({status:'stopped'},'resume',cp),{checkpoint_id:'cp-5'});
  assert.deepEqual(payload({status:'completed'},'evaluate',cp),{checkpoint_id:'cp-5'});
});
