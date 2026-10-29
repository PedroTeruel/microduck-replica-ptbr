# 连续语音 e 音乐互动

Usuário已确定：R3 单击开启语音、再次单击关闭；声音来自旁边手机或音箱；听音乐时以小幅Cabeçae身体动作响应，提问“感觉怎么样”“喜欢这种歌吗”时按音乐感觉发出不同叫声。沿用板载麦克风、本地识别、现有Webe SSH SoftwareAtualização。

## 第一交付：R3 连续语音

开启后共享一条有界麦克风流，停顿自动分句，每句最长 10 秒；关闭、Select、手柄失联、输入丢帧 e Serviço退出都取消未执行 de 识别e播放。忽略键重复，Inicialização时已按住 R3 必须先松开。PreservadoSentar/站起口令。按Usuário后续明确要求，R3或Web实际开启时短叫一次，默认日常模式不再播放Usuário原话；已识别 de 动作e音乐问题使用鸭子 de 原生叫声回应。录音复读是独立功能，Preservado显式 echo Configuração e  CLI record，单独按键留待之后决定。播放自身声音时暂停收音处理并留尾音间隔，防止自我复读。默认使用单击模式，Preservado显式 hold Configuraçãousado para回退。无音频留盘，无云Serviço。

第一交付已用复读确认过实际分句，后续日常模式以坐站口令、原生叫声e音乐问答验收，再单击后不再执行。不能把单击切换做成仍要按住或每 10 秒自动关闭。麦克风Falha须退出本轮监听，不可反复忙循环。

Usuário随后明确要求关闭也有不同提示：显式R3或Web从开启切到关闭时使用低coo一次，开启用chirp；分句结束仍继续监听，不播放关闭提示。Select、断连、输入丢帧、FalhaeServiço退出等自动取消不叫。关闭提示沿用有界派发线程，重开/退出会取消未播出 de 旧提示，不另建每次点击 de 线程。

## 第二交付：音乐感知 e 回应

同一麦克风流产生节拍e粗略 de 轻快、低沉、松弛摇摆、不确定状态；不把快慢当成准确爵士曲风识别。询问语句 e 动作口令分开处理，只用已确认 de 提问触发叫声，叫声期间抑制自身音频。无把握时使用询问声。问话需在音乐持续播放 de 情况Inferior实测，不能只用静音单元Teste代替。

## 第三交付：动作 e Web

小幅Cabeça、身体意图por meio de Studio 现有Controle仲裁发出，仅在策略接管、状态新鲜、姿态稳定时Execução。手柄人工操作、WebControle、录制回放、灵动、坐站 e 失联优先；不主动Superior力、不Inicialização策略、不换Modelo。静音、Dados过期或关闭后停止律动。Web显示监听、节拍、音乐感觉e暂停原因。Atual板无散热器，é necessário记录负载 e 温度后再启用常驻分析。

## 发布

逐步交付可TesteVersão，PreservadoInstalação前ArquivoeConfiguração，Teste e VersãoGravaçãoSoftware功能总账。只重启本任务é necessário de Serviço；不重启运动核心。真实动作验收交由Usuário进行。
