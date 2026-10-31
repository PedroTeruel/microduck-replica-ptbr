# Origem do projeto de treinamento e manutenção

Este é um diretório comum de código-fonte, distribuído junto com `microduck-replica`; não é um submódulo Git. O trabalho futuro de treinamento HD1910 será mantido aqui. A branch HD1910 original de `fanhao375/microduck_rl` permanece como referência histórica.

## Versão importada

Em 24/09/2026, foi importado um snapshot completo e rastreado do código-fonte na versão fixa abaixo:

- Origem: [fanhao375/microduck_rl @ d9e1926](https://github.com/fanhao375/microduck_rl/tree/d9e1926c5220a0eb79fa5aab9df7b336f8e9a226)
- Commit completo: `d9e1926c5220a0eb79fa5aab9df7b336f8e9a226`
- Base upstream de Pollen Robotics: `d424a0c899f6b33cbd3daeb279913134349c0b63`; foram adicionados acima dela a tarefa HD1910, a referência aos parâmetros M6, a adaptação da inicialização e testes.
- Método de importação: snapshot de código por `git archive`; não inclui `.git`, ambiente virtual, logs de treinamento ou checkpoints.
- O README original foi preservado em [README.upstream.md](README.upstream.md). A migração ajustou as instruções deste diretório e os links de entrada, corrigiu a raiz de empacotamento do HF Jobs para incluir somente o projeto de treinamento e adicionou um teste de regressão do empacotamento local. A lógica de treinamento/atuador, o lock de dependências, as configurações, os testes existentes e os assets geométricos correspondem à versão importada.

A geometria Microduck, massa, inércia e convenções das articulações deste snapshot vêm do projeto de treinamento; não representam medições concluídas do robô físico com servos Feetech.

## Autoria e licenças

| Conteúdo | Origem | Licença |
|---|---|---|
| Mecanismo de treinamento, tarefas originais, ferramentas e documentação | [Pollen Robotics / microduck_rl](https://github.com/pollen-robotics/microduck_rl) | [Apache-2.0](LICENSE) |
| Modelo 3D e malhas Microduck | Mesmo upstream | O README upstream declara CC BY-SA-NC; este repositório preserva a atribuição e as condições de uso não comercial e compartilhamento pela mesma licença conforme CC BY-NC-SA 4.0. Consulte [NOTICE](../../NOTICE.md#licença) |
| Parâmetros de dinâmica do servo `1910_m6.json` e referência de configuração | [LuwuDynamics / xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl) | Cópia de [Apache-2.0](src/mjlab_microduck/robot/hd1910/LICENSE) |
| Modelo de atuador BAM e biblioteca de identificação, instalados como dependência | [Rhoban / BAM](https://github.com/Rhoban/bam) | Apache-2.0; lock fixado em `62bd8ce12154340be97e06f7f41a0ca8f116d967` |
| Tarefa HD1910, adaptação da inicialização de estado, testes correspondentes e documentação criada neste diretório | Este projeto de réplica | Apache-2.0 |

A licença CC da documentação geral da raiz não se aplica à documentação Apache deste diretório. A licença do modelo 3D permanece separada; as bibliotecas dependentes continuam sob suas próprias licenças.

## Origem dos parâmetros

- Commit fixo da LuwuDynamics: `326d77a1122870bdefa2c36403937502c958e69c`
- Caminho original: `src/mjlab_microduck/robot/xgoduck/params/1910_m6.json`
- Caminho neste repositório: [`src/mjlab_microduck/robot/hd1910/1910_m6.json`](src/mjlab_microduck/robot/hd1910/1910_m6.json)
- SHA-256 do arquivo original: `ef2d51adfb1cc0831b9b02ca19aa9176fceecdf725148d084378d7d9a64afceb`

Os parâmetros foram preservados do arquivo original e não são resultado de identificação feita por este projeto. Consulte [Origem dos parâmetros](src/mjlab_microduck/robot/hd1910/README.md) para as referências e limites de configuração. Se você treinar suas próprias políticas com esses parâmetros, mantenha a atribuição ao autor dos parâmetros.
