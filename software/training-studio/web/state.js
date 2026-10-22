export const CONFIG_FIELDS = [
  {key:'num_envs',label:'并行环境',min:16,max:16384,step:4,help:'同时在仿真中练习的小鸭子数量，需为 4 的倍数。更多环境会占用更多显存。'},
  {key:'iterations',label:'训练轮数',min:1,max:100000,step:1,help:'计划执行的训练迭代次数，不代表动作学会的百分比。'},
  {key:'save_interval',label:'保存间隔',min:1,max:10000,step:1,help:'每隔多少轮保存一个可以评估、继续训练的检查点。'},
  {key:'seed',label:'随机种子',min:0,max:2147483647,step:1,help:'记录随机种子，方便复现实验条件。'},
  {key:'learning_rate',label:'学习率',min:0.000001,max:0.01,step:'any',help:'每次学习的更新步幅。建议先使用配方默认值。'},
];
export const FALLBACK_DEFAULTS = {num_envs:2048,iterations:1000,save_interval:50,seed:42,learning_rate:0.001};
export function defaultsFor(recipe) { return {...FALLBACK_DEFAULTS,...recipe?.defaults}; }
export function metersToCm(value) { return value===''||value===null||value===undefined?'':Number((Number(value)*100).toFixed(6)); }
export function cmToMeters(value) { return typeof value==='string'&&!value.trim()?'':Number((Number(value)/100).toFixed(8)); }
export function normalizeSkill(recipe, value) {
  if(!recipe?.skill_defaults)return null;
  if(value!==undefined&&value!==null&&(typeof value!=='object'||Array.isArray(value)))throw new Error('请检查动作目标参数');
  const fields=['support_side','lift_height_m','hold_seconds'];
  if(Object.keys(value||{}).some(key=>!fields.includes(key)))throw new Error('动作目标包含不支持的参数');
  const skill={...recipe.skill_defaults,...value},limits=recipe.skill_limits||{};
  if(!(limits.support_side||['left','right']).includes(skill.support_side))throw new Error('请选择机器人自身的左脚或右脚作为支撑脚');
  for(const key of ['lift_height_m','hold_seconds']) {
    const raw=skill[key],n=Number(raw),limit=limits[key];
    if(raw===null||typeof raw==='boolean'||(typeof raw==='string'&&!raw.trim())||!Number.isFinite(n)||!limit||n<limit.min||n>limit.max)throw new Error(key==='lift_height_m'?'请填写范围内的抬脚高度':'请填写范围内的保持时间');
    skill[key]=n;
  }
  return skill;
}
export function skillSummary(skill) {
  if(!skill)return '';
  return `${skill.support_side==='right'?'右':'左'}脚支撑 · ${skill.support_side==='right'?'左':'右'}脚抬高 ${formatNumber(metersToCm(skill.lift_height_m),2)} cm · 保持 ${formatNumber(skill.hold_seconds,1)} 秒`;
}
export function recipeTitle(value, recipes=[]) {
  const id=typeof value==='string'?value:value?.recipe_id||value?.id;
  return recipes.find(r=>r.id===id)?.title||value?.title||value?.recipe_title||({'hd1910-flat':'HD1910 平地行走','hd1910-rough':'HD1910 起伏地形','hd1910-single-leg':'HD1910 单脚平衡'}[id])||id||'训练配方';
}
export function recipeCatalog(recipe={}) {
  const meta=recipe.catalog||{},balance=!!recipe.skill_defaults;
  const fallbackPreview=balance?'balance_target':recipe.id==='hd1910-flat'?'robot_model':'text';
  let preview=['robot_model','text','balance_target'].includes(meta.preview_kind)?meta.preview_kind:fallbackPreview;
  if(preview==='balance_target'&&!balance)preview='text';
  const strings=value=>Array.isArray(value)?value.filter(s=>typeof s==='string'&&s.trim()).map(s=>s.trim()):[];
  const instructions=strings(meta.instructions);
  const verified=meta.verification_state==='pipeline';
  return {category:typeof meta.category==='string'&&meta.category.trim()?meta.category.trim():balance?'平衡':['hd1910-flat','hd1910-rough'].includes(recipe.id)?'行走':'其他',
    tags:strings(meta.tags),preview_kind:preview,source_label:meta.source_label||'项目内置',
    verification_state:verified?'pipeline':'unverified',verification_label:meta.verification_label||(verified?'已完成短试跑':'验证记录未提供'),
    instructions:instructions.length?instructions:['选择配方并设置练习参数。','完成短试跑后开始正式训练。','保存检查点，运行评估并查看回放。']};
}
export function recipeCategories(recipes=[]) { return ['全部',...new Set(recipes.map(recipe=>recipeCatalog(recipe).category))]; }
export function filterRecipes(recipes=[],{query='',category='全部'}={}) {
  const terms=String(query).trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return recipes.filter(recipe=>{const catalog=recipeCatalog(recipe),text=[recipeTitle(recipe),recipe.description||'',catalog.category,...catalog.tags].join(' ').toLocaleLowerCase();return (category==='全部'||catalog.category===category)&&terms.every(term=>text.includes(term));});
}
export function runDraft(run) {
  return {recipe_id:run.recipe_id,config:run.kind==='smoke'?{seed:run.config.seed,learning_rate:run.config.learning_rate}:{...run.config},profile:run.profile,kind:run.kind==='smoke'&&run.status==='completed'?'train':'smoke',...(run.skill?{skill:{...run.skill}}:{})};
}
export function evaluationStats(result, demo=false) {
  if(demo||!Number.isInteger(result?.trials)||result.trials<=0||!Number.isInteger(result?.successes)||result.successes<0||result.successes>result.trials)return null;
  return {trials:result.trials,successes:result.successes,success_rate:result.successes/result.trials};
}
export function advancedChanges(config, defaults) {
  return CONFIG_FIELDS.filter(f => Number(config[f.key]) !== Number(defaults[f.key])).map(f=>({...f,value:Number(config[f.key]),original:Number(defaults[f.key])}));
}
export function effectiveConfig(form, defaults) {
  const config = Object.fromEntries(CONFIG_FIELDS.map(({key})=>[key,Number(form.config?.[key] ?? defaults[key])]));
  return form.kind === 'smoke' ? {...config,num_envs:64,iterations:5,save_interval:1} : config;
}
function canonical(value) { return JSON.stringify(value, function(key, v) {return v && typeof v==='object' && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])) : v;}); }
export function hasMatchingSmoke(runs,recipeId,mode,config,profile=null,skill=null) {
  const goal=s=>s?canonical({...s,lift_height_m:Number(s.lift_height_m),hold_seconds:Number(s.hold_seconds)}):null;
  return runs.some(r=>r.recipe_id===recipeId&&r.mode===mode&&r.kind==='smoke'&&r.status==='completed'&&Number(r.config?.seed)===Number(config.seed)&&Number(r.config?.learning_rate)===Number(config.learning_rate)&&canonical(r.profile??null)===canonical(profile)&&goal(r.skill)===goal(skill));
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
export function resourceNumber(value,digits=1,suffix='') { return typeof value==='number'&&Number.isFinite(value)&&value>=0?`${formatNumber(value,digits)}${suffix}`:'—'; }
export function resourceMemory(used,total,unit='bytes') {
  const divisor=unit==='mib'?1024:1024**3;
  const gib=value=>typeof value==='number'?value/divisor:null;
  return `${resourceNumber(gib(used),1)} / ${resourceNumber(gib(total),1)} GiB`;
}
export function resourceStatus(snapshot,error='',secondsSinceReceipt=0) {
  if(!snapshot)return {label:error?'暂不可读取':'正在采集',tone:error?'amber':'neutral',stale:!!error};
  // Remote sampled_at is display-only: the execution host may have a different clock.
  const validAge=typeof snapshot.age_seconds==='number'&&Number.isFinite(snapshot.age_seconds)&&snapshot.age_seconds>=0;
  const localAge=Number.isFinite(secondsSinceReceipt)?Math.max(0,secondsSinceReceipt):0;
  const stale=!!error||snapshot.stale===true||(validAge&&snapshot.age_seconds+localAge>10);
  if(stale)return {label:'更新中断 · 上次采样',tone:'amber',stale:true};
  if(snapshot.status==='pending')return {label:'正在采集',tone:'neutral',stale:false};
  if(snapshot.status==='unavailable')return {label:'暂不可读取',tone:'amber',stale:false};
  if(!validAge)return {label:'采样时间未知',tone:'amber',stale:true};
  if(snapshot.status==='partial')return {label:'部分指标可用',tone:'neutral',stale:false};
  return {label:'实时更新',tone:'green',stale:false};
}
export function safeExternalUrl(value) {
  if(typeof value!=='string'||!/^https:\/\//i.test(value))return null;
  try { const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password?url.href:null; } catch { return null; }
}
export function filterPretrained(models=[],{query='',category='全部',source='all'}={}) {
  const terms=String(query).trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return models.filter(model=>{
    const text=[model.title,model.description,model.category,model.servos,model.source_label,model.author,model.version,...(model.tags||[])].filter(value=>typeof value==='string').join(' ').toLocaleLowerCase();
    return (category==='全部'||category===model.category)&&(source==='all'||source===model.source_kind)&&terms.every(term=>text.includes(term));
  });
}
