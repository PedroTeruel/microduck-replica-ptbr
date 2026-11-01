# Guia de primeiro uso do Microduck V2 — tradução textual

Tradução para português brasileiro dos textos extraíveis do PDF `Microduck上手指南-V2-20261022.pdf` (21 páginas, edição de 22/10/2026; imagem 20261021b). As imagens, capturas de tela, diagramas e ilustrações permanecem no PDF original. Quando houver diferença entre esta edição e o projeto atual, consulte o [guia web atualizado](../../software/image/烧录和第一次使用.md).

## Capa

**MICRODUCK / Guia de primeiro uso V2**  
Feetech HD-1910 · imagem 20261021b · 22/10/2026

Da gravação do cartão até ficar em pé e caminhar. Grave o cartão no computador e abra a página pelo celular. Cada etapa explica o que fazer e como saber se deu certo. O guia contém 20 passos, pode ser impresso e as imagens podem ser compartilhadas na ordem. Os modelos e as demonstrações de interface estão identificados nas páginas. Uso para aprendizado pessoal e réplica não comercial.

## Antes de começar

### 01. Confira o hardware

1. Microduck já montado na versão Feetech HD-1910, com os 15 IDs dos servos configurados, HAT e alimentação conectadas.
2. O guia considera Radxa Zero 3W + microSD. Não use esta imagem Feetech nos servos XL330 originais.
3. Separe um cartão microSD de pelo menos 8 GB (recomendado: 32 GB), leitor, computador e celular.

Antes de ligar: confirme os IDs — perna esquerda 20–24, perna direita 10–14, cabeça/pescoço/bico 30–34 —, fixe a IMU do tronco e confira os cabos. Na primeira operação, consiga apoiar o Microduck e tenha como cortar a alimentação. Quando tudo estiver pronto, baixe a imagem. O guia corresponde à imagem 20261021b; confira a documentação se usar outra placa ou ligação.

### 02. Instale a IMU antes de ligar

Use o módulo de tronco BNO085 ou LSM6DSV16X. Ligue-o conforme o diagrama do projeto ao J5 da HAT ou à interface I²C dos pinos 27/28 do conector de 40 pinos. Faça as ligações sem alimentação e confira VCC, terra, SDA e SCL: os pinos 27/28 são sinais, não constituem sozinhos a ligação completa de quatro fios. A HAT D1 já inclui uma LSM6DSV16X em 0x6A; o módulo externo do tronco deve usar 0x6B.

Na instalação recomendada da LSM6DSV16X, o eixo +Z aponta para a frente do Microduck e o +X aponta para baixo; identifique os eixos pelas marcações do próprio módulo. Na primeira utilização, faça a calibração em pé. Outra orientação de montagem pode ser compensada pela calibração. A IMU de barramento (ID 200) também é compatível; a validação do conjunto com a placa `imu_to_dxl` nesta imagem ainda não foi concluída.

**Conclusão:** módulo preso ao tronco e conectado antes da primeira inicialização.

## Baixar e gravar o cartão

### 03. Baixe esta versão da imagem

No computador, abra a página de lançamento e confirme a versão 20261021b. O QR code também aponta para ela. Expanda **Assets** e baixe o arquivo identificado como “imagem (grave este arquivo, não descompacte)”; não baixe o código-fonte. O nome esperado é `microduck-replica-20261021b.img.xz`, com cerca de 677 MB. Baixe-o no computador; o celular pode ser usado para consultar a página.

**Conclusão:** o arquivo `.img.xz` completo está no computador. Esta edição corresponde a uma versão fixa; não escolha automaticamente a opção “Latest”.

### 04. Grave a imagem no cartão SD

Instale o balenaEtcher pelo site `etcher.balena.io`. Escolha **Flash from file** e selecione o `.img.xz`; em **Select target**, escolha o cartão microSD; clique em **Flash!**. Não é preciso descompactar manualmente. Espere a gravação e a verificação terminarem antes de retirar o cartão. Se o Windows pedir para formatá-lo, clique em **Cancelar**.

**Conclusão:** o programa informa que a gravação terminou e a verificação foi aprovada. A gravação apaga os dados do cartão selecionado; confira o dispositivo e a capacidade para não selecionar um disco errado.

