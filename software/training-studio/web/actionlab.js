import {html,useState,useEffect,useRef} from '/shared/vendor/preact-htm.module.js';
import {Icon,Badge,Empty,DuckStage} from './ui.js';
import {SkillTargetPreview} from './skillform.js';
import {PretrainedCatalog} from './pretrained.js';
import {recipeCatalog,recipeCategories,filterRecipes,recipeTitle,recipeTeachers,skillSummary} from './state.js';

function RecipeFacts({recipe}) {
  const catalog=recipeCatalog(recipe);
  return html`<dl class="recipe-facts"><div><dt>硬件</dt><dd>${catalog.hardware||'训练环境信息未提供'}</dd></div><div><dt>地形</dt><dd>${catalog.terrain_label||'未提供'}</dd></div><div><dt>齿隙模型</dt><dd>${catalog.backlash===null?'未提供':catalog.backlash?'启用':'未启用'}</dd></div>${catalog.requires_rollers&&html`<div class="recipe-roller-requirement"><dt>脚部要求</dt><dd>需要轮滑脚部</dd></div>`}</dl>`;
}

function RecipeCard({recipe,onPreview,onNew}) {
  const catalog=recipeCatalog(recipe),balance=catalog.preview_kind==='balance_target',blocked=recipe.launchable===false;
  const icon=balance?'balance':catalog.preview_kind==='robot_model'?'flask':'chart';
  return html`<article class="panel catalog-card" data-recipe-id=${recipe.id}><div class=${'catalog-cover '+(balance?'balance':catalog.preview_kind==='text'?'terrain':'walk')}><span class="catalog-cover-category">${catalog.category}</span><${Icon} name=${icon} size=${44}/><span class="catalog-cover-caption">${balance?'可设置单脚目标':catalog.preview_kind==='robot_model'?'三维模型说明':'动作文字说明'}<${Icon} name="arrow" size=${14}/></span></div><div class="catalog-card-body"><div class="catalog-card-source"><span>${catalog.source_label}${catalog.author&&html` · ${catalog.author}`}</span><${Badge} tone=${catalog.verification_state==='pipeline'?'blue':'neutral'}>${catalog.verification_label}<//></div><h2>${recipeTitle(recipe)}</h2><p class="catalog-description">${recipe.description||'使用当前训练服务提供的配方，创建一次仿真实验。'}</p>${catalog.requires_rollers&&html`<div class="catalog-requirement"><${Badge} tone="amber">需要轮滑脚部<//></div>`}<${RecipeFacts} recipe=${recipe}/>${catalog.tags.length>0&&html`<div class="catalog-tags">${catalog.tags.map(tag=>html`<span>${tag}</span>`)}</div>`}${balance&&html`<p class="catalog-goal">${skillSummary(recipe.skill_defaults)}</p>`}${blocked&&html`<p class="catalog-prerequisite">需先完成老师训练 · 查看兼容性前置条件</p>`}<p class="catalog-verification">${catalog.verification_state==='pipeline'?'短试跑验证训练链路，不代表已学会动作。':'训练前请先确认环境，动作效果需要实际评估。'}</p>${balance&&html`<span class="catalog-experimental">实验性 · 尚未实机验证</span>`}<div class="catalog-card-actions"><button class="btn" type="button" onClick=${()=>onPreview(recipe.id)} aria-label=${`预览与说明：${recipeTitle(recipe)}`}>预览与说明</button><button class="btn primary" type="button" onClick=${()=>blocked?onPreview(recipe.id):onNew({recipe_id:recipe.id})} aria-label=${`${blocked?'查看前置条件':'开始训练'}：${recipeTitle(recipe)}`}>${blocked?'查看前置条件':'开始训练'}<${Icon} name="arrow" size=${14}/></button></div></div></article>`;
}

