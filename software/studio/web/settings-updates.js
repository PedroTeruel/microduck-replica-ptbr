import {html,useEffect,useRef,useState} from './vendor/preact-htm.module.js';
import {updateMessage,updateActions,PHASES} from './updates-ui-state.js';

const CSS=`.update-settings{padding:18px 20px;min-width:0;overflow-wrap:anywhere}.update-settings h2{font-size:20px;margin:0 0 8px}.update-settings p{font-size:13px;line-height:1.65;color:var(--text-2);margin:8px 0}.update-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.update-settings button{border:0;border-radius:999px;padding:9px 14px;min-height:38px;font:inherit;font-size:14px;background:#e9e9ee;color:#242428;cursor:pointer}.update-settings button.primary{background:#007aff;color:white}.update-settings button:disabled{opacity:.4;cursor:default}.update-settings button:focus-visible{outline:2px solid #007aff;outline-offset:2px}.update-settings [role=alert]{color:var(--red,#b42318)}.update-settings pre{white-space:pre-wrap;font:inherit;font-size:13px;line-height:1.6;max-height:200px;overflow:auto}.update-settings input{max-width:100%;font-size:13px}.update-settings progress{width:100%}@media(max-width:480px){.update-settings{padding:16px 12px}.update-settings button{max-width:100%;white-space:normal}}`;
if(!document.getElementById('updates-css')){const style=document.createElement('style');style.id='updates-css';style.textContent=CSS;document.head.appendChild(style);}

export function UpdateSettings({api,csrf}){
  const [data,setData]=useState(null),[pending,setPending]=useState(false),[error,setError]=useState(''),[reconnecting,setReconnecting]=useState(false);
  const mounted=useRef(true),loading=useRef(false),input=useRef(null);
  async function refresh(){
    if(loading.current)return;loading.current=true;
    try{const result=await api('/api/updates');if(!mounted.current)return;
      if(!result.ok){setError(result.error||'暂时无法读取更新状态');return;}
      setData(result);setReconnecting(false);
    }catch{if(mounted.current)setReconnecting(true);}finally{loading.current=false;}
  }
  useEffect(()=>{mounted.current=true;refresh();const timer=setInterval(refresh,2000);return()=>{mounted.current=false;clearInterval(timer);};},[]);
  async function operate(op){
    if(pending)return;setPending(true);setError('');
    try{const result=await api('/api/updates',{op},20000);if(!mounted.current)return;
      if(!result.ok)throw new Error(result.error||'更新请求未完成');setData(result);
    }catch(reason){if(mounted.current)setError(reason.message||'连接中断，正在重新读取任务状态');}
    finally{if(mounted.current){setPending(false);refresh();}}
  }
  async function upload(event){
    const file=event.target.files?.[0];if(!file)return;
    if(!file.size||file.size>160*1024*1024){setError('请选择 160 MiB 以内的软件更新包');event.target.value='';return;}
    setPending(true);setError('');
    try{const response=await fetch('/api/updates/upload',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/octet-stream','X-CSRF':csrf},body:file});
      const result=await response.json();if(!result.ok)throw new Error(result.error||'上传未完成');if(mounted.current)setData(result);
    }catch(reason){if(mounted.current)setError(reason.message||'上传中断，请重新选择文件');}
    finally{event.target.value='';if(mounted.current){setPending(false);refresh();}}
  }
  const actions=updateActions(data,pending),job=data?.job;
  return html`<section class="board update-settings" data-updates aria-label="软件更新">
    <h2>软件更新</h2>
    <p>当前套件：<strong data-update-installed>${data?.installed||'尚未登记'}</strong> · 包含网页控制台、匹配的小助手和本地坐站语音。</p>
    <p>更新前请关闭策略、语音监听和音乐，结束舵机、标定、录制与回放会话，让鸭子停稳并保持充足电量。</p>
    <p>安装会短暂重启网页和语音服务。页面会自动重连并读取保存的任务结果。</p>
    ${!data&&!error?html`<p role="status">读取更新服务…</p>`:null}
    <p role="status" data-update-phase=${job?.phase||'idle'}>${updateMessage(data)}${typeof job?.percent==='number'?`（${job.percent}%）`:''}</p>
    ${reconnecting?html`<p role="status">网页连接中断，正在重新读取独立更新服务的任务状态…</p>`:null}
    ${data?.busy&&typeof job?.percent==='number'?html`<progress max="100" value=${job.percent} aria-label=${PHASES[job.phase]||'更新进度'} />`:null}
    ${data?.candidate?html`<p>发布版本：<strong>${data.candidate.version}</strong>（下载验证前为发布源提供的信息）</p><pre>${data.candidate.changelog||'此发布未填写更新说明。'}</pre>`:null}
    ${data?.staged?html`<p>本机缓存：${data.staged.version} · ${data.ready?'验证通过':'尚未通过当前安装条件验证'}</p>`:null}
    <div class="update-actions">
      <button type="button" data-update="check" disabled=${!actions.check} onClick=${()=>operate('check')}>检查更新</button>
      <button type="button" data-update="download" disabled=${!actions.download} onClick=${()=>operate('download')}>下载更新</button>
      <button type="button" data-update="upload" disabled=${!actions.upload} onClick=${()=>input.current?.click()}>上传离线包</button>
      <input ref=${input} type="file" aria-label="软件更新包" accept=".tar" style="display:none" disabled=${!actions.upload} onChange=${upload} />
      <button type="button" data-update="validate" disabled=${!actions.validate} onClick=${()=>operate('validate')}>重新验证</button>
      <button type="button" class="primary" data-update="install" disabled=${!actions.install} onClick=${()=>operate('install')}>立即更新</button>
      <button type="button" data-update="rollback" disabled=${!actions.rollback} onClick=${()=>operate('rollback')}>退回上一版</button>
    </div>
    ${pending?html`<p role="status">正在提交请求…</p>`:null}
    ${error?html`<p role="alert">${error} <button type="button" onClick=${()=>{setError('');refresh();}}>重新读取</button></p>`:null}
    ${job?.id?html`<p>任务：${job.id}</p>`:null}
  </section>`;
}
