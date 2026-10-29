# ServoSCS通信Protocolo

# 1 通信Protocolo概要
&emsp;&emsp;通讯电平采用兼容高速通信 de TTL电平方式 e 具有较强抗干扰能力 de RS485方式，通讯仍是采用异步双工，发送 e 接收信号是异步处理。
&emsp;&emsp;Controle器eServo之间采用问答方式通信，Controle器发出指令帧，Servo返回应答帧。
&emsp;&emsp;一个总线ControleRede em 允许有多个Servo，所以每个Servo都分配有一个Rede内唯一 de ID号。Controle器发出 de Controle指令 em 包含ID信息，只有匹配SuperiorID号 de Servo才能Completo接收这条指令，并返回应答信息。
通信方式为串行异步方式，一帧Dados分为1位起始位，8位Dados位e1位停止位，无奇偶校验位，共10位。
&emsp;&emsp;内存表 de 部分Parâmetros采用两个字节 de 值域时，两个字节顺序conformeServo型号区分，电位器类型Servo为大端格式（高字节在前低字节在后），磁编码类型Servo为小端格式（低字节在前高字节在后）。每款Servo因功能略有不同，因此实际Controle时Por favor参照具体型号 de 内存表为准。

# 2 指令帧
|字头|ID号|Dados长度|指令|Parâmetros|校验e|
|-|-|-|-|-|-|
|0xFF 0xFF|ID|Length|Instruction|Parameter1 ...Parameter N|Check Sum|

- 字头：连续收到两个0xFF ,表示有Dados包到达。
ID号：每个Servo都有一个ID号。ID号范围0～253,转换为十六进制0x00～0xFD。
- 广播ID：ID号254为广播ID,若Controle器发出 de ID号为254(0xFE)，所有 de Servo均接收指令，除PING指令外其它指令均不返回应答信息(多个ServoConexão在总线Superior不能使用广播PING指令)。
- Dados长度：等于待发送 de ParâmetrosN加Superior2，即“N+2”。
- 指令：Dados包操作功能码，详见4指令类型。
- Parâmetros：除指令另外é necessário补充 de Controle信息，Parâmetros最大suporta双字节Parâmetros表示一个内存值，字节顺序参考Servo使用手册内存Controle表(不同型号Servo字节顺序不一样)。
- 校验e：校验eCheck Sum，计算方法如Inferior
Check Sum = ~ (ID + Length + Instruction + Parameter1 + ... Parameter N) 若括号内 de 计算e超出255, 则取最低 de 一个字节，“~”表示取反。

# 3 应答帧
|字头|ID号|Dados长度|状态码|Parâmetros|校验e|
|-|-|-|-|-|-|
|0xFF 0xFF|ID|Length|ERROR|Parameter1 ...Parameter N|Check Sum|

返回 de 应答帧包含Servo de Atual状态ERROR，若ServoAtual工作状态不正常，会por meio de这个字节反映出来（各状态所代表意义详见手册内存Controle表），若ERROR为0，则Servo无报错信息。

# 4 指令类型
|指令|功能|值|Parâmetros长度|
|-|-|-|-|
|PING（查询）|查询工作状态|0x01|0|
|READ DATA（读）|查询Controle表里 de Dados|0x02|2|
|WRITE DATA（写）|往Controle表里GravaçãoDados|0x03|不小于2|
|REGWRITE DATA（异步写）|类似于WRITE DATA，但是Controle字符Gravação后并不马Superior动作，直到ACTION指令到达|0x04|不小于4|
|ACTION（执行异步写）|触发REG WRITEGravação de 动作|0x05|0|
|SYCNREAD DATA（同步读）|usado para同时查询多个Servo|0x82|不小于3|
|SYCNWRITE DATA（同步写））|usado para同时Controle多个Servo|0x83|不小于2|
|RESET（状态重置）|重置Servo状态(重置Servo圈数)|0x0A|0|
|位置校准|Atual位置重校准为指令值|0x0B|0|
|Parâmetros恢复指令|恢复Servo除ID号外 de 其它Parâmetros|0x06|0|
|Parâmetros备份指令|备份AtualParâmetros，usado para恢复指令|0x09|0|
|重启指令|usado para重启Servo|0x08|0|

## 4.1 查询状态指令PING
- 功能：LeituraServo de 工作状态
- 长度：0x02
- 指令：0x01
- Parâmetros：无
- PING指令使用广播地址，Servo同样返回应答信息。

