# Web动作录制 e 回放：第一版设计

日期：2026-10-24。最新状态（2026-10-25）：已按Usuário授权实现并部署到Atual鸭子原Controle网址；SoftwareVerificação e 部署回读por meio de，真机动作效果待Usuário试用。

2026-10-25 复核：Web录制回放仍未实现。Inferior文声音路线描述 de 是写稿时状态；后续独立 de  R3 复读 e 坐立语音Serviço已在Atual鸭子Validação，见[语音Serviço](../../../software/duck-echo/README.md)。Usuário本次又提出将新功能、Modelo动作e已保存回放绑定到手柄，属于在原首版之外 de 扩展方向，已汇入[Software功能 e 升级总账](../../Software功能 e 升级总账.md)，未在此暗 em 扩大首版实现范围。

2026-10-25 后续实现：Superior述“仍未实现”为当天较早盘点 de Histórico状态，现已由 c18783c 实现并部署。Completo范围、Testee备份见[本轮验收](../verification/2026-10-25-web-motion-studio.md)。首版接受摇杆、头/身体/嘴e已知叫声，并可记录灵动生成 de 目标；Modelo技能无法可靠确认结束，因此在录制时明确拒绝，不声称已经实现Inferior文设想 de 技能等待/取消。已保存回放 de 手柄或语音绑定尚未实现；仍不录音视频、不保证精确空间路线。

## Usuário已经确定 de 范围

- 从Web点击开始录制，使用现有Web遥控 e 虚拟摇杆操作，不依赖实体手柄按键映射。
- 包括前进、后退、转弯，记录Web操作对应 de 速度、方向e持续时间，再按时间回放。
- pode停止录制、命名保存，随后选择记录重复播放。
- 声音录制、声音触发动作、模仿声音是后续独立阶段，本次不一起实现。

## 方案选择

推荐录制经过现有权限 e 状态Verificação、实际获准发送 de WebControle指令，加Superior相对时间。回放也经过同样 de Verificação，并Preservado主程序负责平衡e关节Controle de 方式。

另一种方案是采集全部关节角度，再直接复现关节轨迹。它适合以后单独研究手扶示教，但é necessário处理Ficar em pé平衡、接触地面e关节Superior力，不能当成本次Web指令录制 de 替代实现。

本功能重复 de 是Controle指令 e 节奏，不保证相同脚步、落脚位置或空间路线。起始姿态、地面e打滑都会改变实际运动；不使用“原路返回”或“精确轨迹回放”字样。

## Web使用流程

在现有遥控卡内增加“动作录制”区域，靠近站、走、坐按钮，不新增实体手柄绑定。

1. Usuário按原流程让鸭子站稳。录制按钮本身不触发Ficar em pé、Superior力或开始走。
2. 点击“开始录制”，显示红色录制状态、已录时长e“暂停录制／结束录制”。
3. 操作现有Web摇杆、Cabeça／身体模式、张嘴、叫声 e 已suporta de 动作。界面 em  de 校准、设置修改、Modelo更换不属于动作记录。
4. 点击“暂停录制”时停止连续运动并回 em ，暂停 de 等待时间不进入成片；继续后从新操作开始，不延续暂停前按住 de 摇杆。
5. 点击“结束录制”，停止连续运动，输入名字，保存。没有有效动作时Instruções原因，不生成空记录。
6. 从记录列表选择一条，查看名称、时长 e 所需Modelo／功能，选择播放 1、3 或 5 次，默认 1 次。
7. 明确点击“开始回放”。显示进度、Atual步骤、剩余次数e“暂停回放／停止回放”，顶部急停仍可用。

记录可重命名、删除。第一版不做剪辑、拼接、倍速、导入Arquivo或无限循环。

## 录制Conteúdo e 起始条件

- 记录Serviço端接受 de WebControle事件 e 单调时钟时间，不抓浏览器键盘original事件，也不把全部 JSON-RPC 当成可回放Conteúdo。
- 连续通道记录经过限制后 de 速度／角速度、Cabeça、身体、嘴部意图e停止边界。将模式变化显式保存，不依赖回放前Página de 摇杆模式。
- 动作e技能记录已知动作标识 e 生命周期；叫声记录已知声音标识。不得把任意方法名、ArquivoCaminho或程序写进记录。
- Levantar、开始走、Sentar是Usuário在录制前手动Concluído de 状态准备，第一版不将这些切换作为回放步骤。操作 em 改变这些准备状态、卸力、进入校准或更换Modelo时，结束Atual录制／回放并显示原因。
- 若Conteúdoé necessárioCaminhada策略，录制e回放前均要求鸭子已经具备“准备好走” de 状态。Verificação实时状态、AtualModeloe速度限制，不用录制Arquivo里 de 旧状态代替Verificação。
- 实体手柄Conexão时沿用现有Web遥控互斥规则；Web摇杆不可用就不能开始本次Web录制，并解释原因。
- 保存必要 de Modelo／Configuração指纹。相关Modelo或ControleConfiguração不匹配时拒绝回放，提示重新录制，避免同一标识变成另一动作。

