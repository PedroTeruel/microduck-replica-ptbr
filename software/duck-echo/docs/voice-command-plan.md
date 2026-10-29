# R3  em 文语音动作（2026-10-25）

Usuário选择按住手柄键说话、松开执行，继续por meio de SSH Atualização。Preservado现有 R3 复读：明确识别到Sentar或Levantar时执行，其余话语继续复读。

## 设计

- 使用 Vosk small-cn-0.22 本地 em 文Modelo（Oficial约 42 MB），不Enviar录音。Modelo常驻后台识别线程，只在 R3 松开后处理一段有限录音。
- 采用小词表，Preservado未知语音、否定e引用形式。Completo听写在板端需 6–7 秒；小词表在同板 14 条合成语音Superior约 0.26–0.51 秒。
- 白名单仅SentareLevantar e 少量明确同义词。Completo句子去空白、标点后精确匹配；“不要Sentar”“Sentar再Levantar”e低置信度Resultado不触发动作，不采用模糊匹配。
- 普通说话、明确“复读”前缀e没有识别到口令 de 录音沿用复读。Inicialização新录音、手柄断线或退出Serviço时取消尚未执行 de 旧口令；处理超过 6 秒 de Resultado不得执行。录音达到 10 秒Superior限时取消本次，不自动执行。
- 每次执行先Leitura robot.policies e robot.busStatus。已经坐着时再次说Sentar不发送切换；已经站着时再次站起不切换。软着 de 站起走 robot.init；坐着且策略正常时站起走 sit_toggle。
- 从Ficar em pé保持状态Sentar，先Verificação已 HOME、扭矩确认，再清零速度、por meio de robot.enable 开启策略、等待读回后Por favor求 sit_toggle。主程序拒绝任何一步就停止；不改Firmware、运动Configuração、标定e安全闸。
- 坐着且已卸力时不强行初始化或绕过现有主程序 de 姿态规则。动作回执e目标坐立状态分别Verificação。
- 只修改 /opt/duck-echo e其Serviço；可关闭语音模式返回纯复读。Modelo、依赖隔离Instalação，运动Serviço不重启。

## Arquivo e Validação顺序

1. `voice_commands.py`：口令解析、有限 JSON-RPC、坐立状态动作；先写否定句、低置信度、幂等坐立和未知状态拒绝测试。
2. `speech_control.py`：Vosk 识别、有限队列、取消与过期；用真实模型和系统合成测试语音验证识别，用单元测试验证迟到结果不会执行。
3. `duck_echo.py`：仅在语音启用时挂接处理器；未启用时保留原行为；覆盖普通语句回退、超时取消和断线取消。
4. Instalação脚本 e Serviço：Instalação两个模块，隔离依赖 e ModeloCaminho，增加语音模式所需内存预算；por meio de现有回滚机制Atualização。
5. Linux Teste、真实ModeloTeste、ServiçoConfiguraçãoValidaçãoConcluído后Superior机。核对 CPU/内存、只读动作状态eModelo加载；先观察识别，再由真实 R3 口令ValidaçãoSentare站起，复核原运动进程没有重启。

## Fonte

- https://alphacephei.com/vosk/models
- https://alphacephei.com/vosk/install
- https://github.com/alphacep/vosk-api/blob/master/python/example/test_simple.py
- este projeto studio/pad_drive.py  de 站起/Sentar状态逻辑、studio/rpc.py  de  NDJSON RPC。

## 已Concluído de Validação e 部署

- SoftwareTeste 45 项por meio de（Linux 真实模拟 ALSA 子进程、状态机、口令、并发取消、Instalação回滚 e 离线依赖解包）。
- Windows 真实Modelo e 板端 ARM64 真实Modelo均Validação正向/否定/引用/普通语音；板端 14 条合成语音全部得到预期Comando或拒绝，峰值内存 144 MB。
- 板端 Python 3.13 没有 pip；使用 PyPI Oficial分发 de  ARM64/cp313 wheel，离线解包到 /opt/duck-echo/asr-deps，未改系统 Python 包。
- ModeloInstalação到 /opt/duck-echo/models，模式 ECHO_VOICE_MODE=actions 已开启，Serviço active，语音工作线程 ready，常驻内存约 123 MB。
- 运动Serviço robotd PID 1090、padd PID 1128  e 其Inicialização时间未变，Controle环约 50 Hz。
- 初始动作状态为未 HOME、扭矩关闭、sitting=false。先说“Levantar”会使用原生 robot.init；正常站起后再TesteSentar。
- 审查发现 de 实际 robot.policies slots[] 结构 e 输入溢出取消问题，均已先用FalhaTeste重现再修复。
- Usuário已明确回复“LevantareSentar都Sucesso”，真人 R3 语音 e 坐立动作验收Concluído；该结论来自Usuário反馈。
- 验收后 SSH 复查超时，绑定有线网卡扫描没有发现 SSH 主机，未取得这次真人动作对应 de 新日志。先前部署 e 识别日志Preservado，Rede间歇问题尚未排除；没有为排查Rede而改动声控或运动行为。
