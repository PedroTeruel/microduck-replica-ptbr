import {html,useState,useEffect,useRef} from '/shared/vendor/preact-htm.module.js';
import {metricPoints,formatNumber,dateText,statusText,recipeTitle,skillSummary} from './state.js';
import {request} from './client.js';

const paths={balance:'M12 3v5 M8 6h8 M6 10h12 M9 10l-3 9 M9 10l6 5 3-4 M3 20h6 M9 3h6',grid:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',flask:'M9 3h6 M10 3v6l-6 10a1.3 1.3 0 0 0 1 2h14a1.3 1.3 0 0 0 1-2L14 9V3 M8 15h8',box:'m12 3 9 5v9l-9 5-9-5V8z M3 8l9 5 9-5 M12 13v9',chip:'M7 7h10v10H7z M9 1v4 M15 1v4 M9 19v4 M15 19v4 M1 9h4 M1 15h4 M19 9h4 M19 15h4',plus:'M12 5v14 M5 12h14',arrow:'M5 12h14 m-6-6 6 6-6 6',play:'m9 5 11 7-11 7z',pause:'M8 5v14 M16 5v14',stop:'M6 6h12v12H6z',check:'m5 12 4 4L19 6',chevron:'m9 5 7 7-7 7',down:'m6 9 6 6 6-6',close:'m6 6 12 12 M18 6 6 18',upload:'M12 16V3 m-5 5 5-5 5 5 M4 15v5h16v-5',download:'M12 3v13 m-5-5 5 5 5-5 M4 17v4h16v-4',refresh:'M20 8V3l-4 4a8 8 0 1 0 3 10 M20 3h-5',clock:'M12 8v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',info:'M12 11v6 M12 7v.1 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',chart:'M4 3v17h17 M7 14l4-5 4 3 5-7',compare:'M8 3v18 M16 3v18 M4 7l4-4 4 4 M12 17l4 4 4-4',file:'M14 2H5v20h14V7z M14 2v6h6 M8 12h8 M8 16h6',settings:'M4 7h16 M4 17h16 M9 4v6 M15 14v6',link:'m10 14 4-4 M8 16l-2 2a3 3 0 0 1-4-4l5-5a3 3 0 0 1 4 0 M16 8l2-2a3 3 0 0 1 4 4l-5 5a3 3 0 0 1-4 0',eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',alert:'m12 3 10 18H2z M12 9v5 M12 17v.1',menu:'M3 6h18 M3 12h18 M3 18h18',help:'M9 8a3 3 0 1 1 5 2c-2 1-2 2-2 3 M12 17v.1 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0'};
export function Icon({name='arrow',size=18,className=''}) {return html`<svg class=${'icon '+className} width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d=${paths[name]||paths.arrow}/></svg>`;}
export function Badge({children,tone='neutral',dot=false}) {return html`<span class=${'badge '+tone}>${dot&&html`<span class="status-dot"/>`}${children}</span>`;}
export function Status({run}) {return html`<${Badge} dot tone=${run?.status==='running'?'green':run?.status==='paused'?'amber':run?.status==='failed'?'red':run?.status==='completed'?'blue':'neutral'}>${statusText(run)}<//>`;}
export function Empty({icon='flask',title,children,action}) {return html`<div class="empty"><span class="empty-icon"><${Icon} name=${icon} size=${26}/></span><h3>${title}</h3><p>${children}</p>${action}</div>`;}
export function Stat({label,value,unit,icon,sub}) {return html`<div class="stat"><span class="stat-label">${icon&&html`<${Icon} name=${icon} size=${15}/>`}${label}</span><div class="stat-value">${value}<small>${unit}</small></div>${sub&&html`<span class="stat-sub">${sub}</span>`}</div>`;}

