# Atualização Web, voz local e nova imagem: relatório de entrega

Data: 27/10/2026 (horário de Tóquio). O usuário pediu a implementação da atualização online pela Web e a inclusão da voz local “Sentar/Levantar” na nova imagem; depois confirmou: “Deixe desligado por enquanto; primeiro conclua o software e a imagem localmente”. A conversa livre por voz com IA permaneceu pausada.

**Software, pacote assinado, pacote de entrada inicial e imagem correspondente foram concluídos. Depois, o usuário autorizou o envio e a publicação: o código-fonte em `master`, a imagem Latest 20261027 e a versão de software 2026.10.27 foram publicados. Consulte o [relatório de publicação](2026-10-27-web-updates-publication.md). Não houve implantação no pato desligado nem gravação de cartão; a inicialização de cartões antigos e a validação física da nova imagem ainda dependem de ligar o equipamento.**

## Versão e artefatos

Os arquivos de execução foram congelados em `e382f0741d7dfe4e972605e2843474df7219cade`. Depois, `1b7416e` corrigiu apenas as condições de espera de três testes de regressão existentes no navegador; os arquivos de execução não mudaram. Versão do software: `2026.10.27`. O commit separado da documentação foi registrado no histórico Git e não alterou a origem dos arquivos incluídos no pacote.

Os diretórios locais de entrega na raiz do workspace são `复刻镜像-20261027` e `软件升级包-20261027`. Tamanhos e hashes completos estão em `artifacts/software-updates-20261027/delivery.json`; a imagem, o pacote de atualização e o arquivo da inicialização inicial incluem arquivos SHA256.

| Artefato | SHA256 |
| --- | --- |
| `microduck-replica-20261027.img.xz` | `91ab5550e0f409d634722718a638d6e9615412b779b5d26c0af5c777056d0194` |
| `2026.10.27.software-update.tar` | `b6543c9f3a2ad6477106410dbed9753be9fa37c61b79ea0350767a18229d0e55` |
| `microduck-bootstrap-20261027.tar.gz` | `866f8d49e3097133ab911debda9c4fdc66b9f02b867a789aadfb9793b99b3610` |
| Chave pública de publicação | `0878853a92b10c9196c5b63e02087664923c576e6bc2e064d3bbdcc1be056bf5` |
| Manifesto dos recursos de voz | `2639f40cd196c7f64fd5adef2220c135b82186c5ebe22ff527c57fde7ae66b9c` |

A imagem tem 741.604.104 bytes, o pacote de atualização Web tem 5.683.200 bytes e o arquivo de inicialização inicial tem 57.811.043 bytes. Esse arquivo inicial contém somente o código-fonte público congelado, o mecanismo ARM64 original, chave pública, pacote assinado, recursos ASR, licenças e instruções de operação. Não é o pacote para envio pela Web e não foi executado no pato. O envio normal pela página usa um arquivo `.software-update.tar` separado. A nova imagem já inclui o mesmo bootstrap e não precisa ser inicializada duas vezes.

## Implementação e limites

