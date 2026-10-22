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

const balanceRecipe = {id:'hd1910-single-leg',title:'HD1910 单脚平衡',skill_defaults:{support_side:'left',lift_height_m:.01,hold_seconds:3},skill_limits:{support_side:['left','right'],lift_height_m:{min:.005,max:.02,step:.005},hold_seconds:{min:1,max:5,step:1}}};
test('balance goal normalizes numeric input and uses recipe defaults without mutating them', () => {
  const normalize=feature('normalizeSkill');
  assert.deepEqual(normalize(balanceRecipe),balanceRecipe.skill_defaults);
  assert.deepEqual(normalize(balanceRecipe,{support_side:'right',lift_height_m:'0.015',hold_seconds:'4'}),{support_side:'right',lift_height_m:.015,hold_seconds:4});
  assert.equal(balanceRecipe.skill_defaults.support_side,'left');
  assert.equal(normalize({id:'hd1910-flat'}),null);
});
test('balance goal rejects blank, nonfinite, unsupported and out-of-range values', () => {
  const normalize=feature('normalizeSkill');
  for(const value of ['',true,NaN,Infinity,.03]) assert.throws(()=>normalize(balanceRecipe,{lift_height_m:value}));
  assert.throws(()=>normalize(balanceRecipe,{support_side:'both'}));
  assert.throws(()=>normalize(balanceRecipe,{hold_seconds:0}));
  assert.throws(()=>normalize(balanceRecipe,{unknown:1}));
});
test('centimeter display and meter payload retain conservative half-centimeter steps', () => {
  assert.equal(feature('metersToCm')(.005),.5);
  assert.equal(feature('metersToCm')(.015),1.5);
  assert.equal(feature('cmToMeters')('1.5'),.015);
  assert.equal(feature('cmToMeters')(''),'');
});
test('a completed balance smoke qualifies only for exactly the same goal', () => {
  const ready=feature('hasMatchingSmoke'),skill=balanceRecipe.skill_defaults;
  const smoke={recipe_id:balanceRecipe.id,mode:'real',kind:'smoke',status:'completed',config:defaults,skill};
  assert.equal(ready([smoke],balanceRecipe.id,'real',defaults,null,{...skill,lift_height_m:'0.01'}),true);
  for(const change of [{support_side:'right'},{lift_height_m:.015},{hold_seconds:4}]) assert.equal(ready([smoke],balanceRecipe.id,'real',defaults,null,{...skill,...change}),false);
  assert.equal(ready([{...smoke,skill:undefined}],balanceRecipe.id,'real',defaults,null,skill),false);
  assert.equal(ready([smoke],balanceRecipe.id,'real',defaults,null,null),false);
});
test('balance summaries distinguish support and lifted feet and identify the right recipe', () => {
  assert.match(feature('skillSummary')(balanceRecipe.skill_defaults),/左脚支撑.*右脚抬高 1 cm.*保持 3 秒/);
  assert.match(feature('skillSummary')({...balanceRecipe.skill_defaults,support_side:'right'}),/右脚支撑.*左脚抬高/);
  assert.equal(feature('recipeTitle')({recipe_id:balanceRecipe.id},[balanceRecipe]),balanceRecipe.title);
  assert.equal(feature('recipeTitle')({recipe_id:balanceRecipe.id}),'HD1910 单脚平衡');
});
test('copy and smoke-to-training preserve the archived action goal independently', () => {
  const run={recipe_id:balanceRecipe.id,kind:'smoke',status:'completed',config:defaults,skill:{...balanceRecipe.skill_defaults},profile:{schema:'microduck-studio-duck-profile/v1'}};
  const draft=feature('runDraft')(run);
  assert.equal(draft.kind,'train');
  assert.deepEqual(draft.skill,run.skill);
  draft.skill.support_side='right';
  assert.equal(run.skill.support_side,'left');
  assert.deepEqual(draft.config,{seed:42,learning_rate:.001});
  assert.equal(Object.hasOwn(feature('runDraft')({...run,recipe_id:'hd1910-flat',skill:undefined}),'skill'),false);
});
test('evaluation evidence never treats missing or demonstration counts as physical success', () => {
  const stats=feature('evaluationStats');
  assert.equal(stats({trials:3,successes:null,success_rate:null}),null);
  assert.equal(stats({trials:null,successes:0}),null);
  assert.equal(stats({trials:3,successes:4}),null);
  assert.equal(stats({trials:3,successes:1},true),null);
  assert.deepEqual(stats({trials:3,successes:0,success_rate:0}),{trials:3,successes:0,success_rate:0});
  assert.deepEqual(stats({trials:4,successes:1,success_rate:.25}),{trials:4,successes:1,success_rate:.25});
});
const catalogRecipes=[
  {id:'hd1910-flat',title:'HD1910 平地行走',description:'练习向前走和转向',catalog:{category:'行走',tags:['基础步态','平地'],preview_kind:'robot_model',source_label:'项目内置',verification_state:'pipeline',verification_label:'已完成短试跑',instructions:['选择参数','短试跑','评估检查点']}},
  {id:'hd1910-rough',title:'HD1910 起伏地形',description:'适应坡面和不平整地面',catalog:{category:'行走',tags:['地形适应'],preview_kind:'text',verification_state:'unverified',verification_label:'待 GPU 验证'}},
  {...balanceRecipe,catalog:{category:'平衡',tags:['单脚','左右可选'],preview_kind:'balance_target',verification_state:'pipeline',verification_label:'已完成短试跑'}}
];
test('recipe catalog search combines category with case-insensitive title, description and tags', () => {
  const filter=feature('filterRecipes');
  assert.deepEqual(filter(catalogRecipes,{query:' hd1910   地形 ',category:'行走'}).map(r=>r.id),['hd1910-rough']);
  assert.deepEqual(filter(catalogRecipes,{query:'左右可选'}).map(r=>r.id),['hd1910-single-leg']);
  assert.deepEqual(filter(catalogRecipes,{query:'坡面'}).map(r=>r.id),['hd1910-rough']);
  assert.deepEqual(filter(catalogRecipes,{query:'单脚',category:'行走'}),[]);
  assert.deepEqual(filter(catalogRecipes,{query:'   ',category:'全部'}),catalogRecipes);
});
test('catalog categories follow available recipes and never add unavailable actions', () => {
  assert.deepEqual(feature('recipeCategories')(catalogRecipes),['全部','行走','平衡']);
  assert.deepEqual(feature('recipeCategories')([]),['全部']);
  const filtered=feature('filterRecipes')(catalogRecipes,{category:'平衡'});
  assert.equal(filtered[0],catalogRecipes[2]);
  assert.equal(catalogRecipes.length,3);
});
test('old recipe metadata falls back to available previews without inventing verification', () => {
  const catalog=feature('recipeCatalog');
  assert.equal(catalog({id:'hd1910-flat'}).preview_kind,'robot_model');
  assert.equal(catalog({id:'hd1910-rough'}).preview_kind,'text');
  assert.equal(catalog(balanceRecipe).preview_kind,'balance_target');
  assert.equal(catalog(balanceRecipe).verification_state,'unverified');
  assert.equal(catalog(balanceRecipe).verification_label,'验证记录未提供');
  assert.equal(catalog(catalogRecipes[0]).verification_label,'已完成短试跑');
  assert.equal(catalog({id:'future',catalog:{preview_kind:'unknown',tags:null,instructions:null}}).preview_kind,'text');
  assert.equal(catalog({id:'future'}).instructions.length,3);
});

