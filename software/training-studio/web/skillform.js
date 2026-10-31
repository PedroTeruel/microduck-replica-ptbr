import {html,useState,useEffect,useRef} from '/shared/vendor/preact-htm.module.js';
import {Icon,Badge} from './ui.js';
import {metersToCm,cmToMeters,formatNumber,skillSummary,evaluationStats,recipeTitle} from './state.js';

export function ActionLabEntry({recipes=[],onBrowse}) {
  const examples=recipes.slice(0,3).map(recipe=>recipeTitle(recipe)).join(' · ');
  return html`<section class="panel action-lab" aria-labelledby="action-lab-title"><div class="action-lab-heading"><div><span class="eyebrow">A próxima habilidade do patinho</span><h2 id="action-lab-title">Laboratório de ações</h2><p>Navegue pelas receitas disponíveis e escolha o movimento que deseja praticar.</p></div><div class="action-lab-badges"><${Badge}>Sem programação<//><${Badge}>${recipes.length} receitas disponíveis<//></div></div><div class="action-lab-body"><div class="action-lab-goal"><span class="action-glyph"><${Icon} name="balance" size=${34}/></span><div><h3>Comece com uma meta de prática</h3><p>${examples||'Veja as receitas oferecidas pelo serviço de treinamento atual'}</p><span class="muted small-copy">Confira a prévia da meta e as instruções da ação antes de configurar seu experimento.</span></div></div><button class="btn primary" onClick=${onBrowse}>Explorar receitas de ação<${Icon} name="arrow" size=${16}/></button></div><ol class="action-lab-steps"><li><b>1</b><span>Explore as receitas e entenda a meta</span></li><li><b>2</b><span>Configure os parâmetros, faça um teste curto e treine</span></li><li><b>3</b><span>Avalie o checkpoint e observe o resultado real</span></li></ol><p class="action-lab-note">A prévia ajuda a entender a ação; para saber se foi aprendida, confira a avaliação do checkpoint após o treinamento.</p></section>`;
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
  const support=skill.support_side==='right'?'direito':'esquerdo',lifted=support==='esquerdo'?'direito':'esquerdo';
  return html`<figure class="skill-preview"><div class="duck-stage skill-stage"><canvas ref=${canvas} aria-label=${`Ilustração da meta de equilíbrio em um pé: o robô apoia o pé ${support} e levanta o pé ${lifted}. Arraste para girar a vista.`}/><span class="stage-label">Ilustração da meta · não é resultado do treinamento</span>${!ready&&!error&&html`<div class="stage-loading"><span class="spinner"/>Carregando ilustração da meta…</div>`}${error&&html`<div class="stage-loading">Ilustração 3D indisponível<small>O texto abaixo ainda descreve a meta completa.</small></div>`}<div class="skill-stage-caption"><span>Apoio no pé ${support}</span><span>Pé ${lifted} elevado ↑</span></div><button class="icon-button white skill-reset-view" type="button" aria-label="Redefinir ângulo da ilustração" onClick=${()=>duck.current?.resetView()} disabled=${!ready}><${Icon} name="refresh" size=${15}/></button></div><figcaption><b>${skillSummary(skill)}</b><span>Esquerda e direita são relativas ao robô. A pose ajuda a entender a meta; não representa equilíbrio físico nem a altura exata de elevação do pé.</span></figcaption></figure>`;
}