- A parte superior de Configurações ganhou a área “Atualização de software”: versão, verificação, download, envio offline, validação, instalação, estado da tarefa, reconexão com conferência e reversão. Mantém login, Host/Origin/CSRF e `no-store`; a lista permitida não aceita fonte, caminho ou shell arbitrários.
- Um pacote de componentes de software assinado gerencia Studio, helper correspondente e `duck-echo`. O executável, a verificação de saúde, a chave pública, os dados do usuário e os recursos ASR ficam fora da árvore de versões. A lista congelada de arquivos de execução do Git não inclui testes, logs, estado do usuário nem chave privada. O arquivo USTAR externo valida estritamente quatro arquivos; o mecanismo original valida o `tar.zst` interno.
- Foi usado o `updaterd` ARM64 real da imagem original, versão 0.15.1, código-fonte `1fa84386f07884e27866411bc1ba166977bced95`, IPC API 37 e opções `profile/from_dir/dry_run`. Não foi criado outro mecanismo transacional de troca. `auto_apply=off`; não há verificação periódica nem instalação automática.
- Um controlador independente com privilégios de root oferece verbos fixos via IPC, com validação das permissões do peer. A fonte de publicação é fixa: os lançamentos oficiais `microduck-software-v` de `fanhao375/microduck-replica`. Ausência de lançamento, erro de rede, download concluído e instalação concluída são apresentados como estados separados. O primeiro lançamento de software `2026.10.27` já foi publicado; durante a verificação, era normal não encontrar uma versão de imagem superior.
- O mecanismo original também tentava reiniciar `updaterd`/`btd` com atraso. A fronteira estável do serviço os recusa e permite somente os serviços Web e de voz. A compilação offline não modifica serviços do host; a verificação de saúde usa o caminho absoluto real de `systemctl`.
- Antes da troca, são verificadas leituras novas do barramento, postura em pé real, política parada, 15 articulações, velocidade, horário, alimentação, espaço e ocupação por gravação/reprodução/calibração/servos/áudio. Um marcador e um bloqueio entre processos protegem ao mesmo tempo a Web e o R3 físico, cancelam ASR atrasado e evitam uma corrida entre a pré-verificação e o comando para sentar/levantar. A parada de emergência, o alívio de torque e o desligamento da escuta são preservados.
- A inicialização inicial confere os arquivos drop-in antigos do serviço, substitui a configuração conhecida `10-image.conf` e recusa configurações de inicialização personalizadas desconhecidas. O estado antigo é copiado para uma área temporária privada após conferir UID fixo, descritores de diretório sem seguir links, tipo, número de links e tamanho; depois é movido atomicamente para um destino vazio. Não é feito `chown` recursivo em uma árvore controlável pelo usuário. Um estado novo já existente e não vazio é preservado; em caso de erro, o serviço e a entrada do programa originais são restaurados.
- O Studio executa como usuário comum, com diretórios externos explícitos para estado e logs; a árvore do programa pertence a root e não permite escrita. A voz usa por padrão `actions/toggle/duck`, não começa escutando na inicialização e declara explicitamente o caminho ASR compartilhado, a preparação do microfone para R3 e as permissões de áudio/entrada.

## Validação executada

| Verificação | Resultado e escopo |
| --- | --- |
| Regressão completa não relacionada ao navegador no Studio | `STUDIO_E2E=0 py -3.13 -I run_tests.py`: 1.201 testes, 268,296 s, OK; 75 ignorados. A thread de estado de voz AF_UNIX do Windows emitiu avisos ambientais conhecidos; não se afirma que o caminho de áudio nativo do Windows tenha sido aprovado. |
| Voz local | 155 testes aprovados, 18 ignorados; mais 12 verificações direcionadas no WSL para `flock` real, cancelamento de ASR atrasado e casos relacionados. |
| Atualizador Linux | 18 testes da revisão independente de qualidade, incluindo autenticação/log com UID 65534, rejeição de links simbólicos e de corrida na migração. |
| Lado da imagem | 128 testes aprovados em 49,590 s, incluindo hash inválido/caminho desconhecido, entrada completa dos componentes, bootstrap com assinatura compartilhada e garantia de que uma falha não seja registrada como sucesso. |
| Atualizador ARM original/QEMU | 10 verificações reais: instalação inicial assinada, simulação, rejeição de hash/manifesto/assinatura incorretos, troca 27→28, reversão manual, reversão automática após falha de saúde, recuperação após matar o mecanismo depois da troca persistente e escopo de serviço. Nenhum comando de movimento foi enviado ao `robotd` real. |
| Edge real final | Studio/controlador real em `e382f07`; um teste passou em 17,394 s. Layouts de 1440/390/320 px; ausência de lançamento; download condicionado a o robô estar parado; validação, instalação, atualização da página da tarefa, reversão, envio, pacote inválido e recusa de campos extras de root; console sem erros. O pré-teste do mecanismo/dispositivo era um substituto de teste explícito; o mecanismo original teve testes reais separados, sem chamar o substituto de atualização em robô real. |
| Revisão independente da especificação | 503b7cf aprovado: 9 verificações do controlador e 4 de voz; problema P2 de exclusão mútua com R3 encerrado. |
| Revisão independente de qualidade | `e382f074` aprovado: encerrados os problemas de estado/log externo e migração sem seguir links; nenhum achado P1/P2 restante. |
| Python ARM real da imagem | Leitura somente da imagem: Python 3.13.5/ARM carregou o modelo chinês do Vosk com sucesso e o silêncio não foi reconhecido. O Python ARM iniciou no QEMU com UID 65534; a árvore do Studio não permitia escrita, `healthz` funcionou e os diretórios externos de estado/log permitiam escrita. Todos os endpoints do robô estavam desligados. |

