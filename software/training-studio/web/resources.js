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
      } catch(e) { if(live)setError(e.name==='AbortError'?'A solicitação de leitura de recursos expirou':e.message); }
      finally {clearTimeout(timeout);if(live){setClock(performance.now());timer=setTimeout(poll,3000);}}
    };
    const refreshAge=()=>{if(live&&!document.hidden)setClock(performance.now());};
    window.addEventListener('focus',refreshAge);document.addEventListener('visibilitychange',refreshAge);
    poll();return()=>{live=false;clearTimeout(timer);controller?.abort();window.removeEventListener('focus',refreshAge);document.removeEventListener('visibilitychange',refreshAge);};
  },[]);
  const sample=reading?.sample,secondsSinceReceipt=reading?Math.max(0,(performance.now()-reading.receivedAt)/1000):0;
  const status=resourceStatus(sample,error,secondsSinceReceipt),cpu=sample?.cpu||{},memory=sample?.memory||{},gpus=sample?.gpus||[];
  const active=['starting','running','paused','stopping'].includes(run.status),latest=run.metrics?.at(-1)||{};
  return html`<section class=${'panel resource-panel '+(status.stale?'is-stale':'')} aria-labelledby="resource-title"><div class="panel-head"><div><h2 id="resource-title">Recursos computacionais</h2><p class="muted small-copy">Recursos gerais atuais do ambiente de execução${sample?.is_wsl?' · WSL CPU e memória visíveis':''}</p></div><${Badge} tone=${status.tone}>${status.label}<//></div><div class="resource-grid">${gpus.length?gpus.map(gpu=>html`<section class="resource-device" key=${gpu.index}><div class="resource-device-heading"><${Icon} name="chip" size=${20}/><div><span>GPU ${gpu.index}</span><h3>${gpu.name||'Modelo indisponível no momento'}</h3></div></div><dl class="resource-readings"><${Reading} label="Uso da GPU" value=${resourceNumber(gpu.utilization_pct,0,'%')} reason=${gpu.utilization_pct==null?gpu.unavailable_reasons?.utilization_pct||'Indisponível no momento':null}/><${Reading} label="Temperatura da GPU" value=${resourceNumber(gpu.temperature_c,0,' °C')} reason=${gpu.temperature_c==null?gpu.unavailable_reasons?.temperature_c||'Indisponível no momento':null}/><${Reading} label="Memória de vídeo usada / total" value=${resourceMemory(gpu.memory_used_mib,gpu.memory_total_mib,'mib')} reason=${gpu.memory_used_mib==null?gpu.unavailable_reasons?.memory_used_mib||'Indisponível no momento':null}/></dl><${Meter} used=${gpu.memory_used_mib} total=${gpu.memory_total_mib} label=${`GPU ${gpu.index} Proporção de memória de vídeo usada`}/></section>`):html`<section class="resource-device"><div class="resource-device-heading"><${Icon} name="chip" size=${20}/><div><span>GPU</span><h3>${sample?.status==='pending'||!sample?'Aguardando leitura do dispositivo':'Indisponível no momento'}</h3></div></div><p class="resource-reason">${sample?.gpu_reason||'Lendo modelo, uso, temperatura e memória de vídeo da GPU no ambiente de execução.'}</p></section>`}<section class="resource-device"><div class="resource-device-heading"><${Icon} name="chip" size=${20}/><div><span>CPU${cpu.count?` · ${cpu.count}  núcleos lógicos`:''}</span><h3>${cpu.model||'Modelo indisponível no momento'}</h3></div></div><dl class="resource-readings"><${Reading} label="Uso da CPU" value=${resourceNumber(cpu.utilization_pct,0,'%')} reason=${cpu.utilization_pct==null?cpu.utilization_reason||'Indisponível no momento':null}/><${Reading} label="Temperatura da CPU" value=${resourceNumber(cpu.temperature_c,0,' °C')} reason=${cpu.temperature_c==null?cpu.temperature_reason||'Indisponível no momento':null}/><${Reading} label="Memória usada / total" value=${resourceMemory(memory.used_bytes,memory.total_bytes)} reason=${memory.used_bytes==null?memory.reason||'Indisponível no momento':null}/></dl><${Meter} used=${memory.used_bytes} total=${memory.total_bytes} label="Proporção de memória usada"/></section></div><div class="resource-footer"><div class="resource-run-stats"><span>Rodada deste experimento <b>${resourceNumber(run.progress?.iteration??0,0)} / ${resourceNumber(run.progress?.total??run.config?.iterations,0)}</b></span><span>${active?'Velocidade de amostragem mais recente':'Última velocidade de amostragem antes do fim'} <b>${resourceNumber(latest.fps,0,'  etapas/s')}</b></span><span>Ambientes paralelos <b>${resourceNumber(run.config?.num_envs,0)}</b></span></div><p>${sample?.scope_note||'Este é o uso total atual do ambiente de execução, incluindo outros processos.'}${!active?' Este experimento terminou; estas leituras em tempo real não representam o uso durante sua execução.':''}${run.mode==='demo'?' As métricas deste experimento são dados de demonstração; os recursos são medidos no ambiente de execução real.':''}</p><div class="resource-sample-time"><span>${sample?.sampled_at?`Leitura mais recente ${dateText(sample.sampled_at)}`:'Aguardando a primeira leitura'} · Atualizado a cada 3 s, aproximadamente</span>${error&&html`<span role="status">${error}</span>`}</div>${sample?.errors?.length>0&&html`<details class="resource-errors"><summary>Detalhes da leitura · ${sample.errors.length} itens</summary><ul>${sample.errors.map(item=>html`<li>${item.component}：${item.reason}</li>`)}</ul></details>`}</div></section>`;
}
