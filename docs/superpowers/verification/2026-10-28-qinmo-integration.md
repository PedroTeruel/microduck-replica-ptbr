# Validação da integração local do IMU Qinmo

Data do relatório: 2026-10-28, fuso Asia/Tokyo. Confirmação final do usuário: detectar automaticamente a placa existente por padrão; oferecer Qinmo como opção na página do IMU; manter a escolha após salvar e reiniciar; ao trocar o tipo, repetir a validação da instalação.

## Fontes congeladas e escopo entregue

- Implementação do Studio/helper: `058963af5a11b2ebfe6d84b4106d1435a22bbbc7`, aprovada em revisão independente de especificação e qualidade. A branch local `studio-dev` avançou de `9ff314c` até essa implementação.
- Runtime: `bdf494ab3fd74898b5159419fbffe87113b4097c`, baseado em `0791fcd44f71c705dc8bb0fbcde405593b52d19b`; aprovado nas revisões independentes de especificação e qualidade. A referência local de desenvolvimento `hd1910-v167-imu-dxl2` avançou até esse commit. A área de trabalho principal original e os logs não rastreados permaneceram intactos.
- Protocolo do fabricante 1.2: commit `4644a9d19e07ac47f2c145c5e064c96683a5450b` da QinmoTech/IMU-DXL. O fabricante não publicou o firmware do microcontrolador; os dispositivos simulados seguem modelos da especificação.
- helper na versão `0.7.2`. A versão oficial exibida pelo robotd continua `0.15.1`; a identidade real desta adaptação é `deployment-info` `0791fcd-feetech-qinmo-control.45`, IPC API 40 e model API 2. Não é possível determinar se a adaptação está instalada apenas com `--version`.

Foram concluídos somente o código local, o programa principal ARM64 e os arquivos de entrada para implantação. Não houve atualização por SSH, gravação de cartão, movimentação do Duck nem alteração de ativos de lançamento público.

## Comportamento implementado

Por padrão, `imu_profile=legacy` corresponde à opção da interface “Detecção automática (placa existente)”. A escolha manual de Qinmo usa a página original do IMU e reconecta de forma controlada ao modo de calibração. As configurações principal e salva preservam os demais campos; os parâmetros originais e a calibração são copiados byte a byte. O cancelamento comum restaura o estado original. Se o processo for cancelado durante a inicialização, ele retorna ao modo de calibração de fábrica, onde é possível fazer uma nova seleção. O controle e a voz R3, quando ativos, ficam suspensos durante a transação e são restaurados ao estado anterior ao final. O alívio dos servos e o caminho global real da tecla de espaço são preservados.

A primeira versão Qinmo aceita somente o barramento Feetech. O PING usa o endereço 56 e comprimento 15; o valor bruto do giroscópio é dividido por 16,4; a orientação é um quaternion explícito, pronto e com unidades; a atualidade do contador e os 15 servos compartilham um limite de 20 ms. A conversão da versão original/I²C foi preservada. A calibração fica vinculada ao protocolo e ao tipo de dados. Metadados desconhecidos, contraditórios ou malformados não são tratados como valores padrão de uma placa antiga. Se o estado mudar durante aquisição, cálculo ou validação, o resultado assíncrono anterior é invalidado, mesmo que o estado depois retorne ao valor original.

As instruções de identificação e as unidades físicas são exibidas separadamente: FT6 e placas personalizadas usam a identidade conhecida; DXL2 genérico confirma apenas um layout compatível; Qinmo exibe o tipo configurado. Isso não significa autenticação automática do fabricante nem detecção automática de qualquer faixa de medição.

## Validação realizada e limitações

