# Gravação e reprodução de movimentos na Web: projeto da primeira versão

Data: 24/10/2026. Estado atualizado em 25/10/2026: a implementação foi autorizada pelo usuário e implantada no endereço de controle existente do pato. As verificações de software e a conferência após a implantação passaram; o efeito dos movimentos no equipamento real ainda aguarda o teste do usuário.

Revisão de 25/10/2026: naquele momento, a gravação e a reprodução Web ainda não estavam implementadas. A descrição da rota de voz mais adiante refletia o estado quando este texto foi redigido; o serviço R3 independente de fala contínua e voz para sentar/levantar foi validado depois no pato atual. Consulte o [serviço de voz](../../../software/duck-echo/README.md). O usuário também propôs vincular novas funções, movimentos de modelo e reproduções salvas ao controle. Isso foi incorporado ao [inventário de funções e atualizações](../../软件功能与升级总账.md) como uma extensão além da primeira versão original; o escopo inicial não foi ampliado silenciosamente aqui.

Implementação posterior em 25/10/2026: a frase acima, “ainda não implementadas”, descrevia uma verificação anterior daquele dia. A função foi implementada e implantada no commit c18783c. O escopo completo, os testes e os backups estão no [relatório de validação desta rodada](../verification/2026-10-25-web-motion-studio.md). A primeira versão aceita o joystick, a cabeça/corpo/boca e sons conhecidos, e pode gravar os alvos gerados pelos movimentos expressivos. Habilidades de modelo são recusadas durante a gravação porque não há confirmação confiável de que terminaram; não se afirma que a espera ou o cancelamento imaginados mais adiante tenham sido implementados. Ainda não há vínculo das reproduções salvas ao controle ou à voz. Não se grava áudio nem vídeo e não se promete uma trajetória espacial exata.

## Escopo definido pelo usuário

- Iniciar a gravação clicando na página Web e operar pelos controles remotos Web existentes e pelo joystick virtual, sem depender do mapeamento de botões do controle físico.
- Incluir avanço, ré e curvas, registrando velocidade, direção e duração correspondentes às operações Web para reproduzi-las depois no tempo.
- Permitir interromper a gravação, nomear e salvar o trecho e, depois, selecioná-lo para reprodução repetida.
- Gravação de sons, movimentos acionados por sons e imitação de voz são etapas independentes futuras; não fazem parte desta implementação.

## Escolha da solução

Recomenda-se gravar as instruções de controle Web que realmente forem autorizadas após as verificações existentes de permissões e estado, junto com o tempo relativo. A reprodução também deve passar pelas mesmas verificações e preservar o controle de equilíbrio e articulações do programa principal.

Outra opção seria coletar os ângulos de todas as articulações e reproduzir diretamente a trajetória articular. Isso pode ser pesquisado mais tarde como uma função independente de demonstração guiada manualmente, mas exige tratar equilíbrio em pé, contato com o chão e torque nas articulações. Não é uma substituição adequada para gravar os comandos Web desta versão.

Esta função repete comandos e ritmo de controle; não garante os mesmos passos, pontos de apoio ou trajetória espacial. A postura inicial, o chão e o deslizamento mudam o movimento real. A interface não deve dizer “retornar pelo mesmo caminho” nem “reproduzir trajetória exata”.

## Fluxo de uso na Web

Adicionar uma área de “Gravação de movimentos” no cartão de controle remoto existente, perto dos botões de ficar em pé, caminhar e sentar; não criar vínculo com os botões do controle físico.

1. O usuário prepara o pato para ficar estável em pé seguindo o fluxo existente. O botão de gravação, por si só, não aciona a ação de ficar em pé, habilitar torque nem começar a caminhar.
2. Ao clicar em “Iniciar gravação”, mostrar o estado vermelho de gravação, o tempo registrado e as opções “Pausar gravação” e “Encerrar gravação”.
3. O usuário opera o joystick Web existente, os modos de cabeça/corpo, abre a boca, emite sons e executa movimentos conhecidos já compatíveis. Calibração, alteração de configurações e troca de modelo na interface não fazem parte do registro de movimentos.
4. Ao pausar, interromper o movimento contínuo e retornar à condição neutra. O tempo de espera pausado não entra no trecho final. Ao retomar, a gravação começa com uma nova operação; o joystick não continua pressionado a partir do estado anterior à pausa.
5. Ao encerrar, interromper o movimento contínuo, pedir um nome e salvar. Se não houver movimento válido, explicar o motivo e não criar uma gravação vazia.
6. Na lista, permitir selecionar um trecho e consultar nome, duração e modelo/funções necessários. Oferecer reprodução 1, 3 ou 5 vezes, uma vez por padrão.
7. Exigir um clique explícito em “Iniciar reprodução”. Mostrar progresso, etapa atual, repetições restantes e “Pausar reprodução”/“Parar reprodução”; a parada de emergência continua visível no topo.