## Primeira inicialização e rede

### 05. Insira o cartão, ligue e aguarde

Com o Microduck desligado, insira o microSD e ligue a placa principal e os servos. Apoie ou estabilize o robô. Na primeira inicialização, o sistema amplia o espaço do cartão, gera um nome e identifica a IMU. Aguarde cerca de 1–3 minutos e procure a rede Wi-Fi `Microduck-xxxx`; `xxxx` são os quatro caracteres exclusivos daquele robô.

**Conclusão:** o celular encontra uma rede cujo nome começa com `Microduck-`. Se ainda não aparecer, espere mais um pouco. Um cartão já configurado para o Wi-Fi doméstico pode conectar-se diretamente a ele, sem criar o ponto de acesso.

### 06. Conecte-se ao ponto de acesso do Microduck

No celular, escolha `Microduck-xxxx` e anote os quatro caracteres finais. A senha é `microduck`. Se o sistema avisar que não há internet, escolha **Manter conexão** ou **Continuar conectado**.

**Conclusão:** o Wi-Fi do celular mostra `Microduck-xxxx` como conectado. A ausência de internet é normal enquanto o celular está ligado diretamente ao robô; `a1b2` nos exemplos é apenas ilustrativo.

### 07. Abra o Studio

Digite o endereço completo `http://10.42.0.1:8000/` na barra de endereço do navegador do celular. Você chegou ao lugar certo quando aparecer o Microduck Studio com o cartão **Conectar ao Wi-Fi**. No Android, se não abrir, desative os dados móveis e confirme que continua conectado ao ponto de acesso do Microduck.

**Conclusão:** a página mostra **Conectar ao Wi-Fi** e a lista de redes. Digite o endereço na barra do navegador, não no campo de busca. Esse IP é usado enquanto estiver conectado ao ponto de acesso; depois, use o endereço do passo 10.

### 08. Escolha o Wi-Fi da sua casa

No cartão **Conectar ao Wi-Fi**, toque no nome da rede doméstica. Digite a senha dessa rede (não a senha do ponto de acesso) e toque em **Conectar**. Aguarde a confirmação antes de prosseguir.

**Conclusão:** aparece a confirmação para desconectar e conectar à sua rede Wi-Fi. Também é possível continuar usando o ponto de acesso do Microduck e ir direto ao passo 11.

### 09. Confirme a troca de rede no celular

Toque na confirmação vermelha para desconectar e conectar à rede doméstica. O Microduck desligará o próprio ponto de acesso; a desconexão do celular é esperada. Nas configurações Wi-Fi do celular, conecte-se manualmente à mesma rede doméstica e volte à aba original do navegador sem fechá-la. Aguarde o redirecionamento automático.

**Conclusão:** o celular e o Microduck estão na mesma rede doméstica. Se a senha estiver errada ou a conexão falhar, o ponto de acesso reaparecerá em até cerca de dois minutos. Reconecte-se e leia a mensagem em vermelho para corrigir a senha.

### 10. Encontre o novo endereço do Microduck

Normalmente a página redireciona sozinha. Se isso não acontecer em 3 minutos, conecte computador e celular ao Wi-Fi doméstico e abra manualmente o endereço correspondente. Troque `xxxx` pelos quatro caracteres anotados; por exemplo, `Microduck-a1b2` corresponde a `duck-a1b2`.

- Windows: `http://duck-xxxx:8000/`
- iPhone ou Mac: `http://duck-xxxx.local:8000/`
- Android ou se os outros endereços falharem: procure o IP de `duck-xxxx` na lista do roteador, por exemplo `http://192.168.1.23:8000/`.

Depois, salve o endereço ou favorito na página **Mais** do Studio.

**Conclusão:** o Studio abre pela rede doméstica. Se houver proxy, tente o IP; no Windows, o nome sem `.local` pode funcionar. Não continue usando `10.42.0.1` após sair do ponto de acesso.

## Calibração e movimento

### 11. Continue a lista de primeiro uso

