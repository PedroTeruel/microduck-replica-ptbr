# Lista de compras para montagem — versão Feetech

**Organizada por 机械行者Robo · versão de 2026-10-23**

**[Baixar a planilha Excel completa](装配BOM-机械行者Robo-2026-10-23-带采购链接.xlsx)** · [Peças impressas e CAD](https://github.com/fanhao375/microduck-replica-cad) · [Repositório principal](https://github.com/fanhao375/microduck-replica)

Esta página foi organizada a partir da planilha Excel da mesma versão e contém **33 peças impressas e 23 itens comprados**. Quantidades, materiais, observações, preços e links de compra preservam o conteúdo da tabela original.

**Versão compatível: configuração Feetech HD-1910.** A lista inclui servos Feetech e uma placa de depuração URT2; os servos XL330 e a eletrônica correspondente precisam ser conferidos separadamente. O arquivo Excel original permanece inalterado.

[Ver peças impressas](#pecas-impressas) · [Ver itens comprados](#itens-comprados) · [Instruções da planilha original e itens a conferir](#observacoes-e-conferencia)

<a id="pecas-impressas"></a>

## 1. Peças impressas (33 itens)

Baixe os modelos no [repositório CAD](https://github.com/fanhao375/microduck-replica-cad) e selecione a versão correspondente aos servos. Confira também as instruções de impressão dessa versão; a tabela abaixo reproduz os dados da planilha Excel.

**Preço registrado para o conjunto de peças impressas: ¥139**, correspondente à área mesclada I3:I35 da planilha original; [link de compra](<https://item.taobao.com/item.htm?from=cart&id=1083122166800&mi_id=0000ywbZ5efl4VxxIGb0KHx-3C8BOS37n90MGBh_xmncHd4&skuId=6306393642451&spm=a1z0d.6639537%2F202410.item.d1083122166800.70527484LqKlHG&upStreamPrice=13900>)。

| Nº | Nome | Nome do arquivo original | Material (planilha original) | Quantidade | Observação (planilha original) |
|---|---|---|---|---:|---|
| 1 | Carcaça superior da cabeça | `top_head_shell_CabeçaSuperior壳.stp` | PLA | 1 |  |
| 2 | Carcaça inferior da cabeça | `bottom_head_shell_CabeçaInferior壳.stp` | PLA | 1 |  |
| 3 | Peça facial | `face_part_面部零件.stp` | PLA | 1 |  |
| 4 | Mandíbula inferior | `jaw_Inferior巴.stp` | PLA | 1 |  |
| 5 | Mandíbula flexível | `jaw_soft_软Inferior巴.stp` | PLA | 1 | Recomenda-se TPU flexível |
| 6 | Parte superior flexível do bico | `soft_mouth_top_软嘴顶部.stp` | PLA | 1 | Recomenda-se TPU flexível |
| 7 | Olhos | `noenoeil_眼睛.stp` | PLA | 1 |  |
| 8 | Pescoço | `neck_Pescoço.stp` | PLA | 2 | Recomenda-se liga de alumínio |
| 9 | Inclinação do pescoço | `neck_pitch_Pescoço俯仰.stp` | PLA | 1 |  |
| 10 | Base do tronco | `trunk_base_躯干底座.stp` | PLA | 1 | Recomenda-se liga de alumínio |
| 11 | Carcaça esquerda | `left_shell_Esquerdo壳.stp` | PLA | 1 |  |
| 12 | Carcaça direita | `right_shell_Direito壳.stp` | PLA | 1 |  |
| 13 | Quadril esquerdo | `hip_l_髋部Esquerdo.stp` | PLA | 2 |  |
| 14 | Conversor de yaw para roll | `yaw2roll_偏航转横滚.stp` | PLA | 1 |  |
| 15 | Mecanismo de yaw e roll | `yaw_roll_motion_偏航横滚运动.stp` | PLA | 1 |  |
| 16 | Perna | `leg_Perna.stp` | PLA | 2 |  |
| 17 | Perna superior esquerda | `left_upper_leg_EsquerdoSuperior腿.stp` | PLA | 1 |  |
| 18 | Perna superior direita | `right_upper_leg_DireitoSuperior腿.stp` | PLA | 1 |  |
| 19 | Placa de reforço da perna superior | `upper_leg_rigidity_plate_Superior腿加固板.stp` | PLA | 2 | Recomenda-se liga de alumínio |
| 20 | Pé esquerdo | `foot_left_Esquerdo脚.stp` | PLA | 1 |  |
| 21 | Pé direito | `foot_right_Direito脚.stp` | PLA | 1 |  |
| 22 | Sola esquerda | `sole_left_Esquerdo脚底.stp` | PLA | 1 |  |
| 23 | Sola direita | `sole_right_Direito脚底.stp` | PLA | 1 |  |
| 24 | Tornozelo esquerdo | `ankle_left_脚踝Esquerdo.stp` | PLA | 1 |  |
| 25 | Tornozelo direito | `ankle_right_脚踝Direito.stp` | PLA | 1 |  |
| 26 | Tornozelo esquerdo (alternativa V1) | `ankle_l_v1_脚踝EsquerdoV1.stp` | PLA | 1 |  |
| 27 | Tornozelo direito (alternativa V1) | `ankle_r_v1_脚踝DireitoV1.stp` | PLA | 1 |  |
| 28 | Roda montada | `合体轮胎.stp` | PLA | 4 |  |
| 29 | Palheta do rolete | `roller_blade_滚轮叶片.stp` | PLA | 2 |  |
| 30 | Suporte do motor | `motor_support_电机支架.stp` | PLA | 1 |  |
| 31 | Suporte de alimentação | `power_support_Alimentação支架.stp` | PLA | 1 |  |
| 32 | Trava de PCB tipo banana | `banana_pcb_locker_香蕉形PCB锁扣.stp` | PLA | 1 |  |
| 33 | Rolete com rolamento | `bearing_roll_轴承滚轮.stp` | PLA | 2 | Recomenda-se liga de alumínio |

<a id="itens-comprados"></a>

## 2. Itens comprados (23 itens)

Os preços são exibidos em yuans, conforme registrados na planilha original. Os links de compra são clicáveis; itens sem URL na planilha aparecem como “não preenchido na planilha original”.

| Nº | Nome | Categoria | Quantidade | Preço unitário | Total (planilha original) | Observação (planilha original) | Compra |
|---|---|---|---:|---:|---:|---|---|
| 1 | Placa principal Radxa Zero 3W | Eletrônica | 1 | 309 | 309 |  | [Link de compra](<https://item.taobao.com/item.htm?id=763812025816&last_time=1790655696&mi_id=0000M9KvAKZdKHX6irXd93nZ9S8044VLMp9XHfosSxlXgV0&scm=1007.13982.82927.0&spm=tbpc.mytb_footmark.item.goods&upStreamPrice=88800>) |
| 2 | Cartão TF de 64 GB | Eletrônica | 1 | 60 | 60 |  | Não preenchido na planilha original |
| 3 | Placa HAT robótica para Raspberry Pi | Eletrônica | 1 | 120 | 120 | Compra em grupo pelo GitHub | [Página do projeto](<https://github.com/fanhao375/microduck-replica>) |
| 4 | Placa imu_to_dxl | Eletrônica | 1 | 80 | 80 | Compra em grupo pelo GitHub | [Página do projeto](<https://github.com/fanhao375/microduck-replica>) |
| 5 | Servo Feetech HD1901M | Eletrônica | 15 | 95 | 1425 | Compra em grupo pelo GitHub | [Página do projeto](<https://github.com/fanhao375/microduck-replica>) |
| 6 | Placa de depuração URT2 para servos Feetech | Eletrônica | 1 | 45 | 45 |  | [Link de compra](<https://item.taobao.com/item.htm?spm=a1z0d.6639537%2F202410.item.d575365901461.511774843C6ViG&id=575365901461&xxc=shop&from=cart&skuId=5435424470243&mi_id=0000xzcmwFVCRAh37nhTBqqPxAc4BB-aXBAZs9-SHZnxT_s>) |
| 7 | Bateria NP-F550 | Eletrônica | 1 | 17 | 47 |  | [Link de compra](<https://item.taobao.com/item.htm?adType=orgqzt&from=cart&id=769425140324&mi_id=00009VN3uJH9Mvl1nh6sR6uszyaiYL6FFhvjGBj6PAaJbUg&skuId=5445604550341&spm=a1z0d.6639537%2F202410.item.d769425140324.5a377484k96nZS&upStreamPrice=5500&xxc=qzt_taobaoSearch>) |
| 8 | Cabo adaptador AMP2.0 de duas pontas para os servos Microduck | Eletrônica | 1 | 2 | 2 | Para depuração | [Link de compra](<https://item.taobao.com/item.htm?id=1089647066599&mi_id=0000KqIW0wThzcfg1FqUc6VdYVF2XtZv0Ep94yoyuJ-fYl8&pvid=a7a9bbc1-3e60-439d-90a4-0d4fdd081d6d&scm=1007.54964.509742.0&skuId=6146736860515&spm=pc_detail.30350276.201876.d4.18bd7dd6DvXX58&utparam=%7B%22x_object_type%22%3A%22item%22%2C%22matchType%22%3A%22MAIN_SWING_I2I%22%2C%22item_price%22%3A%222%22%2C%22umpCalled%22%3Atrue%2C%22pc_scene%22%3A%2220001%22%2C%22userId%22%3A1038948925%2C%22ab_info%22%3A%2244964%23509742%23-1%23%22%2C%22tpp_buckets%22%3A%2244964%23509742%23-1%23%22%2C%22aplus_abtest%22%3A%22fe88f406097dbf1addeadb9550070432%22%2C%22isLogin%22%3Atrue%2C%22abid%22%3A%220%22%2C%22pc_pvid%22%3A%22a7a9bbc1-3e60-439d-90a4-0d4fdd081d6d%22%2C%22isWeekLogin%22%3Afalse%2C%22rn%22%3A3%2C%22item_ecpm%22%3A0%2C%22ump_price%22%3A%222%22%2C%22isXClose%22%3Afalse%2C%22x_object_id%22%3A1089647066599%7D&xxc=home_recommend>) |
| 9 | Conector banana de 2,5 mm para PCB, cobre banhado a ouro | Eletrônica | 2 | 1.6 | 3.2 |  | [Link de compra](<https://item.taobao.com/item.htm?from=cart&id=1066300439603&mi_id=0000idrzZ0iZmNePV-H8uLJ0q--7Nuk50iH4KmlQjt7l16Q&skuId=6116801109787&spm=a1z0d.6639537%2F202410.item.d1066300439603.20807484wDo29i&upStreamPrice=160>) |
| 10 | banana PCB | Eletrônica | 1 | 20 | 20 |  | JLCPCB |
| 11 | Módulo de câmera IMX219 | Componente óptico | 1 | 46.8 | 46.8 |  | [Link de compra](<https://detail.tmall.com/item.htm?id=775872575316>) |
| 12 | Módulo ToF VL53L8CX | Eletrônica | 1 | 49.5 | 49.5 |  | [Link de compra](<https://item.taobao.com/item.htm?from=cart&id=737603917521&mi_id=0000svFiYCCRNyTplS2syupd6wPqm_3g253yiYEiJIUzYWg&skuId=5090650052053&spm=a1z0d.6639537%2F202410.item.d737603917521.12a97484LeTNU7&upStreamPrice=4950>) |
| 13 | Alto-falante | Eletrônica | 1 | 3.8 | 3.8 |  | [Link de compra](<https://item.taobao.com/item.htm?ali_refid=a3_430673_1006%3A1300920180%3AH%3AXe0d%2B%2ByvvuheeXXsNbtAzA%3D%3D%3A1fb351596f290624d1f838f6933a4bf9&ali_trackid=318_1fb351596f290624d1f838f6933a4bf9&id=902489608878&loginBonus=1&mi_id=00004qd77Ss-NI_QwEGJk3oQMSCKLeGBjvYFB1womY2KPUQ&mm_sceneid=0_0_1169600180_0_0&priceTId=2100c91217905892639744554e0a2f&skuId=5925223242747&spm=a21n57.sem.item.52&utparam=%7B%22aplus_abtest%22%3A%221116d3394ed69d4d6ae8676cf27ec828%22%7D&xxc=ad_ztc>) |
| 14 | Rolamento 10×15×3 | Peça padronizada | 3 | 2.8 | 8.4 |  | [Link de compra](<https://item.taobao.com/item.htm?id=670727787832>) |
| 15 | Rolamento 16×22×4 | Peça padronizada | 11 | 3.5 | 38.5 |  | [Link de compra](<https://item.taobao.com/item.htm?id=539024647147&skuId=5716548727712>) |
| 16 | Rolamento 6×12×3 | Peça padronizada | 4 | 0.88 | 3.52 | Rolamento para patins | [Link de compra](<https://item.taobao.com/item.htm?abbucket=2&id=963037239628&loginBonus=1&mi_id=00009MRQFjdPW6cwLc4VvA6iVYQgy2Qaevxz6dOGm9D1myw&ns=1&priceTId=213e0a2917895687271465994e0fd6&skuId=6068333830994&spm=a21n57.sem.item.1.40ad3903YwCCZ2&utparam=%7B%22aplus_abtest%22%3A%22633f8c365e71a9c062ec49e542a73279%22%7D&xxc=taobaoSearch>) |
| 17 | Parafuso autoatarraxante de ponta chata M2×5 | Peça padronizada | 1 pacote | 3.05 | 3.05 |  | [Link de compra](<https://detail.tmall.com/item.htm?id=534923831046&mi_id=0000lLHxCRqtZ8_pqc3QGIagm4EgOL8KYhEEg_ZEZdQEaCI&spm=tbpc.boughtlist.suborder_itemtitle.1.c3892e8dY9OLZg>) |
| 18 | Parafuso autoatarraxante de ponta chata M2×6 | Peça padronizada | 1 pacote | 4.05 | 4.05 |  | [Link de compra](<https://detail.tmall.com/item.htm?id=534923831046&mi_id=0000lLHxCRqtZ8_pqc3QGIagm4EgOL8KYhEEg_ZEZdQEaCI&spm=tbpc.boughtlist.suborder_itemtitle.1.c3892e8dY9OLZg>) |
| 19 | Parafuso autoatarraxante de ponta chata M2×8 | Peça padronizada | 1 pacote | 4.05 | 4.05 |  | [Link de compra](<https://detail.tmall.com/item.htm?id=534923831046&mi_id=0000lLHxCRqtZ8_pqc3QGIagm4EgOL8KYhEEg_ZEZdQEaCI&spm=tbpc.boughtlist.suborder_itemtitle.1.c3892e8dY9OLZg>) |
| 20 | Parafuso autoatarraxante de ponta chata M2,5×6 | Peça padronizada | 1 pacote | 3.93 | 3.93 |  | [Link de compra](<https://item.taobao.com/item.htm?spm=a1z0d.6639537%2F202410.item.d534923831046.10db74840oHq5F&id=534923831046&from=cart&skuId=5947341310639&mi_id=0000RGt64BzUSirBb2ZGiESDHLYHZCCldpvt2pjiQe6DwTE&upStreamPrice=700>) |
| 21 | Parafuso autoatarraxante de ponta chata M2,5×8 | Peça padronizada | 1 pacote | 2.08 | 2.08 |  | [Link de compra](<https://item.taobao.com/item.htm?spm=a1z0d.6639537%2F202410.item.d534923831046.10db74840oHq5F&id=534923831046&from=cart&skuId=5947341310640&mi_id=0000RGt64BzUSirBb2ZGiESDHLYHZCCldpvt2pjiQe6DwTE&upStreamPrice=700>) |
| 22 | Trava-roscas Loctite 243 | Peça padronizada | 1 | 9 | 9 |  | [Link de compra](<https://item.taobao.com/item.htm?adType=orgqzt&from=cart&id=1056442610986&mi_id=0000wOojFoJyiP5dQudTpjmjzfZLEEq7GLdMEB8DaDqMa7Y&skuId=6099342537028&spm=a1z0d.6639537%2F202410.item.d1056442610986.44d57484Ny8pKV&upStreamPrice=900&xxc=qzt_taobaoSearch>) |
| 23 | Almofada antiderrapante para sola | Peça padronizada | 1 | 16 | 16 |  | [Link de compra](<https://detail.tmall.com/item.htm?id=888852278057&mi_id=0000Bug6nFYlEVkT2CGWMwXKqUSbi-0G_VP4pnfiGwBOnrU&spm=tbpc.boughtlist.suborder_itemtitle.1.c3892e8dY9OLZg&skuId=5902232407790>) |

<a id="observacoes-e-conferencia"></a>

## 3. Observações da tabela original e itens a conferir

**Total da planilha original: ¥2.426,88.** O arquivo Excel permanece inalterado; confira estes dois pontos:

- A fórmula do total é `SUM(I3:I58)` e não inclui o último item, “Almofada antiderrapante para sola” (I59, ¥16).
- Na linha “Bateria NP-F550”, a quantidade é 1, o preço unitário é ¥17 e o total é ¥47; os valores não coincidem.

<details>
<summary>Ver instruções originais do autor anexadas à planilha Excel</summary>

Instruções:
🦆 Todo mundo pode ter seu próprio MicroDuck!

💰 Informações sobre o custo do projeto
Além dos 15 servos, da placa HAT e da placa IMU, os demais componentes de hardware custam cerca de ¥828.
Os 15 servos, a placa HAT e a placa IMU podem ser adquiridos em grupo por meio do projeto no GitHub ou comprados separadamente, conforme a necessidade, em plataformas como JLCPCB e Taobao.
Depois, publicaremos tutoriais de instalação e depuração para ajudar todos a montar e configurar o MicroDuck com mais facilidade.
🤖 Por que abrir o projeto?

Queremos que mais pessoas possam conhecer e estudar inteligência incorporada, controle de robôs e aprendizado por reforço a um custo menor.

Todo mundo pode ter seu próprio pato.

Com o código aberto, esperamos construir junto com a comunidade um ambiente de aprendizado mais aberto e acolhedor, para que mais pessoas possam colocar a mão na massa e explorar inteligência incorporada desde o início.

Se este projeto foi útil para você, deixar uma curtida é a maior forma de apoio ❤️

Acompanhe também nosso GitHub e deixe uma estrela ⭐!

🔗 GitHub:
https://github.com/fanhao375/microduck-replica

📕 Xiaohongshu: 机械行者
🎵 Douyin: 机械行者Robo
Bilibili: 机械行者Robo

</details>
