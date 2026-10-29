# 鸭子麦克风复读（2026-10-25）

用户授权自行选择交互、通过 SSH 部署并验证，不重新烧录。实现为独立的 Python 3 服务，安装位置 `/opt/duck-echo`，不修改或重启 robotd、padd，不发送运动指令。

## 交互 e 范围

选用按住Direito摇杆按钮 R3（Linux BTN_THUMBR=318）录音，松开复读；最长 10 秒，过短按压不播放。默认把采集到 de Direito声道提升到 1.25 倍播放采样率，产生轻微变调。原声模式可Configuração为 1.0。按住新一轮时 em 断Superior一轮播放。断开手柄或Serviço停止时丢弃正在录制 de 片段。

另提供 `probe`（有限录音并报告电平）、`record --seconds 4`（定时录音并复读）、`devices`（读取可用手柄）命令。声音留在内存，不保存对话文件，不访问云端。

候选方案：按住录音易于Controle且避免录到喇叭自身；按一Inferior开始、再按结束容易忘关；自动检测讲话é necessário额外噪声门 e 回声处理。本次采用第一种。

## 音频 e 输入

ALSA 使用 `arecord -t raw -f S16_LE -c 2 -r 48000` 采样，由读取线程收集最多 10 秒数据；Mic3R 是已有 HAT 初始化脚本选择的右声道。播放取右声道并复制到两声道，使用 aplay 播放。采集进程异常、声卡忙碌或录音静音必须记录清楚，不声称音频成功。原始 PCM 与播放子进程有明确长度限制和退出期限。

por meio de evdev 只读旁听实体手柄，不执行 EVIOCGRAB，不占用 padd。Inicialização时Se按钮已经按住，必须先松开才接受Inferior一次按Inferior。按键重复不重复开始；输入缓冲溢出或拔出取消录音。无手柄时定期检测热插拔。

## Instalação e 验收计划

- [x] 先写 PCM 声道、电平、状态机 e  evdev 事件Teste；确认缺少实现而Falha。
- [x] 实现 PCM 处理、有限录音/播放、R3 状态机、热插拔监听 e Comando行。
- [x] 提供 systemd 单元、麦克风通路准备、Instalação/卸载脚本；卸载恢复Instalação前采集设置。
- [x] 在本机Execução全部单元TesteeComando行帮助，Verificação Python 语法 e 脚本换行。
- [x] SSH 连通后先核对 hostname、声卡、Serviço、手柄设备，记录原状态。
- [x] Enviar独立Diretório，执行麦克风 probe，核查非零电平；执行有限录放后再Inicialização R3 Serviço。
- [x] Verificação新Serviço日志，并复核 robotd/padd  de 进程eExecução状态。真实说话 e 按键试听须在实际HardwareSuperior验收，离线Teste不能代替。

## 初始Conexão排查

2026-10-25 初始扫描未找到 TCP 22，Wi-Fi 列表 em 未见 Microduck Ponto de acesso。Usuário确认开机后，重新发现 duck-0de6 位于 192.168.0.102。核对Histórico主机密钥后，使用Usuário提供 de Atual登录资料Conexão；登录密码未Gravação项目Arquivo。

## 离线Validação e 审查

- Ubuntu 22.04 / Python 3.10：25 项Testepor meio de，包含真实子进程驱动 de 模拟录放、限时、断线、声卡忙碌、两种麦克风控件命名、备份生命周期、升级Falha恢复。
- `systemd-analyze verify` 以 0644 权限的临时 service 文件运行，退出码 0。
- 项目 `microduck/deploy/audio/aic3104-i2c3.dts` 明确选用通用 aic3x compatible，控件名为 Mic3R；codec 驱动的 AIC3104 专用分支使用 Mic2R。安装时按实际控件列表识别，不依赖猜测。
- 审查发现 de “重新Instalação错误沿用第一次备份”e“InstalaçãoFalha后采集设置没有恢复”均已用FalhaTeste重现，再修复Validação。
- Superior述为离线Validação；后续真机验收见Inferior文。

## 真机验收

- 设备 duck-0de6，aarch64，aic3104 声卡，Mic3R 控件存在。
- 麦克风 probe Sucesso，随后有限录音得到约 2.876 秒 de 有效音频，RMS 1233.255、-28.5 dBFS；变调回放进程退出码 0。
- `/opt/duck-echo` 已安装，duck-echo.service active/running、enabled，运行用户 radxa，未发生服务自动重启。
- 原先配对 de  Pro Controller 回连Sucesso，Serviço识别 Nintendo Switch Pro Controller /dev/input/event4，R3 事件编号 318。
- 日志连续记录多次真实 R3 录放，片段约 0.75–2.125 秒，均Concluído回放。Usuário明确回复“pode”，确认听到鸭子复读。
- Instalação前后 robotd PID 1090、padd PID 1128  e Inicialização时间未变；健康状态 healthy，Controle环 50 Hz，bus ok、imu ready。
- 已设置开机启用，没有为Validação而重启整机。Preservado默认 1.25 倍音调/语速 e  10 秒录音Superior限。
- 证据位于工作区 artifacts/duck-echo-20261025  de  hardware-preflight.json、hardware-install.json、hardware-service.json；均不含登录密码或对话音频。