Uma execução anterior da suíte completa com casos antigos de navegador teve 1.200 testes, 3 falhas e 5 ignorados. A comparação com o baseline `18cd3` identificou corridas de sincronização nos testes: o filtro já havia fixado o valor da bateria antes da inicialização do Edge, e o fechamento do servo ocorria antes de o registro assíncrono do teste terminar. `1b7416e` corrigiu apenas a sincronização dos testes, sem mudar o produto nem enfraquecer as asserções. Os três testes falhos passaram ao serem repetidos, em 35,020 s; depois, passou a regressão completa não relacionada ao navegador, com 1.201 testes. A suíte antiga inteira de navegador não foi executada novamente.

Relatórios em `artifacts/software-updates-20261027`: `studio-unit-regression.log`, `image-tests.log`, `engine-acceptance.log`, `browser-final/browser.json` e capturas de tela, `image-verification.json`, `native-voice-check.json`, `unprivileged-startup.json`, `build-image.log`, `verify-image.log` e `delivery.json`.

## Compilação da imagem e validação somente para leitura

Foram mantidos a imagem-base e o payload de execução já verificados; o modelo de marcha não foi trocado:

- SHA256 da imagem-base: `652dd54e70f49fd3633058d5ed9bbb2f63b435648da2346dfbfa60fcaa4c5bcc`.
- SHA256 do payload: `370f64af5c690eeebab429f4c59d9c5d00883b5cf1e7f0d0e2c18d4afe45998d`.
- SHA256 do `robotd`: `edf182edb7bf11aeeeedfdab98170ab2ec48a9ec18417f9b68c744b0a60c6d16`; origem `0791fcd44f71c705dc8bb0fbcde405593b52d19b`.
- SHA256 do `updaterd` original: `d5f9086bae5c2ec10ba75fc2d41c27578236a12d9a6364bffa8d9315fda97fa6`.
- SHA256 do ZIP Vosk small-cn 0.22: `3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba`; inclui 11 wheels ARM64/cp313, 304 arquivos de recursos e 80.414.834 bytes. O modelo usa Apache-2.0 e as licenças das dependências foram mantidas.

O pacote assinado foi compilado a partir do arquivo Git congelado; o script WSL de imagem existente chamou o mesmo bootstrap compartilhado. O arquivo xz entregue foi extraído de forma independente; hash, xz, partições e `e2fsck` foram verificados somente para leitura; a imagem foi montada com `ro,noload` e depois desmontada.

- Os hashes dos 39 arquivos de execução/modelo e as 9 referências de modelo coincidiram; os 15 servos permaneceram sem calibração e o padrão de comissionamento da IMU estava correto.
- Os hashes dos 350 arquivos de execução de software coincidiram individualmente; o link simbólico `current`, a propriedade root sem permissão de escrita e a origem `e382f07` corresponderam ao pacote.
- O atualizador independente, chave pública e configurações estavam corretos; aplicação automática desativada, serviços estáveis, permissões de State/Logs e substituição `90` conferidas; sintaxe do `sudoers` aprovada.
- Os hashes dos 304 recursos de voz coincidiram; preparação do microfone R3, caminho ASR explícito, padrão `actions/toggle/duck` e carregamento do modelo ARM real foram verificados.
- Não havia Wi-Fi pessoal, chaves SSH de host/desenvolvedor, ID de máquina, dados de usuário da Web, chave de IA ou chave privada de publicação. A câmera continua usando a fonte de teste.

A chave privada de publicação ficou em um diretório privado da máquina de compilação. Git, imagem e pacote de entrega contêm somente a chave pública. Os artefatos foram copiados para um diretório Windows e seus tamanhos/hashes foram conferidos de novo. Depois, conforme instrução do usuário, o código foi enviado e a imagem e os anexos de software foram publicados. Consulte o [relatório de publicação](2026-10-27-web-updates-publication.md) para o estado público e a verificação anônima de download.

## Validação física ainda pendente

O pato estava desligado. Não foram executados no equipamento a inicialização inicial de um cartão antigo, atualização Web real, reversão, recuperação após corte físico de energia, testes acústicos com uma pessoa nem o primeiro uso completo da nova imagem. O usuário já havia confirmado o sucesso de comandos de sentar/levantar; ainda é necessário validar a combinação desta imagem no robô. Testes de matar/reiniciar no QEMU não substituem a validação após perda real de alimentação.

Ainda é necessário corrigir o problema de acompanhamento do ritmo musical com movimentos de cabeça/corpo. A conversa livre por voz com IA não foi conectada e essas funções não são declaradas concluídas nesta versão. As instruções de uso estão em [Atualização de software e voz](../../SoftwareAtualização e 语音Instruções de uso-20261027.md).
