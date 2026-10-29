# Publicação da imagem 20261027 e do pacote de software

**Data:** 27/10/2026 (horário de Tóquio). Depois de receber a entrega local e conferir o código do IMU, o usuário solicitou explicitamente: “envie, use a versão mais recente e faça uma imagem”. Essa autorização abrangia enviar o código-fonte e publicar o pacote de software e a imagem correspondentes; não abrangia gravar cartões nem colocar em movimento o pato desligado.

**Publicação concluída:** o código-fonte foi enviado ao master; a imagem 20261027 foi definida como Latest; o software 2026.10.27 foi publicado separadamente. Os tamanhos no servidor e os SHA256 dos 8 anexos da imagem e dos 10 anexos do software coincidem. Foram verificadas a disponibilidade pública anônima, o download do pacote de software, a assinatura e o arquivo de validação da imagem/cabeçalho XZ. Ambos os releases estão com `draft=false` e `prerelease=false`; a validação física desta versão continua pendente.

## Versão e origem

- Código-fonte integrado enviado: `762b0d44b784104aeb73c7b6bad10a25713daa44`; preservados os 16 novos documentos que já estavam no remoto. Somente o README teve conflito: manteve-se a apresentação mais recente do projeto e acrescentou-se a entrada do novo software.
- Origem de execução do software/imagem: `e382f0741d7dfe4e972605e2843474df7219cade`. Studio, duck-echo, updater e scripts de instalação da imagem correspondem a esse commit em cada caminho; não foi necessário reconstruir uma imagem com o mesmo conteúdo.
- As duas tags de release são tags anotadas e apontam, após desreferenciar, para e382f074; o commit documental posterior não foi apresentado indevidamente como origem da imagem.
- A existência pública do código runtime `0791fcd44f71c705dc8bb0fbcde405593b52d19b` foi confirmada pela API de commits do GitHub. robotd, modelo de marcha e suporte ao IMU no barramento com ID 200 continuam na versão 20261023c.
- As alterações locais de receitas de treinamento não entraram nesta publicação. `software/training` e `software/training-studio` são iguais ao origin/master anterior à publicação. O ramo local original e os documentos não rastreados do usuário foram preservados.

## Páginas de release e arquivos

| Release | Página | Anexos e verificações |
| --- | --- | --- |
| Imagem 20261027 | [Página do release da imagem](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261027) | 8 arquivos: xz, SHA256, manifesto, licença, modelos, terceiros, instruções de voz e README. Todos os resumos do servidor coincidem; a consulta confirmou a tag Latest. |
| Software 2026.10.27 | [Página do release do software](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.27) | 10 arquivos: pacote assinado/checksum, manifesto/assinatura, pacote de configuração inicial/checksum, chave pública, licença Apache, instruções de voz e README. Todos os resumos do servidor coincidem. |

| Artefato principal | Bytes | SHA256 |
| --- | --- | --- |
| `microduck-replica-20261027.img.xz` | 741604104 | `91ab5550e0f409d634722718a638d6e9615412b779b5d26c0af5c777056d0194` |
| `2026.10.27.software-update.tar` | 5683200 | `b6543c9f3a2ad6477106410dbed9753be9fa37c61b79ea0350767a18229d0e55` |
| `microduck-bootstrap-20261027.tar.gz` | 57811043 | `866f8d49e3097133ab911debda9c4fdc66b9f02b867a789aadfb9793b99b3610` |

Todos os artefatos foram enviados individualmente, sem usar curingas do diretório de trabalho. A chave privada de publicação não está nos anexos; somente a chave pública está no Git. O GitHub normalizou automaticamente o arquivo de instruções de voz em chinês para default.txt. Ainda no rascunho, o hash do conteúdo foi conferido e o arquivo foi renomeado para ASCII explícito `microduck-software-20261027-voice.txt`; depois foi verificado novamente e publicado.

## Conferências da publicação

- Os tamanhos e hashes dos arquivos da entrega local foram verificados novamente; a assinatura dos pacotes interno/externo e os 319 arquivos do manifesto do pacote inicial também passaram.
- A validação local completa e a revisão independente estão em [Validação da criação](2026-10-27-web-updates.md). A publicação mesclada alterou somente documentação; os arquivos em execução correspondem à origem congelada já validada. Após a mesclagem, passaram mais 18 verificações Linux do atualizador e 5 verificações HTTP de atualização do Studio.
- Foram verificados individualmente os destinos das duas tags do GitHub, o estado uploaded dos 10 anexos do software, seus tamanhos e SHA256. As URLs dos ativos em rascunho continham caminhos temporários untagged; somente depois da publicação foi confirmada a URL estável de download pela tag.
- Todos os 18 anexos e a origem das duas tags foram confirmados; Latest aponta para a imagem 20261027. O cliente público anônimo do diretório distingue corretamente imagem de software, reconhece 2026.10.27 e baixa o pacote de software de 5.683.200 bytes; hash e as duas assinaturas minisign passaram. O arquivo SHA256 da imagem pública coincide com o local e a leitura Range devolveu o cabeçalho XZ correto.
- O snapshot de validação pública está em [release-assets.json](2026-10-27-release-assets.json). A integridade da imagem foi validada em conjunto pela extração independente e verificação arquivo a arquivo somente de leitura e pelo resumo do arquivo completo no servidor do GitHub; a aceitação física é registrada separadamente.

As evidências estão em `artifacts/software-updates-20261027`: publication-assets.json, publication-verification.json nas etapas de rascunho/público e os arquivos de release. O valor `local_only=true` em delivery.json foi preservado como registro histórico da primeira entrega local e não substitui o estado desta publicação pública.

## Limites da validação física

O pato está desligado. Nesta rodada não houve instalação por SSH, gravação de cartão, movimento do robô nem requisição à nuvem. Ainda aguardam validação: configuração inicial/atualização/retorno no cartão antigo; primeiro uso no cartão novo; desligamento real da alimentação e teste acústico com pessoa. O título e o corpo da página de release deixam isso explícito. O release de software não é aplicado automaticamente por padrão; a imagem e o pacote de componentes são identificados separadamente.

O movimento real da cabeça e do corpo com música ainda não foi corrigido e a conversa livre por voz com IA não está conectada. O sucesso físico anterior de sentar/levantar e gravar/reproduzir não substitui a validação física desta imagem completa. O primeiro parágrafo das instruções do release mantém os limites de reprodução gratuita, pessoal e não comercial e de licença dos modelos.