Na página **Visão geral**, localize a **Lista de primeiro uso** e execute as próximas seis etapas na ordem. **Fazer** abre a operação, **Concluído** registra algo já realizado e **Pular** adia a operação. Antes de continuar, configure sua senha web em **Mais → Senha de acesso**.

1. Ponto zero dos servos.
2. Orientação da IMU.
3. Gravar no programa principal.
4. Configurar o controle.
5. Testar a parada de emergência.
6. Ficar em pé e caminhar.

**Conclusão:** você sabe qual etapa está fazendo e consegue abrir a página correspondente. As etapas podem ser repetidas ou puladas, mas pular não valida a calibração; na primeira montagem, conclua o ponto zero e a calibração da IMU.

### 12. Confira a posição zero dos servos

Na página **Servos**, escolha **Zero** na referência 3D e gire o modelo para examiná-lo. Segure o Microduck e solte as articulações que precisam ser ajustadas. Alinhe pernas, cabeça, pescoço e bico com o modelo, sem pressionar as articulações contra a carcaça. A posição zero é a referência da calibração; a postura em pé após pressionar Start tem as pernas flexionadas e não substitui o zero.

**Conclusão:** você consegue identificar a posição de cada articulação no modelo antes de calibrar os pontos centrais. A ilustração mostra o modelo original com as 15 articulações em zero; o formato da carcaça pode diferir do servo Feetech físico.

### 13. Calibre o ponto central de cada servo

Na página **Servos**, toque em **Começar ajuste dos servos** e aguarde a conexão. O programa principal ficará pausado e o controle físico não poderá comandar os servos. Selecione cada servo, posicione-o em zero e toque em **Calibrar o ponto central deste servo**. Confira o ID mostrado na prévia e confirme; a calibração será mantida. Mova cada servo um pouco para conferir se a direção física corresponde ao modelo 3D; se estiver invertida, alterne ±1 para o servo selecionado e confira novamente.

**Conclusão:** confira o zero e o sentido dos 15 servos. Segure o Microduck antes de **Devolver ao programa principal**, pois essa ação libera os servos. Esta edição descreve a calibração individual validada; a calibração em uma única ação não é requisito.

### 14. Coloque o robô em pé

Na página **IMU**, confirme que existem leituras em tempo real e que a página não informa falha de conexão. Apoie o Microduck com as duas mãos, toque em **Ativar postura em pé**, leia a confirmação e prossiga. Em cerca de 3 segundos, o robô ficará em pé e travará nessa posição. O modo de calibração não corrige o equilíbrio; mantenha as mãos por perto para protegê-lo.

**Conclusão:** a página mostra **Modo de calibração (em pé)**, as articulações estão posicionadas e há leituras atuais da IMU. Se a direção estiver errada, houver travamento ou desequilíbrio, segure o robô, alivie o torque e revise o zero e a orientação.

### 15. Fique imóvel e incline para os quatro lados

Com o robô em pé sobre uma mesa plana, toque em **Iniciar coleta** e não o mova por 3 segundos. Posicione-se atrás dele, olhando na mesma direção. Apoie o tronco e incline cerca de 15° para frente, para trás, para a esquerda e para a direita. Antes de cada inclinação, deixe-o nivelado por meio segundo; incline e segure por 1 segundo. Confirme que as quatro direções foram coletadas e aprovadas. Segure o Microduck e toque em **Desativar** para voltar à terceira etapa da visão geral.

Para a referência de lados, considere a esquerda e a direita do próprio robô; frente é o lado da cabeça e trás é o lado da cauda. O resultado fica registrado no Studio; será aplicado ao programa principal no passo 16.

**Conclusão:** resultado aprovado, orientação anotada e robô desativado, pronto para gravar a configuração. Pular esta etapa reutiliza uma orientação já confirmada ou a orientação padrão da instalação; pular não corrige uma montagem diferente.

### 16. Grave a calibração no programa principal

Segure o Microduck, desative a postura e deixe-o mole ou apoiado; mantenha os servos alimentados. Na terceira etapa da **Visão geral**, confira a preparação, toque em **Revisar o que será gravado** e, após conferir, em **Gravar no programa principal**. Aguarde a reinicialização: normalmente cerca de 20 segundos, podendo levar até 1 minuto. Mantenha a alimentação durante todo o processo.

