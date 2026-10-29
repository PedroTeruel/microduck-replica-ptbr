# Voz contínua e interação musical

O usuário definiu: um toque em R3 ativa a escuta por voz e outro toque a desativa; o áudio vem de um celular ou alto-falante próximo. Ao ouvir música, o pato responde com movimentos pequenos da cabeça e do corpo; quando perguntarem “o que está achando?” ou “gosta desse tipo de música?”, responde com vocalizações diferentes conforme a sensação musical. Usar o microfone integrado, reconhecimento local e os recursos existentes de atualização de software pela Web e SSH.

## Primeira entrega: escuta contínua por voz com R3

Depois de ativada, a escuta usa um único fluxo de microfone compartilhado e separa as frases automaticamente após as pausas; cada frase pode ter no máximo 10 s. Desativar, pressionar Select, perder a conexão com o controle, perder quadros de entrada ou encerrar o serviço cancela qualquer reconhecimento ou reprodução ainda não executados. Ignorar repetições do botão; se R3 já estiver pressionado na inicialização, exigir que seja solto antes de aceitar novo acionamento. Preservar os comandos de sentar/levantar. Conforme pedido posterior explícito do usuário, ao ativar por R3 ou pela Web, tocar um grasnado curto; no modo diário padrão, não repetir o áudio do usuário. Ações reconhecidas e perguntas sobre música recebem vocalizações nativas do pato. Repetição da gravação é uma função separada; manter a configuração explícita echo e a opção CLI record, deixando um botão separado para decisão futura. Pausar o processamento da captação durante a reprodução do próprio áudio e aguardar o fim do som para evitar autorrepetição. Usar o modo de toque único por padrão; manter a configuração explícita hold para voltar ao modo de pressionar e segurar. Não salvar áudio em disco nem usar serviço na nuvem.

A primeira entrega já confirmou a separação real das frases usando repetição. No modo diário futuro, validar os comandos de sentar/levantar, as vocalizações nativas e as perguntas sobre música; ao tocar novamente, a escuta deve ser desativada. Não transformar a alternância de um toque em uma ação que ainda exija manter o botão pressionado ou que desligue automaticamente a cada 10 s. Em caso de falha do microfone, encerrar a escuta desta rodada; não entrar em um loop ocupado.

Depois, o usuário pediu explicitamente avisos sonoros diferentes também para o desligamento: ao mudar de ativo para inativo por R3 ou pela Web, tocar uma vez o som grave coo; ao ativar, usar chirp. Continuar escutando após separar cada frase, sem tocar o aviso de desligamento. Cancelamentos automáticos por Select, desconexão, perda de quadros, falha ou encerramento do serviço não emitem som. O aviso de desligamento reutiliza uma thread de despacho limitada; reativar ou sair cancela avisos antigos ainda não reproduzidos, sem criar uma thread nova a cada toque.

## Segunda entrega: percepção musical e resposta

O mesmo fluxo do microfone estima batidas e estados aproximados de música animada, grave, relaxada/com balanço ou incerta; andamento rápido ou lento não deve ser tratado como identificação precisa de gênero, como jazz. Perguntas e comandos de ação são processados separadamente; somente perguntas reconhecidas com confiança acionam vocalizações, e o áudio do próprio grasnado é suprimido durante a reprodução. Se não houver confiança suficiente, usar um som interrogativo. Testar as perguntas com música tocando continuamente; testes unitários em silêncio não são suficientes.

## Terceira entrega: movimentos e Web

Intenções de movimento de baixa amplitude da cabeça e do corpo passam pelo mecanismo de arbitragem de controle existente no Studio e só são executadas quando a política está no controle, o estado dos dados está atualizado e a postura está estável. Operação manual do controle, controle pela Web, gravação/reprodução, movimento expressivo, sentar/levantar e perda de conexão têm prioridade. Não aumentar torque por conta própria, iniciar a política nem trocar o modelo. Parar o movimento rítmico quando houver silêncio, dados expirados ou a função for desligada. A Web mostra estado da escuta, batida, sensação musical e motivo de pausa. A placa atual não tem dissipador; antes de habilitar análise contínua, registrar carga e temperatura.

## Publicação

Entregar gradualmente versões testáveis; preservar arquivos e configurações anteriores à instalação, testar e registrar a versão no inventário de funcionalidades do software. Reiniciar somente os serviços necessários para esta tarefa; não reiniciar o núcleo de movimento. O usuário valida os movimentos reais.
