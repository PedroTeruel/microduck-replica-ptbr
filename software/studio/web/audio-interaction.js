import { html, useEffect, useRef, useState } from './vendor/preact-htm.module.js';
import { audioLabel, rhythmLabel } from './audio-ui-state.js';

export function AudioInteraction({ pad, link, activity }) {
  const status = pad?.audio;
  const [active, setActive] = useState(activity.active);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const alive = useRef(false), busy = useRef(false);
  useEffect(() => {
    alive.current = true;
    const off = activity.subscribe(({active:value}) => setActive(value));
    return () => { alive.current = false; off(); };
  }, [activity]);
  const change = async values => {
    if (busy.current || !activity.active || link.status !== 'open') return;
    busy.current = true; setPending(true); setError(null);
    try {
      const response = await link.cmd('pad.op', {op:'audio', ...values}, 2500);
      if (alive.current && !response?.ok) setError(response?.reason || response?.error || 'Não foi possível alterar a configuração de voz');
    } catch (err) {
      if (alive.current) setError(err?.message || 'A conexão de voz foi interrompida');
    } finally {
      busy.current = false;
      if (alive.current) setPending(false);
    }
  };
  const ready = active && link.status === 'open' && !pending;
  return html`<section id="audio-interaction" class="pd-motion" aria-label="Interação por voz e música">
    <div class="motion-heading"><h4>Interação por voz e música</h4>
      <span class="motion-state" role="status" data-audio-listening=${!!status?.listening}>${audioLabel(status)}</span>
    </div>
    <div class="motion-toolbar">
      <a class="btn-light" href="#/settings" data-ai-link>Configurar conversa com IA (teste por texto)</a>
      <button type="button" class=${status?.listening ? 'motion-stop' : 'btn-primary'} data-audio="listening"
        disabled=${!ready || !status?.available} onClick=${() => change({listening:!status?.listening})}>
        ${status?.listening ? 'Desativar escuta' : 'Ativar escuta'}</button>
      <button type="button" class="btn-light" data-audio="music" disabled=${!ready || !status?.available}
        onClick=${() => change({music:!status?.music})}>${status?.music ? 'Sair do modo música' : 'Ouvir música'}</button>
    </div>
    ${error || status?.error ? html`<p class="motion-error" role="alert">${error || status.error}</p>` : null}
    ${!status?.available ? html`<p class="pd-small-p">${status?.why || 'Aguardando conexão com o serviço de voz'}</p>` : null}
    ${status?.listening && status?.music ? html`<p class="pd-small-p" data-audio-rhythm>${rhythmLabel(status.rhythm)}</p>
      <p class="pd-small-p">Toque uma música perto do celular ou de uma caixa de som e pergunte, por exemplo, “O que você achou?” ou “Você gosta desse tipo de música?”.
      Os sons do Microduck acompanham o ritmo recente; quando a confiança é baixa, ele responde com um som de pergunta. No modo música, comandos para sentar ou levantar e a repetição de músicas inteiras ainda não estão disponíveis.</p>` : null}
    <p class="pd-small-p motion-note">Pressione R3 uma vez para ativar a escuta; o Microduck emitirá um som curto. Pressione novamente para desativar. Aguarde um instante após o sinal antes de falar.
      Os comandos comuns são “Sente-se” e “Levante-se”. O Microduck confirma a ação com um som e não reproduz a fala literalmente. A repetição de gravações permanece separada; o botão dedicado será configurado depois.</p>
    <p class="pd-small-p motion-note">A escuta permanece ativa até ser desativada. Para ouvir música, desligue primeiro o controle físico, deixe o Microduck em pé e toque em “Começar a andar”.
      Mantenha a página em primeiro plano na área do controle e toque em “Movimento ao som da música”. A cabeça acompanha o ritmo suavemente; o movimento do corpo depende do modelo de movimento.
      Depois de iniciar esse movimento independente, ele continua ao tirar o foco, alternar para o segundo plano, sair da área do controle ou navegar para outra página. Fechar a página ou perder a conexão interrompe o movimento.
      Volte a esta página para interrompê-lo. Durante uma gravação, a página e a área do controle precisam continuar visíveis; sair dela interrompe a gravação.</p>
  </section>`;
}