Antes de gravar, o programa principal deve estar conectado, o modo de calibração deve exibir leituras, os resultados de zero/direção/IMU devem estar prontos e o robô não deve estar caminhando nem segurando a postura em pé. A página informa se faltam etapas; não repita a gravação sem corrigir a causa.

**Conclusão:** gravação aprovada, programa principal reconectado e **Modo de movimento** ativo. Em caso de falha, a página informa a causa e o programa tentará restaurar a calibração e o modo anteriores. Não comece a caminhar antes da confirmação.

### 17. Configure o controle G50 Pro no modo X

Mude a chave traseira do Thunderobot G50 Pro para **X (Xbox)**. Coloque o controle no modo de pareamento Bluetooth conforme as instruções dele; a luz deve piscar rapidamente. No Studio, abra **Controle → Parear controle**, selecione **Controle Xbox**, procure e pareie. Depois pressione alguns botões e confira se o desenho do controle no Studio responde; a mensagem “pareado” sozinha não confirma que os botões funcionam.

**Conclusão:** o controle está conectado e a página reconhece os botões. Na imagem 20261021b, o modo S conectava, mas não transmitia os botões; use X. Para outros controles, siga o procedimento de pareamento do fabricante.

### 18. Teste a parada de emergência

Na página **Controle**, encontre **A parada de emergência do controle está funcionando?** e toque em **Testar parada de emergência** após as verificações. Segure o robô ou coloque-o em um suporte. Pressione Start para deixá-lo em pé; quando a página solicitar, pressione e solte rapidamente Select (botão **Visualizar** no Xbox). Confirme que o torque foi aliviado e aguarde a página confirmar **Parada de emergência testada**. Um robô que já estava mole não conta como teste aprovado.

**Conclusão:** só prossiga quando o Studio confirmar o teste. Não mantenha Select pressionado: após 2 segundos o robô senta, alivia o torque e desliga. Durante o teste, não substitua o botão físico pelo comando web de alívio.

### 19. Fique em pé e caminhe alguns passos

Depois do teste de emergência, coloque o Microduck em piso plano, antiderrapante e com espaço livre. Pressione Start/Menu no controle para ficar em pé; pressione novamente para começar a caminhar. Use o joystick esquerdo para mover e o direito para girar, começando com movimentos curtos. Pelo Studio, abra o cartão de controle remoto da página **Controle** e toque em **Ficar em pé → Começar a caminhar**, depois use os joysticks virtuais.

Start/Menu: ficar em pé e iniciar a caminhada. Joysticks: mover e girar. Select/Visualizar: pressionar e soltar para aliviar o torque.

**Conclusão:** o robô fica estável, avança e gira pouco, e você consegue aliviar o torque pelo controle. Se perder o equilíbrio, segure-o antes de aliviar o torque. No primeiro teste, ainda não experimente cambalhotas, chutes ou outras ações.

## Solução de problemas e suporte

### 20. Informe em qual etapa ocorreu o problema

Segure o Microduck e pare-o com **Aliviar torque** no canto superior direito do Studio ou pressionando Select rapidamente. Em seguida, abra **Mais → Exportar pacote de diagnóstico** e envie o arquivo ao grupo ou a um issue do GitHub, informando o passo atual e anexando uma captura de tela. Para SSH, siga as instruções do cartão **Mais → Acesso remoto por SSH**; o uso diário não exige SSH.

- **Ponto de acesso ausente:** aguarde mais na primeira inicialização; um cartão já configurado pode estar conectado à rede doméstica.
- **Página não abre:** confira o Wi-Fi, o endereço completo e `:8000`; em redes com proxy, tente o endereço IP.
- **Postura ou gravação desativada:** leia o motivo junto ao botão e confira a conexão do barramento, as leituras atuais e o estado sem torque.
- **Controle pareado sem resposta dos botões:** no G50 Pro, use o modo X e confirme os botões no Studio.

**Conclusão:** ao pedir ajuda, informe a versão da imagem, o passo deste guia, o que aconteceu e envie a captura ou o pacote de diagnóstico. Ativar SSH não cria acesso remoto à internet; no uso normal, não é necessário habilitá-lo.