**例1：LeituraID号为1 de Servo de 工作状态。**
指令帧：FF FF 01 02 01 FB（按十六进制发送）
```language
字头：FF FF
ID：01
长度：02
指令：01
校验和：FB
```

应答帧： FF FF 01 02 00 FC（十六进制显示）
```language
字头：FF FF
ID：01
长度：02
状态：00
校验和：FC
```

## 4.2 读指令READ DATA
- 功能：从Servo内存Controle表里读出Dados
- 长度：0x04
- 指令：0x02
- Parâmetros1：Dados读出段 de 首地址
- Parâmetros2：LeituraDados de 长度

**例2：LeituraID为1 de Servo de Atual位置（低位字节在前，高位字节在后）。位置Parâmetros内存表地址为0X38，连续二个字节。**

指令帧：FF FF 01 04 02 38 02 BE（按十六进制发送）
```language
字头：FF FF
ID：01
长度：04
指令：02
参数：38 02（当前位置地址 读数据长度）
校验和：BE
```

应答帧：FF FF 01 04 00 18 05 DD（十六进制显示）
```language
字头：FF FF
ID：01
长度：04
状态：00
参数：18 05
校验和：DD
```
读出两个字节Dados分别是（小端结构）：低位字节L 0x18  高位字节H 0x05，两字节合成16位Dados0X0518，用十进制表示Atual de 位置为1304。

## 4.3 写指令WRITE DATA
- 功能：写Dados到Servo内存Controle表
- 长度：N+2（N为Parâmetros长度）
- 指令：0x03
- Parâmetros1：DadosGravação段 de 首地址
- Parâmetros2：Gravação第1个Dados
- Parâmetros3：Gravação第2个Dados
...
- ParâmetrosN：Gravação第n个Dados，N=n+1

**例3：使用广播ID (0xFE)把任意编号Servo de ID设置为1，在内存表里保存ID号 de 地址为5。**
指令帧：FF FF FE 04 03 05 01 F4 (按十六进制发送)
```language
字头：FF FF
ID：01
长度：04
指令：03
参数：05 01（ID地址 新ID值）
校验和：F4
```

因为采用广播ID发送指令，所以不会有Dados返回。另外内存表EPROM 具有保护锁开关，修改ID前é necessário把它关掉（置0），不然示例ID号掉电将不保存。详细操作Por favor查阅具体Servo型号 de 内存表或操作手册。

**例4：ControleID1Servo以1000步每秒 de 速度转动到2048 de 位置。内存表目标位置 de 首地址为0x2A，所以在地址0x2A处开始Gravação连续六个字节Dados。**

- 位置Dados0x0800(2048)
- 预留Dados0x0000(0)
- 速度Dados0x03E8(1000)

指令帧：FF FF 01 09 03 2A 00 08 00 00 E8 03 D5（按十六进制发送）
```language
字头：FF FF
ID：01
长度：09
指令：03
参数：
2A（首地址）
00 08（位置）
00 00（预留）
E8 03（速度）
校验和：D5
```

应答帧：FF FF 01 02 00 FC（十六进制显示）
```language
字头：FF FF
ID：01
长度：02
状态：00
校验和：FC
```
返回工作状态为0，表示Servo正确无错接收到指令并已开始执行。发送指令包 de ID使用非广播ID (0xFE)，所以指令接收Concluído后Servo将返回状态包。

## 4.4 异步写指令REG WRITE
REG WRITE指令相似于WRITE DATA，只是执行 de 时间不同。当收到REG WRITE指令帧时，把收到 de Dados储存在缓冲区备用，并把异步写标志寄存器置1。当收到ACTION指令后，储存 de 指令最终被执行。
- 长度：N+2（N为Parâmetros长度）
- 指令：0x04
- Parâmetros1：Dados要Gravação区 de 首地址
- Parâmetros2：Gravação de 第1个Dados
- Parâmetros3：Gravação de 第2个Dados
- ParâmetrosN：Gravação de 第n个Dados，N=n+1

**例5：ControleID1到ID10Servo以1000每秒 de 速度转动到2048 de 位置。**

