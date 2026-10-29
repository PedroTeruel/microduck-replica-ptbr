# 本地音乐互动修复 e 实际限制

日期：2026-10-26（东京时间）。本轮已部署Software修正，但Usuário仍反馈等待节拍、头身未随乐运动，**尚未por meio de真实音乐动作验收**。

## 已部署

- 语音 `2f24a6ae7b5a2b16d2b222eee507aa91b988c9fc`：20ms ALSA period/80ms buffer，按样本推进的音频时间轴，连续包络周期判断，短断流和时钟漂移处理，停歌底噪下释放旧节拍。
- Studio `6ca5459c781663d3872cf3a2b4697ee21a05c892`：等待节拍与产生律动分开显示；R3/服务关闭会结束独立音乐会话，恢复监听不复活旧会话。前台/心跳与实体手柄保护仍保留。
- 语音备份 `/var/lib/duck-echo/upgrades/20261026-012132-2f24a6ae7b`，部署时PID42568；后续收音对照仅重启了该语音服务，不能再将42568当成当前PID。网页备份 `/home/radxa/.microduck-backups/web-audio-20261025-cefb03d009`，运行PID43893。
- WebAtualização前Usuário确认停好，回读standing/homed、policy_enabled=false；没有补发停止Comando。Atualização5个StudioArquivo；12个原UsuárioDadosArquivohashInalterado。robotd1099/padd1132 e Inicialização时间保持。
- 8项HTTP资源/健康Verificaçãopor meio de，静态资源hash e 冻结Arquivo相同且no-cache；真实WebSocket快照要求登录，没有绕过登录。

## Software e 性能Verificação

- Windows语音150项：133por meio de，17项Linux跳过；WSLe鸭子Superior150项全por meio de。鸭子最终Versão用时98.600秒。
- Studio Python3.13后端257项、Node11项por meio de；独立审查 de 相关后端88项por meio de。
- 本地EdgeCompleto流程por meio de，88.561秒：先显示等待且无虚构动作，再显示律动；假机器人记录头22帧、身体21帧；Preservado坐站录制/多次回放 e 窄屏Verificação。这不是真机效果。
- 两阶段独立审查修复了弱起音遮蔽重复证据、慢节奏停歌超时e短模式切换累积时间偏移。没有遗留已知重要Software审查项。
- ARM离线数值基准（7fb0b86检测主体）：8秒包络处理约521.66ms CPU，最慢帧30.05ms，缓存快照平均约0.019ms；此项不是整套ASR/音乐长时温度Teste。

## 真实采集 e UsuárioResultado

- Usuário在旁边播放音乐时，两次8秒A/B采集证明默认period6000帧=125ms；Por favor求小周期后实际960帧=20ms。旧起音Algoritmos在小周期歌曲段没有稳定Resultado，新Algoritmos能从该段数值包络取得约100BPM。仅数值落盘，没有保存PCM或谈话录音。
- Superior机后Usuário反馈“一直等待节拍，头e身体都没动”，仍按未修复处理。第一段45秒电机观察发生在Usuário开始操作前：监听/音乐均false、策略关闭，因此未覆盖其实际播放，不能usado para动作验收。
- 后续连续6秒真实Serviço回读60/60项有效，约65.2BPM、置信度0.667–0.815；但再读时又回到unknown。实际音乐 de 锁定仍不稳定，单段por meio de不能代表真实歌曲普遍可用。
- 用Studio实际Python3.13、radxa UID1000Execução已InstalaçãoAudioClientLeituraSucesso；同一MusicRhythm在unknown时正确等待。不能将问题归因为Controlesocket权限或已证明 de 时钟差异。

## 后续收音 e 独立Algoritmos对照（仍未验收）

