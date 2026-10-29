# software · Software

Este diretório preserva os modelos de simulação usados no treinamento. Eles não são a fonte das peças físicas mais recentes; os arquivos CAD são mantidos em [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad).

## Visão geral

| Software | Função | Local | Licença |
|---|---|---|---|
| **Imagem da réplica** | Sistema completo para gravar no cartão: programa principal, modelos, Studio, primeiro boot e rede | [`image/`](image/) | Scripts Apache-2.0; componentes da imagem mantêm suas licenças |
| **Microduck Studio** | Painel web no robô: estado, torque, calibração, IMU, controle e logs | [`studio/`](studio/) | Apache-2.0 |
| **Atualização web** | Pacotes assinados, instalação, envio offline e reversão | [`updater/`](updater/) | Apache-2.0 |
| **Voz local** | Escuta R3, comandos em chinês e sons do robô | [`duck-echo/`](duck-echo/) | Código Apache-2.0; modelos e dependências mantêm suas licenças |
| **Modelos de marcha e movimentos** | Caminhar, sentar, levantar, abaixar a cabeça, cambalhota e patinação | Imagem da réplica | Licença pessoal não comercial do autor |
| **Projeto de treinamento** | Treinamento de simulação HD-1910 | [`training/`](training/) | Código Apache-2.0; malhas 3D CC BY-NC-SA |
| **Microduck Training Studio** | Experimentos web, curvas, avaliação e exportação | [`training-studio/`](training-studio/README.md) | Apache-2.0 e licenças próprias das dependências |

Para ferramentas de servos, IMU e análise de marcha, consulte o [índice de ferramentas](../tools/README.md). Para placas e firmware, consulte os [projetos de hardware](../hardware/README.md).

> Tradução mantida no fork PedroTeruel. A licença aplicável a este documento segue o aviso da pasta e o `NOTICE.md` da raiz.
