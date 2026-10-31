# Driver oficial do LSM6DSV16X

`lsm6dsv16x_reg.c`, `lsm6dsv16x_reg.h` e `LICENSE` foram copiados sem alterações do repositório oficial da STMicroelectronics, fixado no commit `2808e5cd6b85f91b66758e1dd0faab5f043aba07`. O registro do download original está em `source.json`; o caminho registrado é a origem do arquivo no momento do download, não uma dependência de build.

- Origem do driver: https://github.com/STMicroelectronics/lsm6dsv16x-pid/tree/2808e5cd6b85f91b66758e1dd0faab5f043aba07
- Referência da configuração SFLP: https://github.com/STMicroelectronics/STMems_Standard_C_drivers/blob/master/lsm6dsv16x_STdC/examples/lsm6dsv16x_sensor_fusion.c

A configuração SPI específica da placa está em `Core/Src/board.c`; a amostragem, análise do FIFO e máquina de estados de recuperação ficam em `Core/Src/imu.c`. Os avisos de copyright do driver e a licença BSD-3-Clause foram preservados.

Este projeto usa acelerômetro em ±4 g e giroscópio em ±500 dps; acelerômetro, giroscópio, FIFO e SFLP operam a 120 Hz. Essa é uma taxa padrão suportada pelo componente e fornece uma orientação recente ao controlador de 50 Hz; não é a taxa de 30 Hz copiada diretamente do exemplo. Na primeira depuração em placa real, os filtros padrão da ST foram mantidos, sem adicionar filtragem passa-baixa de software sem medições.

Os registros de giroscópio e quaternion do FIFO recebem timestamps separados; não se presume que sejam consecutivos. Cada ciclo consome no máximo 16 registros e o FIFO é consultado a cada 1 ms. Se algum tipo de registro necessário não for atualizado por mais de 100 ms, `ready` é revogado; a configuração é refeita automaticamente após 1 s. Na inicialização, os primeiros dados podem levar até 1,5 s. É normal que os valores se repitam enquanto o componente está parado; só há congelamento quando não chegam novos registros do FIFO. Falhas SPI, overflow do FIFO, ID incorreto do componente e timeout do reset de software podem ser diagnosticados e novamente tentados.

O quaternion usa os valores de ponto flutuante half precision x/y/z do SFLP. `w` é calculado como a raiz quadrada não negativa, conforme o exemplo oficial e o contrato do controlador; não é aplicada uma segunda rotação de montagem. Registros com NaN/Inf ou `x²+y²+z² > 1.02` são rejeitados. Pequenos excessos causados pelo arredondamento half precision são aceitos e normalizados pelo controlador. Se uma orientação unitária válida lida do FIFO tiver os três componentes exatamente zero positivo, x é codificado como zero negativo IEEE-754 `0x8000` (o valor matemático continua sendo zero). Isso impede que o controlador confunda uma orientação válida com o marcador de seis bytes zero que significa “ainda não pronto”. Antes dos primeiros dados, durante timeout ou após uma falha, a saída continua totalmente zerada.

Atualmente, o módulo passou testes de simulação de registradores/FIFO no computador. Ainda não foi conectado a uma placa real para validar configuração do sensor, ruído, orientação de montagem, temporização ou deriva térmica.

Cada chamada de `imu_get_snapshot()` também consulta `board_millis()` para verificar a idade da amostra de forma independente. Mesmo que o tráfego intenso do barramento adie temporariamente a consulta de aquisição, dados com mais de 100 ms retornam `ready=0`, `error=STALE` e gyro/quaternion zerados. Nesse caso, `configured` continua indicando que os registradores foram configurados; contadores de diagnóstico e timestamps não mudam. A recuperação é executada na próxima chamada de `imu_poll()`.
