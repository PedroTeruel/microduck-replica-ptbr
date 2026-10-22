export const CONFIG_FIELDS = [
  {key:'num_envs',label:'并行环境',min:16,max:16384,step:4,help:'同时在仿真中练习的小鸭子数量，需为 4 的倍数。更多环境会占用更多显存。'},
  {key:'iterations',label:'训练轮数',min:1,max:100000,step:1,help:'计划执行的训练迭代次数，不代表动作学会的百分比。'},
  {key:'save_interval',label:'保存间隔',min:1,max:10000,step:1,help:'每隔多少轮保存一个可以评估、继续训练的检查点。'},
  {key:'seed',label:'随机种子',min:0,max:2147483647,step:1,help:'记录随机种子，方便复现实验条件。'},
  {key:'learning_rate',label:'学习率',min:0.000001,max:0.01,step:'any',help:'每次学习的更新步幅。建议先使用配方默认值。'},
];
export const FALLBACK_DEFAULTS = {num_envs:2048,iterations:1000,save_interval:50,seed:42,learning_rate:0.001};
export function defaultsFor(recipe) { return {...FALLBACK_DEFAULTS,...recipe?.defaults}; }
export function advancedChanges(config, defaults) {
  return CONFIG_FIELDS.filter(f => Number(config[f.key]) !== Number(defaults[f.key])).map(f=>({...f,value:Number(config[f.key]),original:Number(defaults[f.key])}));
}
export function effectiveConfig(form, defaults) {
  const config = Object.fromEntries(CONFIG_FIELDS.map(({key})=>[key,Number(form.config?.[key] ?? defaults[key])]));
  return form.kind === 'smoke' ? {...config,num_envs:64,iterations:5,save_interval:1} : config;
}
function canonical(value) { return JSON.stringify(value, function(key, v) {return v && typeof v==='object' && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])) : v;}); }
export function hasMatchingSmoke(runs,recipeId,mode,config,profile=null) {
  return runs.some(r=>r.recipe_id===recipeId&&r.mode===mode&&r.kind==='smoke'&&r.status==='completed'&&Number(r.config?.seed)===Number(config.seed)&&Number(r.config?.learning_rate)===Number(config.learning_rate)&&canonical(r.profile??null)===canonical(profile));
}
export function runActions(run, environment={}) {
  const status=run?.status, ready=['stopped','completed','failed','interrupted'].includes(status);
  const busy=run?.operation?.status==='running', checkpoints=run?.checkpoints?.length>0;
  return {pause:!busy && status==='running' && (run?.mode==='demo'||environment.pause_supported===true),
    resume:!busy && (status==='paused'||(ready&&checkpoints)),stop:!busy&&['starting','running','paused'].includes(status),
    evaluate:!busy&&ready&&checkpoints,export:!busy&&ready&&checkpoints};
}
export function actionPayload(run,action,checkpoint) {
  return checkpoint&&(['evaluate','export'].includes(action)||(action==='resume'&&run.status!=='paused'))?{checkpoint_id:checkpoint.id}:{};
}
export function comparisonCandidates(runs, base) {
  return runs.filter(r=>r.id!==base?.id&&r.task_id===base?.task_id&&r.mode===base?.mode&&r.kind!=='smoke');
}
export function metricPoints(metrics=[], key='reward') {
  return metrics.filter(m=>Number.isFinite(m.iteration)&&Number.isFinite(m[key])).map(m=>({x:m.iteration,y:m[key]}));
}
export function profileSummary(profile) {
  if (!profile||profile.schema!=='microduck-studio-duck-profile/v1') throw new Error('请选择 Studio 导出的鸭子档案（JSON）');
  return {label:profile.duck?.label||profile.duck?.name_on_duck||'未命名鸭子',mass:profile.body?.total_g??profile.body?.mass_g??null,
    joints:Array.isArray(profile.joints)?profile.joints.length:0,imu:profile.imu?.chip||'未记录',verified:profile.imu?.verified===true};
}
export const STATUS = {starting:'准备中',running:'训练中',paused:'已暂停',stopping:'正在停止',stopped:'已停止',completed:'已完成',failed:'失败',interrupted:'已中断'};
export function statusText(run) { return STATUS[run?.status]||run?.status||'等待训练'; }
export function formatNumber(value, digits=1) { return Number.isFinite(Number(value))&&value!==null&&value!==undefined?Number(value).toLocaleString('zh-CN',{maximumFractionDigits:digits}):'—'; }
export function elapsed(seconds=0) { const n=Math.max(0,Math.floor(seconds||0)); return n>=3600?`${Math.floor(n/3600)}小时 ${Math.floor(n%3600/60)}分`:n>=60?`${Math.floor(n/60)}分 ${n%60}秒`:`${n}秒`; }
export function dateText(value) { if(!value)return '—';const d=new Date(typeof value==='number'&&value<1e12?value*1000:value);return Number.isNaN(d.valueOf())?'—':new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(d); }