test('resource numbers distinguish missing measurements from a real zero', () => {
  const number=feature('resourceNumber');
  for(const value of [null,undefined,'',false,NaN,Infinity,-1]) assert.equal(number(value,1,'%'),'—');
  assert.equal(number(0,1,'%'),'0%');
  assert.equal(number(38.26,1,' °C'),'38.3 °C');
  assert.equal(feature('resourceMemory')(1024**3,8*1024**3),'1 / 8 GiB');
  assert.equal(feature('resourceMemory')(null,8*1024**3),'— / 8 GiB');
});
test('resource freshness keeps a failed or old sample from looking live', () => {
  const status=feature('resourceStatus'),fresh={status:'ready',age_seconds:1,stale:false};
  assert.equal(status(null).label,'正在采集');
  assert.equal(status({status:'pending',age_seconds:null}).label,'正在采集');
  assert.equal(status(fresh).label,'实时更新');
  assert.equal(status({...fresh,status:'partial'}).label,'部分指标可用');
  assert.equal(status({...fresh,age_seconds:20}).stale,true);
  assert.equal(status({...fresh,stale:true}).stale,true);
  assert.equal(status(fresh,'网络断开').stale,true);
  assert.equal(status({status:'unavailable',age_seconds:null}).label,'暂不可读取');
  assert.equal(status({status:'ready',age_seconds:null}).label,'采样时间未知');
});
test('resource freshness ignores remote wall clock offsets and ages after browser suspension', () => {
  const status=feature('resourceStatus');
  for(const sampled_at of ['2000-01-01T00:00:00Z','2099-12-31T00:00:00Z']) {
    const fresh={status:'ready',age_seconds:1,stale:false,sampled_at};
    assert.equal(status(fresh).label,'实时更新');
    assert.equal(status(fresh,'',2).label,'实时更新');
    assert.equal(status(fresh,'',11).stale,true);
    assert.equal(status({...fresh,age_seconds:9},'',2).stale,true);
  }
});
test('pretrained links allow only absolute HTTPS without embedded credentials', () => {
  const safe=feature('safeExternalUrl');
  assert.equal(safe('https://huggingface.co/pollen/model/tree/v8'),'https://huggingface.co/pollen/model/tree/v8');
  for(const url of ['javascript:alert(1)','data:text/html,x','//example.com','http://example.com','https://user:pass@example.com',null]) assert.equal(safe(url),null);
});
test('pretrained search combines actual source and category without making recipes', () => {
  const models=[{id:'official-walk',title:'行走',category:'行走',source_kind:'official',source_label:'Pollen Robotics 官方',servos:'XL330',version:'V8',tags:['恢复']},{id:'kiss-walk',title:'行走',category:'行走',source_kind:'community',source_label:'kissqy 社区',servos:'HD1910',version:'V167',tags:['恢复']},{id:'kiss-spin',title:'原地旋转',category:'滑轮',source_kind:'community',servos:'HD1910',tags:[]}];
  assert.deepEqual(feature('filterPretrained')(models,{query:'v8 xl330',source:'official'}).map(m=>m.id),['official-walk']);
  assert.deepEqual(feature('filterPretrained')(models,{query:'恢复',category:'行走',source:'community'}).map(m=>m.id),['kiss-walk']);
  assert.deepEqual(feature('filterPretrained')(models,{query:'unknown'}),[]);
  assert.equal(models.length,3);
});