É possível renomear e excluir gravações. A primeira versão não inclui edição, combinação, mudança de velocidade, importação de arquivos nem repetição infinita.

## Conteúdo gravado e condições iniciais

- Registrar eventos de controle Web aceitos pelo serviço e seus tempos em relógio monotônico. Não capturar eventos originais do teclado no navegador nem tratar todo o JSON-RPC como conteúdo reproduzível.
- Registrar, depois de aplicar os limites, velocidade/velocidade angular, intenções de cabeça, corpo e boca dos canais contínuos e os limites de parada. Salvar explicitamente as mudanças de modo, sem depender do modo de joystick que estiver selecionado na página antes da reprodução.
- Movimentos e habilidades devem usar identificadores e ciclos de vida conhecidos; sons devem usar identificadores conhecidos. Nunca gravar nomes de métodos arbitrários, caminhos de arquivo ou programas.
- Levantar, começar a caminhar e sentar são preparações de estado feitas manualmente pelo usuário antes da gravação; a primeira versão não as reproduz como etapas. Se uma operação alterar essas condições, aliviar torque, entrar em calibração ou trocar de modelo, encerrar a gravação/reprodução atual e explicar o motivo.
- Se o conteúdo exigir a política de caminhada, o pato já precisa estar no estado “pronto para caminhar” antes da gravação e da reprodução. Validar em tempo real o estado, o modelo atual e os limites de velocidade; não usar o estado antigo salvo no arquivo como substituto.
- Quando houver um controle físico conectado, aplicar a exclusão mútua do controle Web existente. Se o joystick Web não estiver disponível, não permitir iniciar a gravação Web e explicar por quê.
- Salvar as impressões digitais necessárias do modelo/configuração. Se o modelo relacionado ou a configuração de controle não corresponderem, recusar a reprodução e pedir uma nova gravação, evitando que o mesmo identificador passe a representar outro movimento.

## Limites de pausa, parada e execução

- Ao pausar a reprodução, parar a caminhada, limpar os controles contínuos mantidos de cabeça/corpo/boca e interromper as próximas etapas. A linha do tempo fica na posição atual. Para continuar, o usuário precisa clicar explicitamente e o estado é validado novamente.
- Não presumir que uma habilidade já iniciada, como chute ou cambalhota, foi fisicamente cancelada só porque os comandos pararam. É necessário verificar se o serviço de execução oferece cancelamento. Se não oferecer, uma pausa normal só terá efeito quando a habilidade atual terminar e a interface mostrará “Aguardando o término da habilidade atual”. A parada de emergência sempre usará o caminho de alívio existente.
- “Parar reprodução” cancela as etapas restantes e os ciclos seguintes e interrompe o controle contínuo. Uma parada normal ou de emergência não pode ser apresentada como execução em segundo plano.
- Só pode haver uma sessão de gravação ou reprodução por vez. Durante a reprodução, desabilitar controles normais conflitantes; se houver intervenção manual, encerrar primeiro a reprodução e só então aceitar os novos comandos.
- Trocar de página, sair da área de controle, ocultar a aba, perder foco da janela, desconectar, mudar a posse do controle, entrar em estado anormal ou acionar a parada de emergência encerra a gravação/reprodução. Reconectar não retoma a execução automaticamente.
- O serviço executa a linha do tempo e exige que a Web atual envie um sinal de atividade válido a cada 100 ms. Mais de 500 ms sem sinal deve parar a saída automática. O serviço não pode continuar enviando velocidades indefinidamente para contornar o mecanismo `deadman` existente.
- A reprodução não pode contornar verificações existentes de bateria baixa, falha de servo, estado da IMU ou prontidão do modelo.
- Ao fim de cada ciclo, parar o movimento contínuo, liberar o estado mantido do corpo e fechar a boca. Antes do ciclo seguinte, validar novamente o estado. Não reabilitar o torque automaticamente.