let chartId=0;
export function Chart({series=[],metric='reward',title='平均奖励',compact=false}) {
  const id=useRef(`gradient-${++chartId}`).current;
  const [hover,setHover]=useState(null),[width,setWidth]=useState(640),box=useRef(null);
  const data=series.map((s,i)=>({...s,color:s.color||['#0071E3','#B25000'][i%2],points:metricPoints(s.metrics,metric)}));
  const all=data.flatMap(s=>s.points),w=width,h=compact?156:208,pad={l:48,r:16,t:18,b:32};
  useEffect(()=>{const el=box.current;if(!el)return;const resize=()=>setWidth(Math.max(240,Math.round(el.getBoundingClientRect().width)));resize();const observer=new ResizeObserver(resize);observer.observe(el);return()=>observer.disconnect();},[all.length>0]);
  if(!all.length)return html`<div class="chart-empty"><${Icon} name="chart" size=${24}/><span>等待训练指标</span><small>收到实际日志后，曲线会出现在这里</small></div>`;
  const xmin=Math.min(...all.map(p=>p.x)),xmax=Math.max(xmin+1,...all.map(p=>p.x));
  let ymin=Math.min(...all.map(p=>p.y)),ymax=Math.max(...all.map(p=>p.y));
  const spread=Math.max((ymax-ymin)*.15,Math.abs(ymax)*.03,0.1);ymin-=spread;ymax+=spread;
  const X=x=>pad.l+(x-xmin)/(xmax-xmin)*(w-pad.l-pad.r),Y=y=>h-pad.b-(y-ymin)/(ymax-ymin)*(h-pad.t-pad.b);
  const nearest=hover===null?null:data.map(s=>({...s,point:s.points.reduce((best,p)=>!best||Math.abs(p.x-hover)<Math.abs(best.x-hover)?p:best,null)}));
  return html`<div class="chart" ref=${box} aria-label=${title}>
    <svg viewBox=${`0 0 ${w} ${h}`} role="img" aria-label=${title} onPointerLeave=${()=>setHover(null)} onPointerMove=${e=>{const b=e.currentTarget.getBoundingClientRect();setHover(xmin+((e.clientX-b.left)/b.width*w-pad.l)/(w-pad.l-pad.r)*(xmax-xmin));}}>
      <defs><linearGradient id=${id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#0071E3" stop-opacity=".18"/><stop offset="100%" stop-color="#0071E3" stop-opacity="0"/></linearGradient></defs>
      ${[0,1,2,3].map(n=>{const y=pad.t+n/3*(h-pad.t-pad.b);return html`<g><line x1=${pad.l} x2=${w-pad.r} y1=${y} y2=${y} stroke="#E5E5EA" stroke-dasharray="3 5"/><text x=${pad.l-10} y=${y+4} text-anchor="end" class="chart-axis">${formatNumber(ymax-n/3*(ymax-ymin),metric==='fps'?0:1)}</text></g>`;})}
      ${[0,.25,.5,.75,1].map(n=>html`<text x=${pad.l+n*(w-pad.l-pad.r)} y=${h-7} text-anchor="middle" class="chart-axis">${formatNumber(xmin+n*(xmax-xmin),0)}</text>`)}
      ${data.map((s,i)=>{const p=s.points.map((p,j)=>`${j?'L':'M'}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join(' ');return html`<g>${i===0&&s.points.length>1&&html`<path d=${`${p} L${X(s.points.at(-1).x)},${h-pad.b} L${X(s.points[0].x)},${h-pad.b} Z`} fill=${`url(#${id})`}/>`}<path d=${p} fill="none" stroke=${s.color} stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>${s.points.length===1&&html`<circle cx=${X(s.points[0].x)} cy=${Y(s.points[0].y)} r="3" fill=${s.color}/>`}</g>`;})}
      ${nearest?.[0]?.point&&html`<line x1=${X(nearest[0].point.x)} x2=${X(nearest[0].point.x)} y1=${pad.t} y2=${h-pad.b} stroke="#6E6E73" stroke-dasharray="3 3"/>`}
    </svg>
    ${nearest&&html`<div class="chart-tooltip">${nearest.filter(s=>s.point).map(s=>html`<span><i style=${`background:${s.color}`}/>${s.name||title} · 第 ${s.point.x} 轮：<b>${formatNumber(s.point.y,2)}</b></span>`)}</div>`}
  </div>`;
}

export function ArtifactMedia({url,alt='检查点评估回放'}) {
  const [src,setSrc]=useState(null),[error,setError]=useState('');
  useEffect(()=>{let active=true,obj;setSrc(null);setError('');request(url,{blob:true}).then(blob=>{if(!active)return;obj=URL.createObjectURL(blob);setSrc(obj);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;if(obj)URL.revokeObjectURL(obj);};},[url]);
  if(error)return html`<div class="media-error"><${Icon} name="alert"/>回放读取失败：${error}</div>`;
  if(!src)return html`<div class="media-loading"><span class="spinner"/>正在读取回放…</div>`;
  return /\.(svg|png|jpg|webp)(?:\?|$)/i.test(url)?html`<img class="artifact-image" src=${src} alt=${alt}/>`:html`<video class="artifact-video" src=${src} controls playsinline preload="metadata" aria-label=${alt}/>`;
}

export function DuckStage({demo=false,checkpoint=null,allowDemoMotion=true}) {
  const canvas=useRef(null),duck=useRef(null),[ready,setReady]=useState(false),[error,setError]=useState(''),[play,setPlay]=useState(false);
  useEffect(()=>{let active=true;import('/shared/duck3d.js').then(async({Duck3D})=>{
    if(!active)return;const d=new Duck3D(canvas.current,{view:'front34',centerX:.5,centerY:.47,fill:.84,pageScroll:true});duck.current=d;
    try{await d.load('/shared/model/');if(!active)return;d.setJoints(new Array(15).fill(0));setReady(true);}catch(e){if(active)setError(e.message);}
  }).catch(e=>{if(active)setError(e.message);});return()=>{active=false;duck.current?.dispose();duck.current=null;};},[]);
  useEffect(()=>{if(!play||!demo||!allowDemoMotion||checkpoint?.video_url){duck.current?.setJoints(new Array(15).fill(0));return;}let raf,last=0;const animate=t=>{if(t-last>45){last=t;const s=Math.sin(t*.004),r=Math.max(0,s),l=Math.max(0,-s);duck.current?.setJoints([0,.01*s,.12*s,.18*l,-.12*s-.18*l,.03*Math.sin(t*.002),0,.04*s,0,0,0,-.01*s,.12*s,-.18*r,-.12*s+.18*r]);}raf=requestAnimationFrame(animate);};raf=requestAnimationFrame(animate);return()=>cancelAnimationFrame(raf);},[play,demo,allowDemoMotion,checkpoint?.video_url]);
  const url=checkpoint?.video_url;
  return html`<div class=${'duck-stage '+(url?'has-video':'')}>
    <canvas ref=${canvas} style=${url?'visibility:hidden':''} aria-label="Microduck CAD 模型，可拖动旋转视角"/>
    ${url&&html`<${ArtifactMedia} url=${url}/>`}
    ${!url&&!ready&&!error&&html`<div class="stage-loading"><span class="spinner"/>正在加载小鸭子…</div>`}
    ${!url&&error&&html`<div class="stage-loading">3D 预览暂不可用<small>${error}</small></div>`}
    <span class="stage-label"><span class="status-dot"/>${url?(demo?'演示回放 · 非模型推理':'检查点评估回放'):(play?'动作示意 · 非模型推理':'CAD 模型预览')}</span>
    ${!url&&html`<div class="stage-tools">${demo&&allowDemoMotion&&html`<button class="btn small white" onClick=${()=>setPlay(v=>!v)} disabled=${!ready}><${Icon} name=${play?'pause':'play'} size=${14}/>${play?'暂停示意':'播放动作示意'}</button>`}<button class="icon-button white" aria-label="重置模型视角" onClick=${()=>duck.current?.resetView()}><${Icon} name="refresh" size=${16}/></button></div>`}
  </div>`;
}

export function RunTable({runs=[],onSelect,selected}) {
  return html`<div class="table-scroll"><table class="run-table"><thead><tr><th>实验名称</th><th>状态</th><th>训练轮数</th><th>检查点</th><th>创建时间</th><th/></tr></thead><tbody>${runs.map(r=>html`<tr class=${r.id===selected?'selected':''} key=${r.id}><td><button class="run-name" onClick=${()=>onSelect(r.id)}><span class="run-table-icon"><${Icon} name=${r.kind==='smoke'?'check':'flask'} size=${17}/></span><span><b>${r.name}</b><small>${r.kind==='smoke'?'环境短试跑':'正式训练'} · ${recipeTitle(r)}${r.mode==='demo'?' · 演示':''}</small>${r.skill&&html`<small>${skillSummary(r.skill)}</small>`}</span></button></td><td><${Status} run=${r}/></td><td class="numeric">${formatNumber(r.progress?.iteration,0)}<span class="muted"> / ${formatNumber(r.progress?.total||r.config?.iterations,0)}</span></td><td class="numeric">${r.checkpoints?.length||0}</td><td class="muted nowrap">${dateText(r.created_at)}</td><td><button class="icon-button" aria-label=${`打开 ${r.name}`} onClick=${()=>onSelect(r.id)}><${Icon} name="chevron" size=${16}/></button></td></tr>`)}</tbody></table></div>`;
}