function RecipePreview({recipe,recipes,onClose,onNew}) {
  const dialog=useRef(null),catalog=recipeCatalog(recipe),balance=catalog.preview_kind==='balance_target',blocked=recipe.launchable===false,teachers=recipeTeachers(recipe,recipes);
  useEffect(()=>{
    const previous=document.activeElement,overflow=document.body.style.overflow;
    document.body.style.overflow='hidden';dialog.current?.focus();
    const key=e=>{
      if(e.key==='Escape'){e.preventDefault();onClose();}
      if(e.key==='Tab'){
        const nodes=[...dialog.current.querySelectorAll('button,a[href],input,select,[tabindex]')].filter(n=>!n.disabled&&n.offsetParent!==null&&n.tabIndex>=0),first=nodes[0],last=nodes.at(-1);
        if(e.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){e.preventDefault();last?.focus();}
        else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
      }
    };
    document.addEventListener('keydown',key);
    return()=>{document.removeEventListener('keydown',key);document.body.style.overflow=overflow;if(previous?.isConnected)previous.focus();};
  },[]);
  return html`<div class="drawer-backdrop" onClick=${e=>{if(e.target===e.currentTarget)onClose();}}><section class="new-drawer recipe-preview-drawer" ref=${dialog} role="dialog" aria-modal="true" aria-labelledby="recipe-preview-title" tabindex="-1">
    <header class="drawer-header"><div><span class="recipe-preview-eyebrow">${catalog.source_label} · ${catalog.category}</span><h2 id="recipe-preview-title">${recipeTitle(recipe)}</h2><p>先了解动作目标，再设置你的训练。</p></div><button class="icon-button" type="button" aria-label="关闭配方预览" onClick=${onClose}><${Icon} name="close"/></button></header>
    <div class="drawer-content"><div class="recipe-preview-evidence"><${Badge} tone=${catalog.verification_state==='pipeline'?'blue':'neutral'}>${catalog.verification_label}<//>${balance&&html`<${Badge} tone="amber">实验性 · 尚未实机验证<//>`}${catalog.requires_rollers&&html`<${Badge} tone="amber">需要轮滑脚部<//>`}${blocked&&html`<${Badge} tone="amber">需要老师检查点<//>`}</div>
      ${blocked&&html`<section class="recipe-prerequisites" aria-labelledby="recipe-prerequisite-title"><h3 id="recipe-prerequisite-title">先完成前置训练</h3><p>${recipe.prerequisite_note||'此联合配方需要兼容的行走与站立 PT 老师检查点及联合训练适配，当前不能直接创建训练。'}</p>${teachers.length>0&&html`<div class="recipe-teacher-actions">${teachers.map(teacher=>html`<button class="btn" type="button" onClick=${()=>{onClose();onNew({recipe_id:teacher.id});}}>选择${recipeTitle(teacher)}<${Icon} name="arrow" size=${14}/></button>`)}</div>`}</section>`}
      ${balance?html`<${SkillTargetPreview} skill=${recipe.skill_defaults}/>`:catalog.preview_kind==='robot_model'?html`<div class="recipe-model-preview"><${DuckStage} demo=${false} allowDemoMotion=${false}/><p>模型预览 · 非训练结果。可拖动旋转查看机器人外观。</p></div>`:html`<div class="recipe-text-preview"><${Icon} name="chart" size=${36}/><b>动作文字预览</b><p>${recipe.description||'这项配方的训练目标详见下方说明。'}</p><small>任务说明 · 非训练结果</small></div>`}
      <section class="recipe-detail-section"><h3>动作说明</h3>${catalog.preview_kind!=='text'&&html`<p>${recipe.description||'按配方目标进行仿真练习。'}</p>`}<ol class="recipe-instructions">${catalog.instructions.map(text=>html`<li>${text}</li>`)}</ol></section>
      <section class="recipe-detail-section"><h3>适用环境</h3><${RecipeFacts} recipe=${recipe}/></section>
      <section class="recipe-detail-section"><h3>配方来源</h3><p>${catalog.source_url?html`<a href=${catalog.source_url} target="_blank" rel="noopener noreferrer">${catalog.source_label} ↗</a>`:catalog.source_label}${catalog.author&&html` · 作者：${catalog.author}`}</p>${catalog.official_source_url&&html`<p><a href=${catalog.official_source_url} target="_blank" rel="noopener noreferrer">官方任务来源 ↗</a></p>`}${catalog.source_revision&&html`<p class="recipe-task-id muted">参考目录版本：${catalog.source_revision}</p>`}${catalog.upstream_task_id&&html`<p class="recipe-task-id">参考任务：${catalog.upstream_task_id}</p><p class="muted">这是本项目适配基线，动作效果需通过训练与评估验证。</p>`}</section>
      ${catalog.budget_note&&html`<section class="recipe-detail-section"><h3>训练预算</h3><p>${catalog.budget_note}</p></section>`}<section class="recipe-detail-section"><h3>验证记录</h3><p>${recipe.validation||'当前服务尚未提供这项配方的验证记录。'}</p><p class="muted">预览用于理解动作。短试跑只验证训练链路，实际效果请查看训练后保存的检查点评估回放。</p></section>
    </div><footer class="drawer-footer"><div><b>${blocked?'先准备兼容的老师检查点':'把这个目标交给小鸭子'}</b><small>${blocked?'完成前置条件后才能训练联合配方。':'下一步设置参数，再开始短试跑。'}</small></div><button class="btn primary" type="button" disabled=${blocked} onClick=${()=>{if(!blocked){onClose();onNew({recipe_id:recipe.id});}}}>${blocked?'需要前置训练':'使用此配方'}${!blocked&&html`<${Icon} name="arrow" size=${16}/>`}</button></footer>
  </section></div>`;
}

function RecipeCatalog({state,onNew}) {
  const [query,setQuery]=useState(''),[category,setCategory]=useState('全部'),[previewId,setPreviewId]=useState(null);
  const recipes=state.recipes||[],categories=recipeCategories(recipes),activeCategory=categories.includes(category)?category:'全部';
  const filtered=filterRecipes(recipes,{query,category:activeCategory}),preview=recipes.find(recipe=>recipe.id===previewId);
  return html`<div class="recipe-catalog"><section class="panel catalog-intro"><div><span class="eyebrow">从想法到一次练习</span><h2>配方已经写好，从选择开始。</h2><p>作者把动作目标和训练规则写进配方；你选择配方、修改参数，再通过短试跑、训练与评估观察结果。</p></div><ol><li><b>1</b><span>看预览，选配方</span></li><li><b>2</b><span>改参数，做短试跑</span></li><li><b>3</b><span>正式训练，看评估</span></li></ol></section><div class="catalog-toolbar"><div class="catalog-filters" role="group" aria-label="按动作类别筛选">${categories.map(item=>html`<button type="button" class=${activeCategory===item?'active':''} aria-pressed=${activeCategory===item} onClick=${()=>setCategory(item)}>${item}</button>`)}</div><label class="catalog-search"><span>搜索配方</span><input type="search" placeholder="搜索名称、用途、任务或标签" value=${query} onInput=${e=>setQuery(e.target.value)}/></label></div><div class="catalog-results" aria-live="polite">显示 ${filtered.length} / ${recipes.length} 个配方<span>所有预览均非训练结果</span></div>${filtered.length?html`<div class="catalog-grid">${filtered.map(recipe=>html`<${RecipeCard} key=${recipe.id} recipe=${recipe} onPreview=${setPreviewId} onNew=${onNew}/>` )}</div>`:html`<section class="panel"><${Empty} icon="flask" title=${recipes.length?'没有找到匹配的配方':'当前服务还没有提供动作配方'} action=${recipes.length?html`<button class="btn" type="button" onClick=${()=>{setQuery('');setCategory('全部');}}>清除筛选</button>`:null}>${recipes.length?'试试其他关键词，或切换到全部类别。':'连接提供训练配方的服务后，这里会显示可以使用的内容。'}<//></section>`}<p class="catalog-footnote">配方保留原始出处与硬件要求；参考适配基线的训练效果需分别评估。社区配方分享暂未开放。</p>${preview&&html`<${RecipePreview} key=${preview.id} recipe=${preview} recipes=${recipes} onClose=${()=>setPreviewId(null)} onNew=${onNew}/>`}</div>`;
}

export function ActionLab({state,onNew}) {
  const [tab,setTab]=useState('recipes'),models=state.pretrained_models||[];
  return html`<div class="page-enter action-catalog"><div class="page-heading"><div><h1>动作实验室</h1><p>选择练习配方，或了解官方与社区已经发布的动作策略。</p></div><${Badge}>${state.recipes?.length||0} 个配方 · ${models.length} 个模型<//></div><div class="segmented catalog-tabs" role="group" aria-label="动作内容类型"><button type="button" class=${tab==='recipes'?'active':''} aria-pressed=${tab==='recipes'} onClick=${()=>setTab('recipes')}>训练配方 <span>${state.recipes?.length||0}</span></button><button type="button" class=${tab==='models'?'active':''} aria-pressed=${tab==='models'} onClick=${()=>setTab('models')}>预训练模型 <span>${models.length}</span></button></div>${tab==='recipes'?html`<${RecipeCatalog} state=${state} onNew=${onNew}/>`:html`<${PretrainedCatalog} models=${models}/>`}</div>`;
}