export function SkillFields({recipe,skill,onChange}) {
  const limits=recipe.skill_limits,height=limits.lift_height_m,hold=limits.hold_seconds;
  return html`<div class="skill-form"><div class="skill-experimental"><${Badge} tone="amber">Experimental · ainda não validado em hardware<//></div><fieldset class="skill-support"><legend class="field-label">Pé de apoio</legend><div class="skill-side-options">${limits.support_side.map(side=>html`<label class=${'skill-side '+(skill.support_side===side?'chosen':'')}><input type="radio" name="support_side" value=${side} checked=${skill.support_side===side} onChange=${()=>onChange({...skill,support_side:side})}/><b>Apoio no pé ${side==='left'?'esquerdo':'direito'}</b><small>Elevar o pé ${side==='left'?'direito':'esquerdo'}</small></label>`)}</div><p class="field-help">Esquerda e direita são relativas ao robô, não à tela.</p></fieldset><div class="skill-number-fields"><label class="advanced-field"><span>Elevação do outro pé <span class="muted">cm</span></span><input type="number" name="lift_height_cm" inputmode="decimal" value=${metersToCm(skill.lift_height_m)} min=${metersToCm(height.min)} max=${metersToCm(height.max)} step=${metersToCm(height.step)} required onInput=${e=>onChange({...skill,lift_height_m:cmToMeters(e.target.value)})}/><small>${formatNumber(metersToCm(height.min),2)}–${formatNumber(metersToCm(height.max),2)} cm; recomenda-se começar com ${formatNumber(metersToCm(recipe.skill_defaults.lift_height_m),2)} cm.</small></label><label class="advanced-field"><span>Tempo de sustentação da meta <span class="muted">s</span></span><input type="number" name="hold_seconds" inputmode="numeric" value=${skill.hold_seconds} min=${hold.min} max=${hold.max} step=${hold.step} required onInput=${e=>onChange({...skill,hold_seconds:e.target.value})}/><small>${hold.min}–${hold.max} s; mantenha a pose depois de alcançar a altura desejada.</small></label></div><${SkillTargetPreview} skill=${skill}/><div class="skill-phases"><span>Estabilizar</span><i>→</i><span>Elevar o pé</span><i>→</i><span>Sustentar</span><i>→</i><span>Apoiar o pé</span><i>→</i><span>Estabilizar nos dois pés</span></div><p class="field-help">O treinamento pratica o movimento completo. Depois de alterar a meta, faça um novo teste curto com os parâmetros atualizados.</p><button class="text-button" type="button" onClick=${()=>onChange({...recipe.skill_defaults})}>Restaurar valores recomendados</button></div>`;
}

export function SkillSummary({skill}) {
  if(!skill)return null;
  return html`<div class="skill-saved-goal"><span class="field-label">Meta desta ação</span><p>${skillSummary(skill)}</p><small>A meta foi salva com o experimento. Ajuste-a ao criar outro treinamento.</small></div>`;
}

export function EvaluationSummary({checkpoint,demo=false}) {
  const result=checkpoint?.evaluation_summary;
  if(!result)return null;
  demo=demo||result.demo===true;
  const stats=evaluationStats(result,demo),trials=Array.isArray(result.trial_results)?result.trial_results:[];
  const reasons={cycle_incomplete:'Ação terminou antes do fim',non_finite_state:'Estado anormal',physics_termination:'Queda ou condição de falha acionada',sample_gap:'Registro da avaliação incompleto',hold_incomplete:'Tempo de sustentação insuficiente',return_incomplete:'Não estabilizou após apoiar o pé'};
  return html`<div class=${'evaluation-summary '+(demo?'is-demo':'')}><div><b>${demo?'DEMO · registro de avaliação ilustrativo':'Avaliação de equilíbrio em um pé'}</b><${Badge} tone=${demo?'amber':'neutral'}>${demo?'Não é uma validação física':'Checkpoint '+checkpoint.iteration}<//></div><p>${demo?'Este modo de demonstração não apresenta uma taxa real de sucesso de avaliação física.':stats?html`<strong>${stats.successes} / ${stats.trials}</strong> ações completas · taxa de sucesso ${formatNumber(stats.success_rate*100,1)}%`:'Esta avaliação não forneceu uma contagem de sucesso válida'}</p>${result.skill&&html`<p class="small-copy muted">${skillSummary(result.skill)}</p>`}<small>${demo?'Os dados de demonstração servem somente para experimentar a interface; não indicam que a política aprendeu ou passou no teste de equilíbrio físico.':'Para ter sucesso, é preciso concluir a sustentação e voltar a ficar estável após apoiar o pé. Esta avaliação é simulada e ainda não foi validada em hardware; confira o vídeo do checkpoint selecionado.'}</small>${!demo&&trials.length>0&&html`<details class="evaluation-trials"><summary>Ver cada tentativa · ${trials.length}<${Icon} name="down" size=${14}/></summary><ol>${trials.map((trial,index)=>html`<li><div><b>Tentativa ${trial.trial??index+1}</b><${Badge} tone=${trial.success===true?'green':'amber'}>${trial.success===true?'Concluída':'Incompleta'}<//></div><p>Sustentação ${formatNumber(trial.hold_achieved_s,1)} / ${formatNumber(result.skill?.hold_seconds,1)} s · estabilidade após apoiar o pé: ${formatNumber(trial.return_achieved_s,1)} s</p>${trial.success!==true&&html`<small>${Array.isArray(trial.failure_reasons)&&trial.failure_reasons.length?trial.failure_reasons.map(code=>reasons[code]||'Não atingiu os critérios desta avaliação').join('; '):'O movimento completo não foi concluído nesta tentativa'}</small>`}</li>`)}</ol></details>`}</div>`;
}
