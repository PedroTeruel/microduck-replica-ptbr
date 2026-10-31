import {html,useEffect,useRef,useState} from './vendor/preact-htm.module.js';
import {updateMessage,updateActions,PHASES,nativeMessage,nativeActions} from './updates-ui-state.js';

const CSS=`.update-settings{padding:18px 20px;min-width:0;overflow-wrap:anywhere}.update-settings h2{font-size:20px;margin:0 0 8px}.update-settings p{font-size:13px;line-height:1.65;color:var(--text-2);margin:8px 0}.update-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.update-settings button{border:0;border-radius:999px;padding:9px 14px;min-height:38px;font:inherit;font-size:14px;background:#e9e9ee;color:#242428;cursor:pointer}.update-settings button.primary{background:#007aff;color:white}.update-settings button:disabled{opacity:.4;cursor:default}.update-settings button:focus-visible{outline:2px solid #007aff;outline-offset:2px}.update-settings [role=alert]{color:var(--red,#b42318)}.update-settings pre{white-space:pre-wrap;font:inherit;font-size:13px;line-height:1.6;max-height:200px;overflow:auto}.update-settings input{max-width:100%;font-size:13px}.update-settings progress{width:100%}@media(max-width:480px){.update-settings{padding:16px 12px}.update-settings button{max-width:100%;white-space:normal}}`;
if(!document.getElementById('updates-css')){const style=document.createElement('style');style.id='updates-css';style.textContent=CSS;document.head.appendChild(style);}

