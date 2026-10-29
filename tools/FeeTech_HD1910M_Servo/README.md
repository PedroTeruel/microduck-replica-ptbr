# Testador de servo Feetech HD1910M (`feetech-HD1910M-tester`)

Ferramenta de teste serial para o servo Feetech HD-1910M, implementada em Rust com o protocolo FT-SCS. Abrange todos os registradores legíveis e graváveis da tabela de memória oficial: configuração de ID e baud rate, controle PID de posição / velocidade / corrente, torque e controle de força, modos de operação, parâmetros de proteção, limites de ângulo, calibração de zero (0x0B), bloqueio da EEPROM e monitoramento em tempo real.

## Início rápido

```bash
cargo build
./target/debug/hd1910-tester scan      # procura servos (com barra de progresso)
./target/debug/hd1910-tester dump      # lê toda a tabela de memória
./target/debug/hd1910-tester monitor   # monitora o retorno em tempo real
./target/debug/hd1910-tester --help    # mostra todos os comandos
```

## Documentação

O manual completo para iniciantes, com explicação do protocolo, conceitos de Rust e tutoriais experimentais, está em **[TUTORIAL.md](TUTORIAL.md)**.

## Duas folhas de especificações Feetech incluídas

| Arquivo | Descrição | Relação com o robô |
|---|---|---|
| [`HD-1910-C001串型规格书20260907.pdf`](HD-1910-C001串型规格书20260907.pdf) | **Servo usado neste projeto**. 4–8,4 V, redução 1:320, torque de bloqueio 15 kg·cm a 7,4 V. Proteção contra sobretensão em 10 V e subtensão em 4 V; a bateria 2S totalmente carregada fornece 8,4 V e está dentro da faixa. | ✅ Os 15 servos do robô são deste modelo. |
| [`HL-2915-C002串型规格书20260227.pdf`](HL-2915-C002串型规格书20260227.pdf) | Outro servo Feetech. **9–14 V (bateria 3S)**, 22,5 g, redução 1:320. | ⚠️ **Não usado neste projeto; apenas para referência.** A tensão não é compatível com a bateria 2S do robô. Pode servir de comparação para uma futura configuração 3S. |

Os dois arquivos são cópias originais das especificações fornecidas pela Feetech; o conteúdo técnico não foi alterado. **O nome e o telefone / WeChat do contato foram removidos** (o original trazia o contato pessoal de um vendedor, inadequado para publicação em um repositório aberto). A cópia do HD-1910 usa a versão oficial com o telefone fixo da empresa.
Para entrar em contato com a Feetech, use o site [www.feetech.cn](https://www.feetech.cn) ou o telefone comercial 0755-89335266.

Os manuais públicos da Feetech sobre protocolo, tabelas de memória e outros materiais estão em [`docs/飞特资料/`](../../docs/飞特资料/).

## Testes

```bash
cargo test    # testes unitários do protocolo e da tabela de memória (não exigem hardware)
```
