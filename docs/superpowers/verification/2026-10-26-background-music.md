# Web后台音乐律动：实现、部署 e Validação

日期：2026-10-26（东京时间）。Usuário明确要求“后台也持续工作”。Software e 浏览器Verificaçãopor meio de，已por meio deSSH部署；最新45秒真实音乐观察仍没有Cabeça实动，整条实物链路尚未验收，不能将Software输出当成实物动作验收。

## 部署Versão e 行为

- 运行代码：Studio `29b940013e3542f9e87944db65e913d1a658f313`，核心实现`ad6651218cb7f138fb07069fcf3445586193a764`；后一个提交仅同步两处说明文案。语音服务仍为`2f24a6a`，本次没有改DSP、模型、幅度、网络或舵机参数。
- 只有独立 de 随乐律动由Serviço端持续管理。Web失焦、后台、滚出遥控区 e 同一WebSocket内站内导航继续；实际断开/关闭、明确停止、音源关闭或状态失效、实体手柄接管、人工输入/其它Página接管、急停/策略/Modelo变化会停止，旧会话不自动恢复。普通灵动、录制（包括录音乐）、回放、摇杆按键仍按原前台规则。
- 无网页观看时保留真实机器人遥测订阅；不伪造状态时间或应用心跳。新`studio.ws_protocol`沿用固定Uvicorn的事件处理，添加随机nonce匹配的原生Ping/Pong和5秒等待上限，独立音乐可在JavaScript心跳暂停超过30秒时继续，未确认连接则关闭。没有编辑vendored依赖。
- 每帧发送前重查真实安全状态；先发头部后若遥测过期或监听关闭，不再发送排队的身体帧。音乐会话只清理一次；原有接管`_halt`的额外move0保留。

## Validação证据

- TDD复现：原版离开前台/500ms动作心跳/无人观看后停止；后台会话改后继续。另复现并修复排队输出期间遥测变旧或音源关闭仍发送Inferior一帧 de 竞态， e 显式停止 e Inicialização哈希计算竞态。
- 相关广覆盖Python308项por meio de（最终发送前竞态修复前）；最终聚焦103项por meio de，12.283秒；补充独立Python93项、Node20项por meio de。Windows部分旧HTTPTeste有既有AF_UNIX/资源Aviso，不将其代表Linux实物效果。
- 独立规格审查99项Python、16项Node e 4项HTTP/遥测集成por meio de；独立质量审查4项Protocoloe16项Nodepor meio de。核心 e 最终文案分别审查por meio de，没有重要未解决审查项。
- 本地真实EdgeCompleto流程por meio de，103.358秒，无Controle台错误：坐站录制/三轮回放/ em 止e窄屏Preservado；音乐无拍时等待；blur后14帧Cabeça输出；真实站内导航卸载组件、过滤JS应用心跳31.5秒后仍有20帧Cabeça输出，没有动作心跳；返回正确显示Execução状态；关闭监听 e 真正WebSocket关闭/重连均停止且不复活。这些为假机器人输出，不代表机身实动。
- 第一轮浏览器por meio de后台动作断言，后在390px截图等待超时；补充截图前置前台/绘制等待 e 尺寸稳定后ConcluídoSuperior述最终流程。最后两处文案改动仅做JS语法、20项Node e 差异审查，没有重复Completo动作流程。

## Superior机

- Usuário确认停Inferior站好，实际回读motion/control、homed=true、policy_enabled=false、全部关节反馈新鲜且速度为0；实体手柄断开。未补发HOME/使能或停机指令。
- 更新9个运行文件，备份`/home/radxa/.microduck-backups/web-background-music-20261026-be22c51564`。用户原有12个状态文件hash不变，所有安装文件hash与冻结版本相同。
- Studio PID11672 active；robotd1097、padd1135、duck-echo6325 e Inicialização时间在WebAtualização前后完全相同。语音仅在更早 de 独立收音诊断 em 重启，本次部署没有重启语音/运动核心。
- 8项HTTP/健康/静态ArquivoVerificação200，JS/CSSServiço字节hash匹配且no-cache。真实WebSocket快照仍要求登录；没有绕过鉴权。
- Usuário刷新并回复“已开启”后观察45秒，450项反馈全部新鲜、运动策略全部开启、无Controle周期错误；136项节拍有效（约30%，BPM有66.7/136.4/142.9/200），Cabeça所有轴位置范围为0，身体也基本不动（仅两个关节一个编码计数变化）。因此真实动作仍未por meio de，不能声称后台功能在本机已Concluído动作验收。
- 随后只读原生订阅 em head指令已接近0，Studio日志显示无观看后停止遥测订阅，Instruções当时没有持续存活 de 后台音乐会话。日志同时包含Web人工移动/松开事件，但尚未确认这是会话结束原因，不能据此归因Usuário操作。正在Por favor求Web动作面板状态 e original提示，以区别未Inicialização、被接管/安全状态终止e节拍等待。
- Windows电脑操作尝试Leitura已有鸭子Web时，Ferramentas因无法可靠确认浏览器URL停止该通道；没有绕过该保护或登录，后续仅使用已授权SSHLeitura设备。WebUI状态仍待Usuário文字反馈。

## 原问题仍需分开验收

本轮实时外放输入RMS约327–2266，能观察到清晰声学变化；12秒DSP私有对照可检测24次起音，但现有RMS节拍只16/120项有效。另45秒记录149/450项有效，界面前台状态不确定，关节未动。因此“收到音乐”“识别稳定节拍”“后台会话存活”“Modelo让关节动”必须分别确认。aubio实验仍只在staging，没有接入生产。

AtualModelo身体跟踪奖励权重为0，前次短时直接头yaw实测可响应，身体基本不响应。详见[本地音乐调查](2026-10-26-local-music-fix.md)。这次后台生命周期修复不改变身体Modelo能力，也不等于增加了随乐嘴部动作。

根工作区证据：`artifacts/background-music-20261026/`；既有声音/模型探测在`artifacts/music-local-fix-20261026/`。