```language
ID 1：异步写指令帧：FF FF 01 09 04 2A 00 08 00 00 E8 03 D4 
ID 1：应答帧：FF FF 01 02 00 FC
ID 2：异步写指令帧：FF FF 02 09 04 2A 00 08 00 00 E8 03 D3 
ID 2：应答帧：FF FF 02 02 00 FB
ID 3：异步写指令帧：FF FF 03 09 04 2A 00 08 00 00 E8 03 D2 
ID 3：应答帧：FF FF 03 02 00 FA
ID 4：异步写指令帧：FF FF 04 09 04 2A 00 08 00 00 E8 03 D1 
ID 4：应答帧：FF FF 04 02 00 F9
ID 5：异步写指令帧：FF FF 05 09 04 2A 00 08 00 00 E8 03 D0 
ID 5：应答帧：FF FF 05 02 00 F8
ID 6：异步写指令帧：FF FF 06 09 04 2A 00 08 00 00 E8 03 CF 
ID 6：应答帧：FF FF 06 02 00 F7
ID 7：异步写指令帧：FF FF 07 09 04 2A 00 08 00 00 E8 03 CE 
ID 7：应答帧：FF FF 07 02 00 F6
ID 8：异步写指令帧：FF FF 08 09 04 2A 00 08 00 00 E8 03 CD 
ID 8：应答帧：FF FF 08 02 00 F5
ID 9：异步写指令帧：FF FF 09 09 04 2A 00 08 00 00 E8 03 CC 
ID 9：应答帧：FF FF 09 02 00 F4
ID10：异步写指令帧：FF FF 0A 09 04 2A 00 08 00 00 E8 03 CB
ID10：应答帧：FF FF 0A 02 00 F3
```

## 4.5 执行异步写指令ACTION
- 功能：触发REG WRITE指令
- 长度：0x02
- 指令：0x05
- Parâmetros：无

1、ACTION 指令在同时Controle多个Servo时非常有用。
2、在Controle多个Servo时，使用ACTION指令pode使第一个e最后一个Servo同时执行各自 de 动作， em 间无延时。
3、对多个Servo发送ACTION指令时，要用到广播ID（0xFE）因此，发送此指令不会有Dados帧返回。

**例6：ControleID1到ID10Servo以1000每秒 de 速度转动到2048 de 位置 de 异步写指令发完后，é necessário执行异步写指令。**
```
指令帧：FF FF FE 02 05 FA
应答帧：无
```

## 4.6 同步写指令SYNC WRITE
- 功能：usado para同时Controle多个Servo。
- ID：0xFE
- 长度：(L+1)*n+4（L：发给每个Servo de Dados长度，n：Servo de 个数）
- 指令：0x83
- Parâmetros1：GravaçãoDados de 首地址
- Parâmetros2：Gravação de Dados de 长度(L)
- Parâmetros3：第1个Servo de ID号
- Parâmetros4：Gravação第1个Servo de 第1个Dados
- Parâmetros5：Gravação第1个Servo de 第2个Dados
...
- ParâmetrosL+3：Gravação第1个Servo de 第L个Dados
- ParâmetrosL+4：第2个Servo de ID号
- ParâmetrosL+5：Gravação第2个Servo de 第1个Dados
- ParâmetrosL+6：Gravação第2个Servo de 第2个Dados
…
- Parâmetros2L+4：Gravação第2个Servo de 第L个Dados
…

不同于REG WRITE+ACTION指令 de 是实时性比它更高，一条SYNC WRITE指令可一次修改多个Servo de Controle表Conteúdo，而REG WRITE+ACTION指令是分步做到 de 。 尽管如此，使用SYNC WRITE指令时，Gravação de Dados长度e保存Dados de 首地址必须相同。

**例7：对ID1-ID4共4个Servo首地址0x2AGravação位置0x0800时间0X0000e速度0x03E8 (低位字节在前，高位节位在后)。**
指令帧: FF FF FE 20 83 2A 06 01 00 08 00 00 E8 03 02 00 08 00 00 E8 03 03 00 08 00 00 E8 03 04 00 08 00 00 E8 03 58（按十六进制发送）
```language
字头：FF FF
ID：FE
有效数据长度：20
指令：83
参数：
2A 06（首地址 数据长度）
01 00 08 00 00 E8 03（ID1舵机指令）
02 00 08 00 00 E8 03（ID2舵机指令）
03 00 08 00 00 E8 03（ID3舵机指令）
04 00 08 00 00 E8 03（ID4舵机指令）
校验和：58
```