- 实际ALSA `cget` 核对：右路Mic3R开启，其余PGA输入关闭，PGA Capture Switch为on,on，增益60,60（30dB），AGC关闭。与当前服务采集右声道一致；不能仅凭配置正常就断定外放音乐清楚进入麦克风。
- 两次约62秒Serviço状态观察均没有可靠节拍，Direito路DC去除后 de RMS大致207–414。Usuário de “Teste麦克风”对照尚未收到Concluído确认，因此这些Dados不能当成说话或特定歌曲 de 已确认Teste片段。
- 在私有staging中构建aubio0.4.9 DSP核心，原始源码SHA256为`d48282ae4dab83b3dc94c16cf011bcb63835c1c02b515490e1883049c3d1f3da`；没有安装系统包或改生产算法。12秒真实采集对照中，tempo输出预测拍但原生confidence始终为0，specflux只在启动时报告一次起音。不得将预测拍数作为可靠节拍证明。
- 短提示音声学回采：Direito路提示音前/后RMS约302/294，700Hze1100Hz提示音期间约28659/32049，且频率分量对应；Esquerdo路始终为0。确认Direito路能收到本机输出，后者已发生削波，不重复使用该音量做Teste。此Resultado不能替代外放音乐 e 近距离说话对照。
- 该提示音Teste只临时停止语音Serviço以独占声卡，finally恢复原监听/音乐开关；未调用运动接口。恢复后语音PID53645、Studio43893、robotd1099、padd1132。实际ExecuçãoSoftware仍为语音2f24a6a/Studio6ca5459。
- Inicialização一个有300秒自动期限 de 数值输入观察器，仅保存时间、RMS、BPM、置信度 e 开关，不保存话语或PCM。仍需Usuário外放音乐/说话 de 同步确认，继续定位输入e检测之间 de 差异。

## 身体Modelo能力 de 关键发现

在Atual已站稳、策略Execução、扭矩确认、关节反馈新鲜且实体手柄断开时做短时、小幅、无Caminhada de 接口对照；未自动HOME、使能或更换Modelo。所有探测结束均发送head零/pose inactive并取得accepted。

- 6秒1Hz头身对照：300次Por favor求被接受；头yaw实际变化范围0.08897rad，身体关节基本Inalterado。
- 6秒缓慢静态roll0.04rad：身体实际无可见位置变化；加入move零心跳也没有改善，排除该假设。
- 同步订阅真实目标：身体关节目标变化仅约0.002–0.010rad，实测位置基本不动。不能仅因RPC accepted就说鸭子已经能做该动作。
- 当前实际模型 `Mjlab-VelStand-Rough-Backlash-MicroDuck`，SHA256 `1cbf8730eadd75a5704332c9f3c10f60bfa9412135b907831c9dbd731ce1795f`。从设备完整导出合同的训练快照核实：`body_pose_tracking.weight=0.0`，`head_pose_tracking.weight=2.0`；没有后续启用身体跟踪奖励的课程项。
- 精确匹配该SHA de 本地ONNX离线反事实推理：roll从0改为+.04，EsquerdoDireitohip_roll输出仅变+.000238/+.000453rad；最大Perna输出变化约.00765rad。这是单步敏感性，不是物理rollout。
- 原生固定源码4734cbbPreservado身体z/roll/pitch至观测57–59，stand槽为空时仍送给walkModelo，不会因此丢弃身体指令。主要限制在AtualModelo de 训练目标；摩擦/死区可能是额外因素，尚未单独定量。

因此，本轮早先“接口suporta即可沿用现有Modelo做身体律动” de 假设不成立。可靠身体跟拍é necessário独立Validação具备身体跟踪能力 de Modelo，不能por meio de接语音大Modelo、放大指令或删除保护来宣称解决。

## 候选Modelo e Controle权边界

本地 `firmware/policies/stand/policy.onnx` 的HD1910恢复教师（SHA256 `a481d9f211f31d9476ab1a319fe362a21ef0879d9fa59442a122845af598268c`）有身体跟踪训练课程，硬件/home/顺序/dim与现模型匹配，离线body输入响应明显。但其角色为teacher_only、deployment_verified=false，README明确不应自动放入零速stand槽；stand槽会影响所有低速/停止姿态。只列为仿真候选，**未启用或替换**。

实体手柄闲置共存仍需原生通道所有权/接管Protocolo：现有raw tap不提供原生head/body/IMU模式，且停止清理可能 e 手柄Gravação竞争。本轮Preservado保护。前一版6ca5459Web音乐会话离开前台会结束；Usuário随后明确要求后台持续，已在29b9400Concluído独立生命周期并部署，见[后台ExecuçãoValidação](2026-10-26-background-music.md)。声音检测 e 身体Modelo能力仍按本页证据单独验收。

后续先核对真实音乐 de 可靠节拍/头嘴表现；身体Modelo按Usuário选择另做仿真 e 验收。未接豆包/Jev、未重烧Imagem或发布OTA。

数值与部署证据：根工作区 `artifacts/music-local-fix-20261026/`；最终语音Linux检查在 `artifacts/audio-interaction-20261025/linux-tests-2f24a6ae7b.json`。