| Verificação | Resultado observado e fonte |
| --- | --- |
| Núcleo Rust/parâmetros | 261 aprovados, 111 ignorados; 10 verificações Qinmo aprovadas; 8 verificações existentes de integração do modelo de loop continuam ignoradas |
| Caminho em foco durante a execução | Aprovados os testes de commissioning em PTY para original/DXL2/Qinmo, I²C, somente leitura, diagnóstico de inicialização, instância única e interface do atualizador; detalhes no registro de entrega da execução |
| Comparação isolada do daemon completo | Em `1fb76af`, equivalente à lógica de produção: 299 aprovados, 2 ignorados e 17 falhas. Os nomes dos casos que falharam coincidem com a linha de base antiga fixa; depois disso, o Rust recebeu apenas testes adicionais e uma alteração de texto de diagnóstico. Não se afirma que toda a área de trabalho Rust passou sem falhas |
| Regressão ampla no Windows | 1.229 casos em `f071ed1`, 76 ignorados, 244,110 segundos, resultado OK. Essa rodada antecede correções posteriores de metadados e contexto assíncrono; não representa uma regressão ampla completa do commit final |
| Regressão focada final no Linux | 183 aprovados em `058963a`: 45 Qinmo, 37 backend, 46 commit, 23 redo antigo e 32 calibração helper. As verificações de permissões de arquivo usam Python 3.12/POSIX; o dispositivo de destino continua usando Python 3.13 |
| Navegador real final | 1 caso aprovado no Edge em `058963a`, cobrindo padrão/escolha manual, unidades, estados anormais, cancelamento/restauração, alívio pela tecla de espaço e limpeza dos resultados de aquisição quando a mensagem de erro muda |
| Matriz independente de metadados | 48 de 48 aprovados: metadados nativos ou explícitos no nível superior, desconhecidos ou malformados, protocolo, tipo e tipo configurado rejeitam calibrações antigas e operações pendentes antigas; campos antigos realmente ausentes continuam compatíveis |
| Formato real das configurações de lançamento | 4 casos aprovados com os arquivos principal/salvo reais de 20261027, para os dois tipos; os outros valores analisados e as matrizes aninhadas do modelo permaneceram iguais, e selecionar o mesmo item repetidamente é idempotente byte a byte |
| Verificação após integração | 45 verificações Qinmo aprovadas na branch canônica `studio-dev`; uma verificação POSIX foi ignorada no Windows; hashes da árvore de treinamento e SHA de três documentos privados não rastreados permaneceram inalterados |

Os logs da regressão ampla preservam a exceção de thread de áudio Windows `AF_UNIX` e os avisos de recursos. O processo de teste terminou com código 0; os logs não são descritos como livres de avisos.

## Compilação ARM64

A compilação foi feita a partir do arquivo Git congelado, com Rust 1.99, dependências bloqueadas e alvo `aarch64-unknown-linux-gnu.2.31`. A inspeção do ELF confirmou AArch64 e referência máxima à GLIBC 2.30. Em QEMU independente, o binário ARM64 real passou por validação PTY/IPC em cinco condições: normal, congelado, não pronto, quaternion inválido e checksum inválido. Em todos os casos, as verificações impediram gravações nos motores.

`robotd-qinmo-arm64`: 5.564.672 bytes, SHA256:

```text
febf44e2e5d4e573f4513f25a1ae6480b976c3988dd3d5e7cdfcf84d2a2d5063
```

SHA256 do arquivo de fontes congeladas do runtime: `1ab2540c55fb0e22e688e52f15e55c4b7a7ee70f0d078275b6bc833faa32a0e6`.

## Entrega local e validação física

A área local `artifacts/qinmo-imu-20261027/` guarda o script de compilação, logs originais, fontes da especificação, resultados independentes e a lista de arquivos protegidos. Após congelar o código-fonte, `package-local-adaptation.py` gera os arquivos versionados de manutenção. Os nomes reais, commits de origem e hashes estão em `local-delivery.json`; `files.json` verifica cada arquivo do pacote. O pacote inclui o programa principal e as fontes correspondentes, para manutenção controlada ou compilação de uma imagem futura.

O atualizador assinado do Web cobre Studio/helper/duck-echo e não foi ampliado para o robotd. A pessoa responsável pela manutenção deve instalar o programa principal e o Web/helper correspondentes; não é necessário gravar um novo cartão obrigatoriamente. Após a instalação, selecionar o tipo e calibrar conforme o [guia Web](../../Qinmo-IMU-Web使用.md).

A placa Qinmo real, a estabilidade prolongada no barramento compartilhado, a direção da instalação física e os testes de ficar em pé e caminhar ainda não foram validados. A imagem pública e o pacote de atualização de 20261027 continuam na versão original; uma publicação posterior deve criar uma nova versão e repetir as verificações.
