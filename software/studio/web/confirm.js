// Confirmação em duas etapas, compartilhada por todas as ações que exigem dois cliques, como devolver o controle ao programa principal e pular a verificação da parada de emergência.
// O botão original permanece no lugar, e um botão de confirmação aparece ao lado para evitar que um clique duplo confirme a ação acidentalmente.
// Cliques nos primeiros 700 ms são ignorados para evitar toques involuntários. Se não houver confirmação em 3 s, a ação é cancelada; um novo clique no botão original recolhe a confirmação.
// Não use a janela confirm do navegador: ela bloqueia a página e pode cobrir o botão de segurança no celular.
import { html, useState, useEffect, useRef } from './vendor/preact-htm.module.js';

export const ARM_GUARD_MS = 700;
export const ARM_TIMEOUT_MS = 3000;

export function ConfirmBox({ lines = [], confirmLabel = 'Confirmar', cancelLabel = 'Agora não', onConfirm, onCancel, busy = false, cls = '' }) {
  return html`<div class=${('confirm-box ' + cls).trim()} role="alertdialog" aria-live="polite">
    <div class="confirm-lines">${lines.map((line) => html`<p>${line}</p>`)}</div>
    <div class="confirm-acts">
      <button class="btn-light" type="button" disabled=${busy} onClick=${() => onCancel && onCancel()}>${cancelLabel}</button>
      <button class="btn-danger" type="button" disabled=${busy} onClick=${() => onConfirm && onConfirm()}>${confirmLabel}</button>
    </div>
  </div>`;
}

export function TwoStep({ label, ask, onConfirm, cls = 'btn-light', askCls = 'btn-danger', disabled = false, title, busyLabel }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const at = useRef(0);
  useEffect(() => {
    if (!armed) return undefined;
    const t = setTimeout(() => setArmed(false), ARM_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [armed]);
  const early = () => performance.now() - at.current < ARM_GUARD_MS;
  const first = (e) => {
    e.currentTarget.blur();
    if (armed) { if (!early()) setArmed(false); return; }
    at.current = performance.now();
    setArmed(true);
  };
  const second = async (e) => {
    e.currentTarget.blur();
    if (!armed || early()) return;
    setArmed(false);
    setBusy(true);
    try { await onConfirm(); } finally { setBusy(false); }
  };
  return html`<span class="two-step">
    <button class=${cls} disabled=${disabled || busy} title=${title || undefined} aria-expanded=${armed ? 'true' : 'false'}
      onClick=${first}>${busy && busyLabel ? busyLabel : label}</button>
    ${armed ? html`<button class=${`${askCls} two-step-ask`} onClick=${second}>${ask}</button>` : null}</span>`;
}