## 4.7 同步读指令SYNC READ
- 功能：usado para同时查询多个Servo。
- ID：0xFE
- 长度：n+4（n为Servo个数）
- 指令：0x82
- Parâmetros1：读Dados de 首地址
- Parâmetros2：读Dados de 长度
- Parâmetros3：第1个Servo de ID号
- Parâmetros4：第2个Servo de ID号
…
- ParâmetrosN：第n个Servo de ID号，N=n+2

一条SYNC READ指令可一次查询多个Servo de Controle表Conteúdo，同步读指令 em 指定了é necessário查询Servo de ID，Servo返回应答包顺序按指令包 em ID顺序返回，使用SYNC READ指令时，所有查询 de Dados长度eDados de 首地址必须相同（此指令针对部分串行总线Servo开放）。

**例8：查询ID1-ID2共2个Servo de Atual位置、Atual速度、Atual负载、Atual电压、Atual温度（首地址0x38，共8字Dados，低位字节在前，高位节位在后）。**

指令帧：FF FF FE 06 82 38 08 01 02 36
```language
字头：FF FF
ID：FE
长度：06
指令：82
参数：
38 08（数据首地址 数据长度）
01 02（ID01 ID02）
校验和：36
```

应答帧：
```language
ID01舵机：FF FF 01 0A 00 00 08 00 00 00 00 79 1E 55 
ID02舵机：FF FF 02 0A 00 FF 07 00 00 00 00 77 23 53
```
应答帧可按读指令进行解码

## 4.8 状态重置指令RESET
- 功能：重置Servo状态（重置Servo圈数）
- 长度：0x02
- 指令：0x0A
- Parâmetros：无

**例9：复位Servo，ID号为01。**
```language
指令帧：FF FF 01 02 0A F2（按十六进制发送）
应答帧：FF FF 01 02 00 FC（十六进制显示）
```

## 4.9 位置校准指令
- 功能：Atual位置重校准为设定值
- 长度：0x02或0x04
- 指令：0x0B
- Parâmetros：无或设定值

**Observação：位置校准指令无Parâmetros表示Atual位置校准为 em 位；校准指令只suporta部分型号Servo，Servo型号suporta情况查阅Inferior表Instruções。**

**例10：Atual位置重校准为 em 位。**
```language
指令帧：FF FF 01 02 0B F1（按十六进制发送）
应答帧：FF FF 01 02 00 FC（十六进制显示）
```

**例11：Atual位置重校准为1024。**
指令帧：FF FF 01 04 0B 00 04 EB（按十六进制发送）
```language
字头：FF FF
ID：01
长度：04
指令：0B
设定值：00 04（1024）
校验和：EB
```

应答帧：FF FF 01 02 00 FC（十六进制显示）
```language
字头：FF FF
ID：01
长度：02
状态：00
校验和：FC
```

|Servo型号|FirmwareVersão|生效条件|Observação|
|-|-|-|-|
|SMSServo|<=2.54|无|suporta扭矩开关写128实现 em 位校准|
|STSServo|>=3.10|无|suporta无Parâmetros e 有Parâmetros指令，suporta扭矩开关写128实现 em 位校准|
|HLSServo|>=3.43|无|suporta无Parâmetros e 有Parâmetros指令，não suporta扭矩开关写128实现 em 位校准|

## 4.10 Parâmetros恢复指令
- 功能：恢复Servo除ID号外其它Parâmetros
- 长度：0x02
- 指令：0x06
- Parâmetros：无

**例11：恢复ServoParâmetros。**
```language
指令帧：FF FF 01 02 06 F6（按十六进制发送）
应答帧：FF FF 01 02 00 FC（十六进制显示）
```
**Observação：恢复ServoParâmetros前先解锁epromParâmetros**

## 4.11 Parâmetros备份指令
- 功能：Parâmetros备份（usado paraParâmetros恢复指令）
- 长度：0x02
- 指令：0x09
- Parâmetros：无

**例12：备份ServoParâmetros。**
```language
指令帧：FF FF 01 02 09 F3（按十六进制发送）
应答帧：FF FF 01 02 00 FC（十六进制显示）
```
**Observação：备份ServoParâmetros前先解锁epromParâmetros**

## 4.12 重启指令
- 功能：重启指令（重启Servo）
- 长度：0x02
- 指令：0x08
- Parâmetros：无

**例13：重启Servo。**
```language
指令帧：FF FF 01 02 08 F4（按十六进制发送）
应答帧：无（重启时间约800ms）
```
**Observação：重启Servo前，先关闭扭矩开关**
