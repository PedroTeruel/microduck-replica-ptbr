# Validação do catálogo de modelos pré-treinados e dos recursos · 23/10/2026

Nesta rodada, um catálogo de modelos prontos foi adicionado ao Laboratório de Ações e o monitoramento atual de recursos do executor foi incluído nos detalhes do treinamento. Algoritmos de treinamento, políticas do robô e estado dos experimentos existentes não foram alterados.

## Origens dos modelos

- V8 oficial: [manifesto V8](https://huggingface.co/pollen-robotics/microduck-policies/blob/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448/manifest.json), fixado no commit `665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448`. São 10 modelos ONNX para XL330, com observação de 61 dimensões, ação de 14 dimensões e frequência de 50 Hz. O conjunto V8 também mantém modelos antigos separados de caminhada e postura; o padrão para caminhada é VelStand.
- kissqy V167: [manifesto dos modelos arm64](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/firmware/verification/v167/arm64-models.json), fixado no commit `525a215a19397767a073b782f57e97cf53683761`. São 10 modelos HD1910; quatro exigem pés com rodas. A auditoria do autor informa inferência QEMU ARM64 e `hardware_tested=false`; isso não significa que este projeto tenha concluído uma avaliação física.
- Os hashes SHA-256 de todos os 15 fluxos ONNX independentes do upstream correspondem aos originais. Os 10 ONNX contidos no pacote de firmware de 34.138.802 bytes também correspondem. Os pesos não foram copiados para o produto nem os modelos foram executados. Os 161 itens do pacote não incluem PT/PTH, assim como a árvore Git completa; não são feitas afirmações sobre outros pacotes que não foram verificados.
- Os 20 itens têm hardware, autor, versão fixa, SHA, tamanho real em bytes, licença e link para obtenção. Links do pacote e de arquivos individuais estão identificados separadamente; os pesos restritos da comunidade continuam sendo distribuídos pelos respectivos autores.
- A página oferece informações de origem e links para obter os modelos no upstream, mas ainda não integra simulação local, instalação automática nem retomada de treinamento. Experimentos criados por novas receitas começam do zero; as regras existentes para retomar checkpoints continuam em vigor.

## Recursos e interação

- Testes Python no Windows: 93, com 90 aprovados e 3 exclusivos de Linux ignorados; Python no WSL: 93/93 aprovados; Node: 26/26 aprovados.
- Uma revisão independente encontrou falsos avisos de dados desatualizados causados por comparar relógios de máquinas diferentes. No commit `7598562`, o cálculo passou a usar a idade da amostra com relógio monotônico no serviço e o tempo local decorrido após o recebimento no navegador. Os testes de diferença de relógio remoto e suspensão da página passaram. A nova revisão não encontrou problemas P1/P2.
- A validação no navegador passou com o serviço de demonstração isolado e com o serviço real 8094: 20 modelos, filtros por origem/categoria/palavra-chave, links de origem e hashes em todos os detalhes, botão de detalhes em celular, entrada para receitas existentes, amostragem real de recursos, preservação da leitura anterior e indicação de expiração durante a desconexão, recuperação e interrupção da consulta ao sair do experimento. Nenhum erro de página; navegar e selecionar não enviou POST de treinamento.
- O serviço real leu uma RTX 5060 Ti (16.311 MiB de memória total), um i5-14600KF (20 núcleos lógicos), utilização da CPU e memória visível no WSL (total de 16.640.778.240 bytes). A temperatura da GPU variou entre amostras; a temperatura da CPU foi null porque o WSL não expõe esse sensor. Os recursos são do executor como um todo e não foram atribuídos exclusivamente a este treinamento.
- Desktop em 1440 px e celular em 320 px foram verificados; as capturas também foram inspecionadas manualmente. O experimento parado existente `9843544f2296` permaneceu com 0/1000 iterações, 9 segundos e nenhum checkpoint. Outros três experimentos antigos também foram preservados. O serviço só foi atualizado e reiniciado sem tarefas ativas; o ambiente de GPU continuou pronto.

## Evidências

O diretório externo `本地记录/training-action-lab-20261023/` contém `pretrained-source-package-audit.json`, `kiss-model-inventory.json`, referências, manifestos, árvore do repositório upstream e `models-resources-browser.mjs`. `models-resources-validation-stable/` contém o relatório e as capturas do serviço 8094; `models-resources-validation/` contém a validação isolada. `pretrained-ui-mock/` é um teste de limites da interface que usa recursos simulados e não serve como evidência de hardware real.

Nesta rodada não houve treinamento real em GPU, uso de computador em nuvem pago nem movimento do robô. Uma única execução de treinamento sintética foi criada no serviço isolado de demonstração para exibir o painel de recursos.