export function UpdateSettings({api,csrf}){
  const [data,setData]=useState(null),[pending,setPending]=useState(false),[error,setError]=useState(''),[reconnecting,setReconnecting]=useState(false);
  const [confirmed,setConfirmed]=useState(false);
  const mounted=useRef(true),loading=useRef(false),input=useRef(null);
  const merge=result=>setData(previous=>({...previous,...result,native:result.native??previous?.native}));
  async function refresh(){
    if(loading.current)return;loading.current=true;
    try{const result=await api('/api/updates');if(!mounted.current)return;
      if(!result.ok){setError(result.error||'Não foi possível consultar o estado das atualizações.');return;}
      merge(result);setReconnecting(false);
    }catch{if(mounted.current)setReconnecting(true);}finally{loading.current=false;}
  }
  useEffect(()=>{mounted.current=true;refresh();const timer=setInterval(refresh,2000);return()=>{mounted.current=false;clearInterval(timer);};},[]);
  async function operate(op){
    if(pending)return;setPending(true);setError('');
    const native=op==='native_install'||op==='native_recover';
    if(native&&!confirmed){setPending(false);return;}
    try{const result=await api('/api/updates',native?{op,confirmed:true}:{op},20000);if(!mounted.current)return;
      if(!result.ok)throw new Error(result.error||'A solicitação de atualização não foi concluída.');merge(result);
    }catch(reason){if(mounted.current)setError(reason.message||'A conexão foi interrompida. Consultando novamente o estado da tarefa.');}
    finally{if(mounted.current){if(native)setConfirmed(false);setPending(false);refresh();}}
  }
  async function upload(event){
    const file=event.target.files?.[0];if(!file)return;
    if(!file.size||file.size>160*1024*1024){setError('Selecione um pacote de atualização de até 160 MiB.');event.target.value='';return;}
    setPending(true);setError('');
    try{const response=await fetch('/api/updates/upload',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/octet-stream','X-CSRF':csrf},body:file});
      const result=await response.json();if(!result.ok)throw new Error(result.error||'O envio não foi concluído.');if(mounted.current)merge(result);
    }catch(reason){if(mounted.current)setError(reason.message||'O envio foi interrompido. Selecione o arquivo novamente.');}
    finally{event.target.value='';if(mounted.current){setPending(false);refresh();}}
  }
  const actions=updateActions(data,pending),job=data?.job,native=data?.native,nativeOps=nativeActions(data,pending,confirmed);
  return html`<section class="board update-settings" data-updates aria-label="Atualizações de software">
    <h2>Atualizações de software</h2>
    <h3>① Interface web e software de voz</h3>
    <p>Versão atual da interface web e do software de voz: <strong data-update-installed>${data?.installed||'não registrada'}</strong> · inclui o console web, o assistente compatível e os comandos locais de sentar e levantar por voz.</p>
    <p>Antes de atualizar, interrompa as atividades e coloque o Microduck em pé conforme o procedimento normal. Desative a política de movimento, a escuta por voz e a música; encerre as sessões de servos, calibração, gravação e reprodução. Mantenha a bateria carregada.</p>
    <p>A instalação reinicia brevemente a interface web e o serviço de voz. A página se reconectará automaticamente e consultará o resultado salvo da tarefa.</p>
    ${!data&&!error?html`<p role="status">Consultando o serviço de atualização…</p>`:null}
    <p role="status" data-update-phase=${job?.phase||'idle'}>${updateMessage(data)}${typeof job?.percent==='number'?`（${job.percent}%）`:''}</p>
    ${reconnecting?html`<p role="status">A conexão com a interface foi interrompida. Consultando novamente o estado da tarefa no serviço de atualização…</p>`:null}
    ${data?.busy&&typeof job?.percent==='number'?html`<progress max="100" value=${job.percent} aria-label=${PHASES[job.phase]||'Progresso da atualização'} />`:null}
    ${data?.candidate?html`<p>Versão publicada: <strong>${data.candidate.version}</strong> (informação da fonte de lançamento antes do download e da verificação)</p><pre>${data.candidate.changelog||'Esta versão não inclui notas de atualização.'}</pre>`:null}
    ${data?.staged?html`<p>Arquivo em cache local: ${data.staged.version} · ${data.ready?'verificado':'ainda não atende aos requisitos atuais de instalação'}</p>`:null}
    <div class="update-actions">
      <button type="button" data-update="check" disabled=${!actions.check} onClick=${()=>operate('check')}>Verificar atualizações</button>
      <button type="button" data-update="download" disabled=${!actions.download} onClick=${()=>operate('download')}>Baixar atualização</button>
      <button type="button" data-update="upload" disabled=${!actions.upload} onClick=${()=>input.current?.click()}>Enviar pacote offline</button>
      <input ref=${input} type="file" aria-label="Pacote de atualização de software" accept=".tar" style="display:none" disabled=${!actions.upload} onChange=${upload} />
      <button type="button" data-update="validate" disabled=${!actions.validate} onClick=${()=>operate('validate')}>Verificar novamente</button>
      <button type="button" class="primary" data-update="install" disabled=${!actions.install} onClick=${()=>operate('install')}>Atualizar agora</button>
      <button type="button" data-update="rollback" disabled=${!actions.rollback} onClick=${()=>operate('rollback')}>Reverter interface e voz para a versão anterior</button>
    </div>
    ${pending?html`<p role="status">Enviando solicitação…</p>`:null}
    ${error?html`<p role="alert">${error} <button type="button" onClick=${()=>{setError('');refresh();}}>Consultar novamente</button></p>`:null}
    ${job?.id?html`<p>Tarefa: ${job.id}</p>`:null}
    <hr />
    <div data-native-updates style="scroll-margin-top:72px">
      <h3>② Atualização do programa principal (opcional)</h3>
      <p>Esta opção permite selecionar manualmente o tipo de placa Qinmo nesta versão. Placas existentes podem continuar usando “Detecção automática (placa existente)”; não é necessário atualizar o programa principal para manter o uso atual. Somente a versão-base conhecida 20261027 é compatível; outras versões devem ser verificadas pela equipe de manutenção.</p>
      <p role="status" data-native-phase=${native?.phase||'unavailable'}>${nativeMessage(native)}</p>
      <p>Estado da instalação: <strong data-native-identity>${native?.supported?'verificado':'não verificado'}</strong>${native?.mode?` · ${native.mode==='motion'?'modo de movimento':native.mode==='commissioning'?'modo de calibração':native.mode}`:''}</p>
      ${native?.installed_sha256||native?.transaction_id?html`<details><summary>Informações de diagnóstico</summary>${native?.installed_sha256?html`<p>SHA256 instalado: ${native.installed_sha256}</p>`:null}${native?.transaction_id?html`<p>Transação do programa principal: ${native.transaction_id}</p>`:null}</details>`:null}
      <p>Segure e apoie o Microduck, libere os servos e desative a política de movimento, a voz, a música e todas as sessões de gravação e calibração. Após a confirmação, uma tarefa independente atualizará o programa principal. Se a página desconectar durante o processo, reconecte para acompanhar. Na etapa 2, mantenha o Microduck apoiado e os servos liberados.</p>
      <label style="display:flex;align-items:flex-start;gap:8px;font-size:13px;line-height:1.6"><input type="checkbox" data-native-confirm checked=${confirmed} onChange=${event=>setConfirmed(event.target.checked)} disabled=${pending||!native?.service_available||!!data?.busy} /><span>Segurei e apoiei o Microduck, confirmei que os servos estão liberados e encerrei as atividades acima. Autorizo instalar ou restaurar o programa principal.</span></label>
      <div class="update-actions">
        <button type="button" class="primary" data-update="native_install" disabled=${!nativeOps.install} onClick=${()=>operate('native_install')}>Confirmar instalação do programa principal</button>
        <button type="button" data-update="native_recover" disabled=${!nativeOps.recover} onClick=${()=>operate('native_recover')}>Restaurar atualização incompleta do programa principal</button>
      </div>
      ${native?.request_error?html`<p role="alert">${native.request_error}. Considere o estado exibido aqui como referência; a parada de emergência continua disponível.</p>`:null}
      <p>Se a atualização do programa principal falhar, o sistema tentará restaurar o binário anterior. O botão “Reverter interface e voz” acima não reverte o programa principal; a redução de versão dele não está incluída nesta versão. A placa Qinmo física e a atualização completa do sistema ainda precisam ser validadas no hardware.</p>
    </div>
  </section>`;
}
