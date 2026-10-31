import { html, useEffect, useRef, useState } from './vendor/preact-htm.module.js';
import { ARK_URL, blankDraft, draftFrom, isDirty, missingFields, requestMessages } from './ai-ui-state.js';

const CSS = `.ai-settings{padding:18px 20px;min-width:0}.ai-settings h2{margin:0 0 8px;font-size:20px}.ai-settings p{font-size:13px;line-height:1.65;color:var(--text-2);margin:8px 0}.ai-settings .ai-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px 0}.ai-settings label{display:flex;flex-direction:column;gap:5px;font-size:13px;min-width:0}.ai-settings input,.ai-settings select,.ai-settings textarea{width:100%;min-width:0;box-sizing:border-box;border:1px solid var(--line,#d2d2d7);border-radius:9px;background:var(--surface,#fff);color:inherit;padding:9px;font:inherit}.ai-settings .ai-wide{grid-column:1/-1}.ai-settings .ai-check{flex-direction:row;align-items:center}.ai-settings .ai-check input{width:auto}.ai-settings .btn{border:0;border-radius:999px;padding:9px 15px;min-height:38px;font:inherit;font-size:14px;background:#e9e9ee;color:#242428;cursor:pointer}.ai-settings .btn.primary{background:#007aff;color:white}.ai-settings .btn:disabled{opacity:.4;cursor:default}.ai-settings .btn:focus-visible{outline:2px solid #007aff;outline-offset:2px}.ai-actions{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}.ai-settings .ai-result{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}.ai-settings .ai-chat{border-top:1px solid var(--line,#ddd);margin-top:18px;padding-top:12px}.ai-settings .ai-message{white-space:pre-wrap;overflow-wrap:anywhere;border-radius:9px;padding:9px 11px;margin:7px 0;background:var(--surface-2,#f1f2f5);font-size:14px}.ai-settings .ai-message strong{font-size:12px;display:block;margin-bottom:3px}.ai-settings [role=alert]{color:var(--red,#b42318)}@media(max-width:480px){.ai-settings{padding:16px 12px}.ai-settings .ai-fields{grid-template-columns:1fr}.ai-settings .btn{max-width:100%;white-space:normal}}`;
if (!document.getElementById('ai-settings-css')) {
  const style = document.createElement('style'); style.id = 'ai-settings-css'; style.textContent = CSS; document.head.appendChild(style);
}

