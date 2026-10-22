import {html,useState,useEffect} from '/shared/vendor/preact-htm.module.js';
import {Badge,Icon} from './ui.js';
import {request} from './client.js';
import {resourceNumber,resourceMemory,resourceStatus,dateText} from './state.js';

function Reading({label,value,reason}) {
  return html`<div class="resource-reading"><dt>${label}</dt><dd>${value}</dd>${reason&&html`<small>${reason}</small>`}</div>`;
}
function Meter({used,total,label}) {
  if(typeof used!=='number'||typeof total!=='number'||!Number.isFinite(used)||!Number.isFinite(total)||used<0||total<=0)return null;
  const percent=Math.max(0,Math.min(100,used/total*100));
  return html`<div class="resource-meter" role="meter" aria-label=${label} aria-valuemin="0" aria-valuemax="100" aria-valuenow=${Math.round(percent)}><span style=${`width:${percent}%`}/></div>`;
}
export function ResourcePanel({run}) {
  const [reading,setReading]=useState(null),[error,setError]=useState(''),[,setClock]=useState(0);
  useEffect(()=>{
    let live=true,timer,controller;
    const poll=async()=>{
      controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),5000);
      try {
        const value=await request('/api/resources',{signal:controller.signal});
        if(live){setReading({sample:value,receivedAt:performance.now()});setError('');}
      } catch(e) { if(live)setError(e.name==='AbortError'?'资源采样请求超时':e.message); }
      finally {clearTimeout(timeout);if(live){setClock(performance.now());timer=setTimeout(poll,3000);}}
    };
    const refreshAge=()=>{if(live&&!document.hidden)setClock(performance.now());};
    window.addEventListener('focus',refreshAge);document.addEventListener('visibilitychange',refreshAge);
    poll();return()=>{live=false;clearTimeout(timer);controller?.abort();window.removeEventListener('focus',refreshAge);document.removeEventListener('visibilitychange',refreshAge);};
  },[]);
  const sample=reading?.sample,secondsSinceReceipt=reading?Math.max(0,(performance.now()-reading.receivedAt)/1000):0;
  const status=resourceStatus(sample,error,secondsSinceReceipt),cpu=sample?.cpu||{},memory=sample?.memory||{},gpus=sample?.gpus||[];
  const active=['starting','running','paused','stopping'].includes(run.status),latest=run.metrics?.at(-1)||{};
  return html`<section class=${'panel resource-panel '+(status.stale?'is-stale':'')} aria-labelledby="resource-title"><div class="panel-head"><div><h2 id="resource-title">计算资源</h2><p class="muted small-copy">执行端当前整体资源${sample?.is_wsl?' · WSL 可见 CPU 与内存':''}</p></div><${Badge} tone=${status.tone}>${status.label}<//></div><div class="resource-grid">${gpus.length?gpus.map(gpu=>html`<section class="resource-device" key=${gpu.index}><div class="resource-device-heading"><${Icon} name="chip" size=${20}/><div><span>GPU ${gpu.index}</span><h3>${gpu.name||'型号暂不可读取'}</h3></div></div><dl class="resource-readings"><${Reading} label="GPU 利用率" value=${resourceNumber(gpu.utilization_pct,0,'%')} reason=${gpu.utilization_pct==null?gpu.unavailable_reasons?.utilization_pct||'暂不可读取':null}/><${Reading} label="GPU 温度" value=${resourceNumber(gpu.temperature_c,0,' °C')} reason=${gpu.temperature_c==null?gpu.unavailable_reasons?.temperature_c||'暂不可读取':null}/><${Reading} label="显存占用 / 总量" value=${resourceMemory(gpu.memory_used_mib,gpu.memory_total_mib,'mib')} reason=${gpu.memory_used_mib==null?gpu.unavailable_reasons?.memory_used_mib||'暂不可读取':null}/></dl><${Meter} used=${gpu.memory_used_mib} total=${gpu.memory_total_mib} label=${`GPU ${gpu.index} 显存占用比例`}/></section>`):html`<section class="resource-device"><div class="resource-device-heading"><${Icon} name="chip" size=${20}/><div><span>GPU</span><h3>${sample?.status==='pending'||!sample?'等待设备采样':'暂不可读取'}</h3></div></div><p class="resource-reason">${sample?.gpu_reason||'正在读取执行端 GPU 型号、利用率、温度与显存。'}</p></section>`}<section class="resource-device"><div class="resource-device-heading"><${Icon} name="chip" size=${20}/><div><span>CPU${cpu.count?` · ${cpu.count} 个逻辑核心`:''}</span><h3>${cpu.model||'型号暂不可读取'}</h3></div></div><dl class="resource-readings"><${Reading} label="CPU 利用率" value=${resourceNumber(cpu.utilization_pct,0,'%')} reason=${cpu.utilization_pct==null?cpu.utilization_reason||'暂不可读取':null}/><${Reading} label="CPU 温度" value=${resourceNumber(cpu.temperature_c,0,' °C')} reason=${cpu.temperature_c==null?cpu.temperature_reason||'暂不可读取':null}/><${Reading} label="内存占用 / 总量" value=${resourceMemory(memory.used_bytes,memory.total_bytes)} reason=${memory.used_bytes==null?memory.reason||'暂不可读取':null}/></dl><${Meter} used=${memory.used_bytes} total=${memory.total_bytes} label="内存占用比例"/></section></div><div class="resource-footer"><div class="resource-run-stats"><span>本实验轮次 <b>${resourceNumber(run.progress?.iteration??0,0)} / ${resourceNumber(run.progress?.total??run.config?.iterations,0)}</b></span><span>${active?'最近记录的采样速度':'结束前最后采样速度'} <b>${resourceNumber(latest.fps,0,' 步/秒')}</b></span><span>并行环境 <b>${resourceNumber(run.config?.num_envs,0)}</b></span></div><p>${sample?.scope_note||'这是执行端当前的整体占用，包含其他进程。'}${!active?' 本实验已结束，这些实时读数不是它运行时的历史占用。':''}${run.mode==='demo'?' 本实验训练指标是演示数据，资源采样来自实际执行端。':''}</p><div class="resource-sample-time"><span>${sample?.sampled_at?`最近采样 ${dateText(sample.sampled_at)}`:'等待首次采样'} · 约每 3 秒更新</span>${error&&html`<span role="status">${error}</span>`}</div>${sample?.errors?.length>0&&html`<details class="resource-errors"><summary>采样说明 · ${sample.errors.length} 项</summary><ul>${sample.errors.map(item=>html`<li>${item.component}：${item.reason}</li>`)}</ul></details>`}</div></section>`;
}