## 暂停、停止e执行边界

- 回放暂停时停止Caminhada、清除持续 de 头／身体／嘴部Controle，不再发出后续步骤；时间轴停在Atual位置。继续由Usuário明确点击，并重新Verificação状态。
- 已触发 de 踢腿、翻滚等技能不能靠停止发送指令假定已经物理停止。é necessárioVerificaçãoExecução端是否suporta取消；não suporta时，普通暂停在Atual技能结束处生效，界面显示“等待Atual技能结束”。急停始终走原有卸力通道。
- “停止回放”取消余Inferior步骤e后续循环，并停止连续Controle。不能将急停或普通停止包装成后台继续执行。
- 同一时刻只有一个录制或回放会话。回放期间禁用相冲突 de 普通Controle；手动接管先终止回放再接受新Controle。
- 切页、滚出Controle区、标签页隐藏、窗口失焦、Conexão丢失、Controle权变化、异常状态或急停，均终止录制／回放。恢复Conexão不会自动续播。
- Serviço端执行时间轴，并要求AtualWeb每 100 毫秒发送有效存活信号。超过 500 毫秒没有信号必须停止，不能由Serviço端无限续发速度而绕开现有 deadman。
- 不为了回放绕过现有低电压、Servo故障、IMU 状态或Modelo就绪Verificação。
- 每轮结尾停止连续运动、退出身体锁存并合嘴；Inferior一轮重新核对状态后才开始。不会自动重新Superior力。

## Dadose模块边界

- 录制、Arquivo校验e时间轴执行使用独立模块；por meio de PadOps  de 已授权Controle入口交互，不向已经很大 de Web或 pad_drive.py  em 堆Completo实现。
- 保存Arquivo采用Versão化Dados结构：标识、名称、创建时间、有效时长、起始要求、Configuração指纹e白名单事件列表。
- 存入 Studio  de  state Diretório，不修改Imagem默认动作。Arquivo使用原子替换，并限制Quantidade、时长、名称、Arquivo大小、事件Quantidade e Parâmetros范围。
- 第一版Superior限：单条 60 秒，最多 20 条，重复最多 5 次。名称不超过 32 个字符，单个Arquivo不超过 1 MiB、6,000 个事件；拒绝非有限数字、逆序时间e未知事件。达到时长或事件Superior限时自动结束为待保存草稿；保存Falha不显示Sucesso。
- 不记录摄像头视频或麦克风音频。功能e摄像头预览可同时使用，但各自管理资源。
- Dados保存在板端；Web不是后台独立Execução de 机器人任务调度器。未保存草稿在Serviço重启后不保证Preservado，界面明确显示“尚未保存”。

## Validação e 交付

纯逻辑Teste覆盖时间顺序、暂停去除等待、连续通道重建、循环结束回 em 、Arquivo损坏／越界Parâmetros拒绝、Configuração不匹配 e 并发会话互斥。

使用假 robotd Verificação实际发出 de 意图e顺序，并Validação断线、迟到事件、接管、急停、后台e刷新不会续播。不能仅conforme按钮变色判定回放Sucesso。

浏览器Verificação桌面e 320／390px 窄屏 de 录制、保存、命名、回放、暂停、停止、有限循环e删除流程，e录制栏不影响原有遥控 e 摄像头布局。

首先Concluído本地模拟e回归。真实鸭子验收单独进行，从短时间、低速片段开始，记录运动偏差 e 取消技能 de 真实行为；本地por meio de不等于板端ValidaçãoConcluído。不自动重刷Imagem或部署。

## 后续声音互动路线

现有工程有声卡初始化、板载麦克风输入路由e叫声播放基础；Studio 尚没有Usuário录音、声音学习或声音触发动作功能，真实麦克风采集也尚未在本任务 em Validação。

先做手动录音 e 试听，确认板载麦克风e喇叭链路；再做“鹦鹉学舌”：录一句、播放原声或变声，并配合嘴部动作。随后研究指定口令或声音 e 已保存动作绑定，加入未知声音拒绝、触发间隔e扬声器回声抑制，并在Servo噪声 em 实测误触发。

“重复播放刚听见 de 话”e“克隆音色生成新 de 话”是不同功能，不能把前者演示宣称为后者。声音识别只产生动作Por favor求，必须继续经过同一套就绪 e 停止Verificação；听见声音不直接绕过Controle权InicializaçãoCaminhada。

声音阶段技术参考：[ALSA 官方录音与播放测试](https://wiki.alsa-project.org/wiki/SoundcardTesting)、[TensorFlow 官方关键词识别示例](https://www.tensorflow.org/tutorials/audio/simple_audio)。这些只支持可行性研究，不证明当前鸭子已完成采集或识别。
