export function audioLabel(status) {
  if (!status?.available) return 'Serviço de voz desconectado';
  if (!status.listening) return 'Monitoramento desativado';
  return status.music ? 'Ouvindo música e perguntas' : 'Ouvindo você';
}

export function rhythmLabel(rhythm) {
  if (!rhythm || rhythm.confidence < .55 || !Number.isFinite(rhythm.bpm)
      || !Number.isFinite(rhythm.age) || rhythm.age > .5) return 'Aguardando um ritmo nítido';
  const feel = { lively: 'Animado', mellow: 'Suave', sway: 'Balançando' }[rhythm.feel];
  return feel ? `${feel} · ${Math.round(rhythm.bpm)} BPM` : 'Aguardando um ritmo nítido';
}

export function musicMotionLabel(motion) {
  if (motion?.state !== 'idle_motion' || motion.idle_kind !== 'music') return null;
  return motion.idle_phase === 'moving' ? 'Movendo-se ao som da música' : 'Aguardando um ritmo estável';
}
