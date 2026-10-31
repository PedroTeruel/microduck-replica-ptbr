# Importar modelos de treinamento

Abra “Gerenciamento de modelos” no Studio. Não é necessário regravar a imagem do sistema.

1. No computador de treinamento, localize o diretório exportado na mesma operação de implantação do modelo.
2. Compacte `policy.onnx`, `manifest.json` e `deployment-contract.json` em um arquivo ZIP, tar.gz ou tgz. Se a exportação incluir `deployment-execution.json`, `deployment-runtime.json` ou `model-info.json`, coloque esses arquivos no mesmo diretório. Não inclua registros de treinamento, scripts nem vários modelos no mesmo pacote.
3. Selecione o pacote de implantação, informe opcionalmente um nome de exibição e toque em “Importar modelo”. O pacote pode ter até 64 MiB e, depois de extraído, até 256 MiB.
4. A importação confirma somente que o arquivo foi instalado. Primeiro alivie o torque. Depois, selecione a finalidade no cartão do modelo e toque em “Usar este modelo”. A página só confirma o sucesso quando o programa principal informa o caminho do modelo que está realmente em uso.
5. Para atribuir uma tecla de ação, toque em “Configurar tecla de ação” no cartão do modelo e pressione uma tecla de ação do controle físico, ou selecione-a no menu “Teclas do controle”. É necessária uma confirmação para substituir uma tecla já atribuída. Caminhar continua usando os controles existentes de ficar em pé e andar.

Um arquivo ONNX isolado não contém a finalidade das ações, a ordem das juntas, a postura em pé nem os parâmetros de execução; por isso, não é possível tratá-lo diretamente como um pacote compatível. O Studio verifica a identidade do arquivo e o contrato e, em seguida, chama `robotd validate-policy` para fazer uma verificação prévia do ONNX localmente. Se esse verificador não estiver disponível, a importação é recusada: extrair o arquivo com sucesso não comprova compatibilidade.

A postura de base atual do programa e os parâmetros P dos servos são definidos na inicialização. Um modelo com postura de base, parâmetros P ou ordem das juntas diferentes não pode ser ativado diretamente durante a execução. A página explica o motivo; primeiro, conclua as adaptações necessárias à implantação.

## Relação entre modelos, ações e teclas

- **Instalado:** o arquivo do modelo está na biblioteca. **Selecionado para uso:** o modelo foi escolhido para aquela finalidade. **Em execução:** o programa principal está executando esse modelo.
- As teclas são associadas a ações, e cada ação usa o modelo selecionado para ela. É possível atribuir ações às teclas A, X, LB, RB e à cruz de direção. Caminhar e ficar em pé separadamente não são ações comuns atribuíveis às teclas.
- Para registrar uma tecla física, confirme que o torque está aliviado, que as cinco teclas estão configuradas e que a ação é comum; em seguida, aguarde dois segundos para que a configuração estabilize. Se uma tecla estiver associada a uma ação especial, como levantar diretamente, use o menu suspenso para atribuí-la, evitando que o registro da tecla acione a ação existente.
- **Cancelar associação** remove somente a tecla selecionada. **Restaurar teclas padrão** restaura as ações originais das cinco teclas. Nenhuma dessas opções exclui modelos.
- **Restaurar modelo integrado** seleciona novamente o modelo padrão registrado inicialmente para aquela finalidade. Os modelos importados continuam na biblioteca.
- Os modelos padrão integrados não podem ser excluídos. Um modelo importado que ainda esteja associado a uma finalidade selecionada também não pode ser excluído; selecione outro modelo ou restaure o integrado primeiro.

Os arquivos importados e seus nomes de exibição ficam no diretório de estado do Studio, normalmente `/var/lib/microduck-studio` no robô. Preserve esse diretório ao atualizar o Studio. Os arquivos dos modelos padrão permanecem no local de instalação original. Renomear um modelo altera apenas o nome exibido, não sua identidade.

## Validação de desenvolvimento

`tests/test_models.py` e `tests/test_model_package.py` usam modelos temporários e um programa principal simulado, sem acessar os servos. `tests/test_models_e2e.py` usa HTTP real, leitura de pacotes de implantação, a biblioteca de modelos e o Edge sem interface gráfica; o verificador e a interface de execução são substituídos explicitamente por implementações locais de teste. Esses testes validam o fluxo de software, mas não substituem a validação dos movimentos do modelo no hardware real.
