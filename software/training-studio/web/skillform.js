import {html,useState,useEffect,useRef} from '/shared/vendor/preact-htm.module.js';
import {Icon,Badge} from './ui.js';
import {metersToCm,cmToMeters,formatNumber,skillSummary,evaluationStats,recipeTitle} from './state.js';

export function ActionLabEntry({recipes=[],onBrowse}) {
  const examples=recipes.slice(0,3).map(recipe=>recipeTitle(recipe)).join(' · ');
  return html`<section class="panel action-lab" aria-labelledby="action-lab-title"><div class="action-lab-heading"><div><span class="eyebrow">小鸭子的下一项本领</span><h2 id="action-lab-title">动作实验室</h2><p>浏览已经写好的配方，选择你想练习的动作。</p></div><div class="action-lab-badges"><${Badge}>无需写代码<//><${Badge}>${recipes.length} 个可用配方<//></div></div><div class="action-lab-body"><div class="action-lab-goal"><span class="action-glyph"><${Icon} name="balance" size=${34}/></span><div><h3>从一个练习目标开始</h3><p>${examples||'查看当前训练服务提供的配方'}</p><span class="muted small-copy">先看目标预览与动作说明，再设置自己的实验。</span></div></div><button class="btn primary" onClick=${onBrowse}>浏览动作配方<${Icon} name="arrow" size=${16}/></button></div><ol class="action-lab-steps"><li><b>1</b><span>浏览配方，理解目标</span></li><li><b>2</b><span>设置参数，短试跑后训练</span></li><li><b>3</b><span>评估检查点，观察实际结果</span></li></ol><p class="action-lab-note">预览帮助理解动作；是否学会，要看训练后的检查点评估结果。</p></section>`;
}

export function SkillTargetPreview({skill}) {
  const canvas=useRef(null),duck=useRef(null),jointNames=useRef([]),[ready,setReady]=useState(false),[error,setError]=useState('');
  useEffect(()=>{
    let active=true,instance;
    import('/shared/duck3d.js').then(async({Duck3D,JOINT_NAMES})=>{
      if(!active)return;
      jointNames.current=JOINT_NAMES;
      instance=new Duck3D(canvas.current,{view:'front34',centerX:.5,centerY:.47,fill:.8,pageScroll:true});duck.current=instance;
      await instance.load('/shared/model/');
      if(active)setReady(true);
    }).catch(e=>{if(active)setError(e.message);});
    return()=>{active=false;instance?.dispose();duck.current=null;};
  },[]);
  useEffect(()=>{
    if(!ready)return;
    // Named joints refer to the robot's own side. This pose illustrates a goal;
    // it is neither inverse kinematics nor an output of the learned policy.
    const lifted=skill.support_side==='right'?'left':'right',left=lifted==='left';
    const amount=.22+Math.max(0,Math.min(.02,Number(skill.lift_height_m)||.01))*8;
    const direction=left?1:-1;
    const pose={[`${lifted}_hip_pitch`]:direction*amount,[`${lifted}_knee`]:direction*amount*1.6,[`${lifted}_ankle`]:direction*amount*.6};
    duck.current?.setJoints(jointNames.current.map(name=>pose[name]||0));
  },[ready,skill.support_side,skill.lift_height_m]);
  const support=skill.support_side==='right'?'右':'左',lifted=support==='左'?'右':'左';
  return html`<figure class="skill-preview"><div class="duck-stage skill-stage"><canvas ref=${canvas} aria-label=${`单脚平衡目标示意：机器人自身${support}脚支撑，${lifted}脚抬起。可拖动旋转视角。`}/><span class="stage-label">目标示意 · 非训练结果</span>${!ready&&!error&&html`<div class="stage-loading"><span class="spinner"/>正在加载目标示意…</div>`}${error&&html`<div class="stage-loading">三维示意暂不可用<small>下方文字仍完整描述当前目标。</small></div>`}<div class="skill-stage-caption"><span>${support}脚支撑</span><span>${lifted}脚抬起 ↑</span></div><button class="icon-button white skill-reset-view" type="button" aria-label="重置目标示意视角" onClick=${()=>duck.current?.resetView()} disabled=${!ready}><${Icon} name="refresh" size=${15}/></button></div><figcaption><b>${skillSummary(skill)}</b><span>左右以机器人自身为准。姿态仅帮助理解目标，不表示物理平衡或精确抬脚高度。</span></figcaption></figure>`;
}