## Limites entre dados e módulos

- Implementar gravação, validação dos arquivos e execução da linha do tempo em módulos independentes. Interagir pela entrada de controle autorizada já existente em `PadOps`; não concentrar uma implementação completa no código Web já extenso nem em `pad_drive.py`.
- Armazenar arquivos em formato de dados versionado: identificador, nome, data de criação, duração válida, requisitos iniciais, impressão digital da configuração e lista de eventos permitidos.
- Salvar no diretório de estado do Studio, sem modificar os movimentos padrão da imagem. Fazer a substituição dos arquivos atomicamente e limitar quantidade, duração, nome, tamanho, número de eventos e faixas de parâmetros.
- Limites da primeira versão: até 60 segundos por trecho, 20 gravações e 5 repetições. Nome de até 32 caracteres; arquivo de até 1 MiB e 6.000 eventos. Rejeitar números não finitos, tempos fora de ordem e eventos desconhecidos. Ao atingir o limite de duração ou eventos, encerrar automaticamente como rascunho pendente de salvamento; se o salvamento falhar, não mostrar sucesso.
- Não gravar vídeo da câmera nem áudio do microfone. O recurso pode ser usado junto com a prévia da câmera, mas cada um gerencia seus próprios recursos.
- Os dados ficam no dispositivo. A Web não é um agendador independente de tarefas robóticas em segundo plano. Um rascunho não salvo não tem garantia de persistência após reiniciar o serviço; a interface deve mostrar claramente “Ainda não salvo”.

## Validação e entrega

Os testes de lógica pura devem cobrir ordem temporal, remoção do tempo pausado, reconstrução dos canais contínuos, retorno ao início ao encerrar ciclos, rejeição de arquivo corrompido/parâmetros fora dos limites, incompatibilidade de configuração e exclusão mútua entre sessões.

Usar um `robotd` falso para verificar as intenções e a ordem realmente enviadas; validar que desconexão, eventos atrasados, intervenção manual, parada de emergência, segundo plano e atualização da página não retomam a execução. Não concluir que a reprodução funcionou apenas porque os botões mudaram de cor.

No navegador, verificar em desktop e em telas estreitas de 320/390 px os fluxos de gravação, salvamento, nomeação, reprodução, pausa, parada, ciclos limitados e exclusão. Confirmar que a área de gravação não prejudica o layout original do controle remoto nem da câmera.

Primeiro, concluir a simulação local e os testes de regressão. A validação do pato real é separada e deve começar com um trecho curto e lento, registrando diferenças de movimento e o comportamento real do cancelamento de habilidades. Testes locais aprovados não equivalem à validação no dispositivo. Não regravar automaticamente a imagem nem implantar a função.

## Próxima etapa: interação por voz

O projeto existente tem inicialização da placa de som, rota de entrada do microfone integrado e reprodução básica dos sons do pato. O Studio ainda não tem gravação do usuário, aprendizado de voz ou ações acionadas por fala, e a captura de áudio do microfone real ainda não foi validada nesta tarefa.

Primeiro, implementar gravação manual e audição para confirmar o caminho do microfone integrado ao alto-falante. Depois, fazer uma experiência de “imitação de papagaio”: gravar uma frase, reproduzi-la com a voz original ou modificada e sincronizar o movimento da boca. Em seguida, pesquisar a associação de palavras ou sons específicos a movimentos salvos, com rejeição de sons desconhecidos, intervalo mínimo entre acionamentos e supressão do eco do alto-falante; testar falsos acionamentos com o ruído dos servos.

“Reproduzir a fala que acabou de ser ouvida” e “clonar uma voz para gerar uma nova fala” são funções diferentes; uma demonstração da primeira não deve ser apresentada como a segunda. O reconhecimento de voz só cria uma solicitação de movimento, que ainda precisa passar pelas mesmas verificações de prontidão e parada. Ouvir uma fala não deve iniciar a caminhada nem contornar a posse do controle.

Referências técnicas para a etapa de voz: [testes oficiais de gravação e reprodução do ALSA](https://wiki.alsa-project.org/wiki/SoundcardTesting) e [exemplo oficial de reconhecimento de palavras-chave do TensorFlow](https://www.tensorflow.org/tutorials/audio/simple_audio). Elas servem apenas para estudar a viabilidade; não comprovam que o pato atual já concluiu captura ou reconhecimento.
