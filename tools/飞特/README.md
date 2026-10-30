# Software de depuração de servos Feetech

Configure IDs, altere parâmetros e use o controle deslizante para testar o movimento dos servos. Este diretório contém o software de depuração para Windows e uma cópia de um driver antigo; também oferece links para drivers oficiais, um assistente serial e os documentos mais recentes.

| Arquivo | Função | Versão | Tamanho |
|---|---|---|---|
| [FD1.9.8.5(250729).7z](FD1.9.8.5%28250729%29.7z) | **Software de depuração FD**: configurar IDs, habilitar proteção contra sobrecorrente/sobretensão e testar o servo com o controle deslizante | 1.9.8.5 (2025-07-29), com opção de interface em inglês | 167 KB |
| [CH340_URT.rar](CH340_URT.rar) | **Cópia de driver antigo CH340**, para o conversor correspondente; para o CH343 do URT-2, consulte o link oficial abaixo | — | 224 KB |

## Instalação e uso

```text
1  Conecte o URT-2 → no Gerenciador de Dispositivos, abra “Portas” e anote USB-Enhanced-SERIAL CH343 (COMx).
   Se não aparecer, confira o modelo do chip conversor e selecione o driver correspondente nos links oficiais abaixo.
2  Extraia FD1.9.8.5(250729).7z e execute o programa diretamente; não é necessário instalar.
3  No FD, selecione a porta COM → baud rate 1000000 → clique em “Open” → clique em “Search”.
```

Se o servo for encontrado, a comunicação está funcionando. **Como fazer a fiação, alimentar o servo, configurar IDs, alterar parâmetros e consultar a tabela de IDs** está explicado passo a passo em [Registro de depuração · configuração dos servos](../../调试记录.md#ServoConfiguração--拿到货一步一步做).

## Drivers e assistente serial

| Link oficial | Uso |
|---|---|
| [CH343SER.ZIP](https://gitee.com/ftservo/fddebug/blob/master/CH343SER.ZIP) | Conversores CH343 como o URT-2; não é preciso instalar separadamente se o sistema já tiver reconhecido o dispositivo |
| [CH341SER.ZIP](https://gitee.com/ftservo/fddebug/blob/master/CH341SER.ZIP) | Conversores com chip CH340 / CH341 |
| [UartAssist.zip](https://gitee.com/ftservo/fddebug/blob/master/UartAssist.zip) | Assistente serial genérico; envia e recebe texto ou dados hexadecimais conforme o protocolo do dispositivo |

Em 2026-10-25, conferimos o repositório oficial: FD 1.9.8.5 ainda aparece como versão estável. Consulte o [repositório oficial Feetech](https://gitee.com/ftservo/fddebug) para versões futuras; protocolo, tabelas de memória e SDK estão no [índice de documentos Feetech](../../docs/飞特资料/README.md).

## Fonte e verificação

Os arquivos foram copiados sem alterações da branch master do repositório oficial Feetech no Gitee, [gitee.com/ftservo/fddebug](https://gitee.com/ftservo/fddebug), em 2026-09-11. **Licença MIT** (o arquivo LICENSE está no mesmo diretório).

```text
sha256
FD1.9.8.5(250729).7z   33b92ac03ff048238bb6455a96aec98e97f6c87a97903ac197406f6d937c7734
CH340_URT.rar          546aaf96a54647f7a3ddd7e21389d64be2d198926c6058d8b19ee90e9eea4e17
```

Se suspeitar que um arquivo está corrompido, compare o resultado de sha256sum com esses valores.

**Por que os arquivos estão no repositório:** o Gitee às vezes exige login para baixar e pode alterar a estrutura dos diretórios. Quem clona o projeto não deveria precisar procurar os arquivos em outro lugar.
**Para atualizar:** obtenha a nova versão no repositório acima, substitua o arquivo, atualize aqui a versão e o hash e atualize a versão em [NOTICE](../../NOTICE.md).

## Bancada web de depuração

O FD só funciona no Windows. Para executar na placa ou visualizar um modelo 3D acompanhando o movimento, use [`../servo-web/`](../servo-web/): execute `python server.py --port COM5`, abra a página no navegador e arraste os controles. A ferramenta também pode exportar todos os registradores de 0 a 90 com um clique.
