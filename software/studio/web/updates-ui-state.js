export const PHASES={queued:'Aguardando início da tarefa',uploading:'Enviando',checking:'Verificando a origem das versões',downloading:'Baixando',downloaded:'Download concluído',
  preflight:'Verificando se o robô está parado e a alimentação está estável',verifying:'Verificando assinatura e pacote',extracting:'Verificando arquivos de execução',swapping:'Trocando a versão',
  applying:'Iniciando os serviços web e de voz compatíveis',health_gate:'Verificando a interface web e o serviço de voz local',committing:'Registrando o resultado da instalação',
  rolling_back:'Restaurando a versão anterior',completed:'Tarefa concluída',failed:'Tarefa falhou',interrupted:'Tarefa interrompida; confira o resultado',
  waiting_validation:'Download concluído; aguardando confirmação de que o robô está parado',rolled_back:'Atualização falhou; versão anterior restaurada'};
export function updateMessage(data){
  if(!data?.available)return 'O serviço de atualização de software não está instalado ou está temporariamente indisponível';
  const job=data.job;
  if(job?.phase==='rolled_back')return 'A atualização falhou; a versão anterior foi restaurada.'+(job.error||'');
  if(job?.phase==='waiting_validation')return 'Download concluído; aguardando confirmação de que o robô está parado.'+(job.error||'');
  if(job?.phase==='failed'||job?.phase==='interrupted')return (PHASES[job.phase]||'Tarefa não concluída')+' — '+(job.error||'Tente novamente');
  if(data.busy)return PHASES[job?.phase]||'Atualização em andamento';
  if(data.ready)return 'A assinatura e os arquivos de execução foram verificados pelo mecanismo de atualização. Pronto para instalar.';
  if(data.source_state==='no_release')return 'Ainda não há uma versão publicada para atualização.';
  if(data.source_state==='network_error')return 'Falha ao verificar a rede. Tente novamente mais tarde; ainda não foi possível confirmar se há atualização.';
  if(data.source_state==='up_to_date')return 'Esta é a versão mais recente disponível na origem de atualizações.';
  if(data.source_state==='available')return 'Há uma atualização disponível. O mecanismo de atualização verificará os arquivos após o download.';
  return job?.phase==='completed'?'Tarefa concluída.':'Verifique se há atualizações ou envie um pacote offline.';
}
export function updateActions(data,pending=false){
  const idle=!!data?.available&&!data.busy&&!pending;
  const nativeBusy=data?.native?.active===true||data?.native?.submitting===true;
  return {check:idle,upload:idle,download:idle&&!!data.candidate&&data.source_state==='available',
    validate:idle&&!!data.staged,install:idle&&!nativeBusy&&data.ready===true,rollback:idle&&!nativeBusy&&data.can_rollback===true};
}

export const NATIVE_PHASES={prepared:'Backup concluído; preparando a proteção do serviço de controle',guarding:'Ativando proteção persistente',guarded:'Serviço de controle isolado; confirme que os motores estão sem força',
  replacing:'Instalando o programa principal',replaced:'Programa principal substituído; aguardando confirmação da inicialização real',verified_commissioning:'Inicialização real no modo de calibração confirmada',
  restoring_normal:'Restaurando o modo de controle normal',verified_motion:'Processo real de controle confirmado; motores permanecem sem força',factory_handoff_pending:'Transferindo para o fluxo inicial de calibração',
  completed:'Operação registrada como concluída',rolled_back:'Instalação falhou; versão anterior restaurada e confirmada',recovering:'Restaurando o programa principal com segurança',
  old_restored:'Programa principal anterior restaurado; aguardando confirmação de execução',recovery_required:'Atualização do programa principal incompleta; mantenha os motores sem força durante a recuperação'};

export function nativeMessage(native){
  if(!native)return 'Lendo o estado do programa principal…';
  if(native.active)return (NATIVE_PHASES[native.phase]||'A proteção da atualização do programa principal continua ativa; verifique se é preciso restaurar')+(native.reason?`. ${native.reason}`:'');
  if(native.submitting)return 'Enviando solicitação ao assistente independente. Aguarde a confirmação do estado de execução; atualize a página para continuar acompanhando.';
  if(!native.service_available)return native.reason||'O assistente atual não oferece o serviço de atualização do programa principal. Atualize primeiro a interface web e o serviço de voz.';
  if(native.current)return 'A identidade do programa principal em execução foi confirmada.'+(native.mode==='commissioning'?' Continue com a seleção e a verificação da orientação da IMU.':'A validação física do MicroDuck ainda está pendente. Verifique a orientação da IMU antes de usar.');
  if(!native.available)return 'Este pacote não contém uma atualização instalável do programa principal.';
  if(!native.supported)return native.reason||'A identidade do programa principal em execução não foi confirmada. A instalação automática está indisponível; peça ao responsável pela manutenção para verificar a versão.';
  if(native.phase==='rolled_back')return 'A instalação falhou; a versão anterior foi restaurada e confirmada.'+(native.reason||'');
  return 'A atualização do programa principal está aguardando instalação. A versão da interface web ou do serviço de voz não indica que o programa principal foi atualizado.';
}

export function nativeActions(data,pending=false,confirmed=false){
  const native=data?.native;
  const idle=!!native?.service_available&&!data?.busy&&!native.submitting&&!pending&&confirmed===true;
  return {install:idle&&native.available===true&&native.supported===true&&!native.current&&!native.active,
    recover:idle&&native.active===true};
}