export function SkillFields({recipe,skill,onChange}) {
  const limits=recipe.skill_limits,height=limits.lift_height_m,hold=limits.hold_seconds;
  return html`<div class="skill-form"><div class="skill-experimental"><${Badge} tone="amber">实验性 · 尚未实机验证<//></div><fieldset class="skill-support"><legend class="field-label">支撑脚</legend><div class="skill-side-options">${limits.support_side.map(side=>html`<label class=${'skill-side '+(skill.support_side===side?'chosen':'')}><input type="radio" name="support_side" value=${side} checked=${skill.support_side===side} onChange=${()=>onChange({...skill,support_side:side})}/><b>${side==='left'?'左脚':'右脚'}支撑</b><small>抬起${side==='left'?'右':'左'}脚</small></label>`)}</div><p class="field-help">左、右以机器人自身为准，与屏幕上的左右无关。</p></fieldset><div class="skill-number-fields"><label class="advanced-field"><span>另一只脚抬高 <span class="muted">cm</span></span><input type="number" name="lift_height_cm" inputmode="decimal" value=${metersToCm(skill.lift_height_m)} min=${metersToCm(height.min)} max=${metersToCm(height.max)} step=${metersToCm(height.step)} required onInput=${e=>onChange({...skill,lift_height_m:cmToMeters(e.target.value)})}/><small>${formatNumber(metersToCm(height.min),2)}–${formatNumber(metersToCm(height.max),2)} cm，建议先从 ${formatNumber(metersToCm(recipe.skill_defaults.lift_height_m),2)} cm 开始。</small></label><label class="advanced-field"><span>目标保持时间 <span class="muted">秒</span></span><input type="number" name="hold_seconds" inputmode="numeric" value=${skill.hold_seconds} min=${hold.min} max=${hold.max} step=${hold.step} required onInput=${e=>onChange({...skill,hold_seconds:e.target.value})}/><small>${hold.min}–${hold.max} 秒，达到目标高度后保持。</small></label></div><${SkillTargetPreview} skill=${skill}/><div class="skill-phases"><span>站稳</span><i>→</i><span>抬脚</span><i>→</i><span>保持</span><i>→</i><span>落脚</span><i>→</i><span>双脚站稳</span></div><p class="field-help">训练会练习完整动作。修改动作目标后，需要用新目标重新短试跑。</p><button class="text-button" type="button" onClick=${()=>onChange({...recipe.skill_defaults})}>恢复动作推荐值</button></div>`;
}

export function SkillSummary({skill}) {
  if(!skill)return null;
  return html`<div class="skill-saved-goal"><span class="field-label">本次动作目标</span><p>${skillSummary(skill)}</p><small>目标已随实验保存。调整目标可新建一次训练。</small></div>`;
}

export function EvaluationSummary({checkpoint,demo=false}) {
  const result=checkpoint?.evaluation_summary;
  if(!result)return null;
  demo=demo||result.demo===true;
  const stats=evaluationStats(result,demo),trials=Array.isArray(result.trial_results)?result.trial_results:[];
  const reasons={cycle_incomplete:'动作提前结束',non_finite_state:'状态异常',physics_termination:'摔倒或触发失败条件',sample_gap:'评估记录不完整',hold_incomplete:'保持时间不足',return_incomplete:'落脚后未站稳'};
  return html`<div class=${'evaluation-summary '+(demo?'is-demo':'')}><div><b>${demo?'DEMO · 演示评估记录':'单脚平衡评估'}</b><${Badge} tone=${demo?'amber':'neutral'}>${demo?'不作为物理验证':'检查点 '+checkpoint.iteration}<//></div><p>${demo?'当前为演示模式，没有实际物理评估成功率。':stats?html`<strong>${stats.successes} / ${stats.trials}</strong> 次完成完整动作 · 成功率 ${formatNumber(stats.success_rate*100,1)}%`:'本次评估未提供有效的成功次数'}</p>${result.skill&&html`<p class="small-copy muted">${skillSummary(result.skill)}</p>`}<small>${demo?'演示数据仅用于体验界面，不表示策略已学会或物理平衡已通过。':'成功需要完成保持与落脚恢复。这是仿真评估，尚未实机验证；请结合所选检查点的视频判断。'}</small>${!demo&&trials.length>0&&html`<details class="evaluation-trials"><summary>查看每次尝试 · ${trials.length} 次<${Icon} name="down" size=${14}/></summary><ol>${trials.map((trial,index)=>html`<li><div><b>第 ${trial.trial??index+1} 次</b><${Badge} tone=${trial.success===true?'green':'amber'}>${trial.success===true?'完成':'未完成'}<//></div><p>保持 ${formatNumber(trial.hold_achieved_s,1)} / ${formatNumber(result.skill?.hold_seconds,1)} 秒 · 落脚后站稳 ${formatNumber(trial.return_achieved_s,1)} 秒</p>${trial.success!==true&&html`<small>${Array.isArray(trial.failure_reasons)&&trial.failure_reasons.length?trial.failure_reasons.map(code=>reasons[code]||'未达到本次评估条件').join('；'):'本次未达到完整动作要求'}</small>`}</li>`)}</ol></details>`}</div>`;
}