export function AiSettings({ api }) {
  const [data,setData] = useState(null), [form,setForm] = useState(blankDraft);
  const [selected,setSelected] = useState(''), [busy,setBusy] = useState(false);
  const [error,setError] = useState(''), [notice,setNotice] = useState(''), [tested,setTested] = useState(false);
  const [history,setHistory] = useState([]), [input,setInput] = useState('');
  const alive = useRef(false), controller = useRef(null), pending = useRef(false);
  const clearConversation = () => {setHistory([]);setInput('');setTested(false);setNotice('');};
  const apply = (response, id) => {
    setData(response);setSelected(id || '');
    setForm(draftFrom(response.connections.find(item=>item.id === id)));
  };
  const run = async (body, done) => {
    if (pending.current) return;
    pending.current = true;setBusy(true);setError('');
    const ctl = new AbortController();controller.current = ctl;
    try {
      const response = await api('/api/ai',body,24000,ctl.signal);
      if (!alive.current) return;
      if (!response.ok) {
        if (response.code === 'stale') clearConversation();
        setError(response.error || 'A solicitação de IA não foi concluída');return;
      }
      done(response);
    } catch (error) {
      if (alive.current) setError(error?.name === 'AbortError' ? 'A solicitação de IA expirou ou foi cancelada. Tente novamente.' : 'A conexão da página foi interrompida. Tente novamente.');
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  };
  useEffect(()=>{
    alive.current = true;
    run(undefined,response=>apply(response,response.current_id));
    return ()=>{alive.current = false;controller.current?.abort();};
  },[]);
  const saved = data?.connections.find(item=>item.id === selected);
  const dirty = isDirty(form,saved), missing = missingFields(form,saved);
  const ready = !!saved?.ready && !dirty && !busy;
  const edit = (key,value) => {setForm({...form,[key]:value});setError('');clearConversation();};
  const choose = id => {setSelected(id);setForm(draftFrom(data.connections.find(item=>item.id === id)));setError('');clearConversation();};
  const save = () => run({op:'save',connection:form},response=>{apply(response,response.saved_id);clearConversation();setNotice('Conexão salva; salvar não contata o provedor');});
  const select = () => run({op:'select',id:selected},response=>{apply(response,selected);clearConversation();setNotice('Definida como conexão atual');});
  const remove = () => run({op:'delete',id:selected},response=>{apply(response,'');clearConversation();setNotice('Conexão removida');});
  const test = () => {setTested(false);setNotice('');run({op:'test',id:selected,revision:saved.revision},response=>{
    if (response.id === selected && response.revision === saved.revision) {setTested(true);setNotice(response.text);}
  });};
  const send = () => {
    const content = input.trim();if (!content || !ready) return;
    const messages = requestMessages(history,content);
    run({op:'chat',id:selected,revision:saved.revision,messages},response=>{
      if (response.id === selected && response.revision === saved.revision) {
        setHistory([...messages,{role:'assistant',content:response.text}].slice(-10));setInput('');
      }
    });
  };
  return html`<section id="ai-settings" class="board ai-settings" data-ai-settings aria-label="Conversa com IA">
    <h2>Conversa com IA</h2>
    <p>Salve primeiro as configurações do provedor e do modelo; preencha a chave depois de criar a conta. No momento, há somente conversa de texto pela página. Microfone, alto-falante e voz em tempo real ainda não foram integrados, e a conversa não controla o robô.</p>
    ${error ? html`<p role="alert">${error}</p>` : null}
    ${!data ? html`<p>${busy ? 'Carregando configurações de IA…' : 'As configurações de IA estão indisponíveis. Defina uma senha para a página e atualize-a.'}</p>` : html`
    <label>Conexões salvas<select aria-label="Conexões salvas" value=${selected} disabled=${busy} onChange=${e=>choose(e.target.value)}>
      <option value="">Nova conexão</option>${data.connections.map(item=>html`<option value=${item.id}>${item.name || 'Rascunho sem nome'}${item.id === data.current_id ? '(atual)' : ''}</option>`)}
    </select></label>
    <p data-ai-current>Atual: ${data.connections.find(item=>item.id === data.current_id)?.name || 'Nenhuma selecionada'} · salvas ${data.connections.length}/10</p>
    <div class="ai-actions"><button type="button" class="btn" data-ai="new" disabled=${busy || data.connections.length >= 10} onClick=${()=>choose('')}>Nova conexão</button></div>
    <fieldset disabled=${busy} style="border:0;padding:0;margin:0;min-width:0" data-ai-connection=${selected || ''}>
      <div class="ai-fields">
        <label>Nome da conexão<input aria-label="Nome da conexão" maxlength="80" value=${form.name} onInput=${e=>edit('name',e.target.value)} placeholder="Ex.: modelo de texto Doubao" /></label>
        <label>Provedor<select aria-label="Provedor" value=${form.provider} onChange=${e=>{
          const provider=e.target.value;setForm({...form,provider,base_url:provider === 'doubao_ark' ? ARK_URL : '',api_key:'',clear_key:false});setError('');clearConversation();
        }}><option value="doubao_ark">Doubao · modelo de texto Ark</option><option value="openai_compatible">Outra interface compatível com OpenAI</option></select></label>
        <label class="ai-wide">Base URL<input aria-label="Base URL" maxlength="500" value=${form.base_url} onInput=${e=>edit('base_url',e.target.value)} placeholder="https://endereco-do-servico/v1" spellcheck="false" /></label>
        <label class="ai-wide">Model ID<input aria-label="Model ID" maxlength="200" value=${form.model} onInput=${e=>edit('model',e.target.value)} placeholder="Informe o ID do modelo ou do endpoint fornecido pelo console" spellcheck="false" /></label>
        <label class="ai-wide">API Key<input type="password" aria-label="API Key" value=${form.api_key} maxlength="4096" autocomplete="new-password" onInput=${e=>edit('api_key',e.target.value)} placeholder=${saved?.key_configured ? 'Salvo; deixe em branco para manter a chave do mesmo provedor e endereço' : 'Ainda não configurado; você pode salvar um rascunho'} /></label>
        <label class="ai-check ai-wide"><input type="checkbox" checked=${form.clear_key} onChange=${e=>edit('clear_key',e.target.checked)} />Remover a chave de API salva</label>
        <label class="ai-check ai-wide"><input aria-label="Não requer chave de API (somente serviço local)" type="checkbox" checked=${form.auth_mode === 'none'} onChange=${e=>edit('auth_mode',e.target.checked ? 'none' : 'bearer')} />Não requer chave de API (somente serviço local)</label>
      </div>
    </fieldset>
    <p>A chave fica somente no Microduck; não é exibida novamente na página nem incluída no armazenamento do navegador, nos logs ou no pacote de diagnóstico. Após trocar o provedor ou endereço, informe a chave novamente ou selecione explicitamente um serviço local sem chave.</p>
    ${missing.length ? html`<p data-ai-missing>Falta preencher: ${missing.join('、')}. O rascunho pode ser salvo; preencha os campos e salve antes de testar ou conversar.</p>` : dirty ? html`<p>Há alterações não salvas. Salve primeiro.</p>` : null}
    <div class="ai-actions">
      <button class="btn primary" type="button" data-ai="save" disabled=${busy || !dirty || (!saved && data.connections.length >= 10)} onClick=${save}>Salvar conexão</button>
      <button class="btn" type="button" data-ai="select" disabled=${!ready || data.current_id === selected} onClick=${select}>Definir como atual</button>
      <button class="btn" type="button" data-ai="delete" disabled=${busy || !saved} onClick=${remove}>Remover conexão</button>
      <button class="btn" type="button" data-ai="test" disabled=${!ready} onClick=${test}>Testar conexão</button>
    </div>
    <p>Salvar ou selecionar não faz chamadas à nuvem. Testar a conexão envia uma solicitação curta de texto e pode gerar custos do provedor.</p>
    ${busy ? html`<p role="status">Processando…</p>` : null}
    ${notice ? html`<p class="ai-result" role="status" data-ai-tested=${tested}>${tested ? 'Teste concluído: ' : ''}${notice}</p>` : null}
    <div class="ai-chat"><strong>Conversa de teste por texto</strong><p>O contexto recente fica somente na memória desta página (até 5 turnos e 12.000 caracteres); cada mensagem pode ter até 2.000 caracteres. O contexto é apagado ao trocar ou editar a conexão ou sair das configurações. O histórico não é salvo.</p>
      <div aria-live="polite" data-ai-history>${history.map(message=>html`<div class="ai-message"><strong>${message.role === 'user' ? 'Você' : 'Modelo'}</strong>${message.content}</div>`)}</div>
      <label>Mensagem de teste<textarea aria-label="Mensagem de teste" rows="3" maxlength="2000" disabled=${busy} value=${input} onInput=${e=>setInput(e.target.value)} placeholder="Depois de configurar e testar o serviço, você poderá conversar aqui" /></label>
      <div class="ai-actions"><button class="btn primary" type="button" data-ai="send" disabled=${!ready || !input.trim()} onClick=${send}>Enviar</button><button class="btn" type="button" data-ai="clear" disabled=${busy || (!history.length && !input)} onClick=${()=>{setHistory([]);setInput('');}}>Limpar conversa</button></div>
    </div>
    <p>A voz em tempo real do Doubao usa um endereço e protocolo WebSocket próprios. Não informe o endereço de voz aqui como interface de texto. A integração de voz será configurada separadamente em uma etapa futura.</p>`}
  </section>`;
}
