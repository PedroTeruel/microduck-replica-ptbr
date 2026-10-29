# 音乐律动在Web后台持续Execução

Usuário明确要求“后台也持续工作”。现有实现把音乐律动放入前台遥控会话，blur、滚出区域、动作500ms心跳缺失会结束；因此Usuário切到聊天后，音乐采集继续但动作停止。本轮将独立音乐律动交给StudioServiço端持续调度。

## 方案选择

采用Serviço端管理已有独立音乐会话：后台Web不é necessário高频发送动作心跳。继续依赖浏览器计时器会受后台限速；独立新增常驻运动进程又会造成Controle权竞争，均不采用。使用已有有序发送锁、Modelo身份、停止 e  em 立清理机制。

## 行为 e 边界

- 仅独立`idle_motion + idle_kind=music`可在网页失焦、隐藏、滚出遥控区后继续；普通灵动、录制（包括录音乐）、回放、摇杆和按键规则不变。启动仍须登录、在遥控区、站稳且策略就绪、实体手柄断开、状态新鲜。
- 原WebWebSocket真正断开、显式停止音乐律动/R3关闭监听或音乐模式、实体手柄连Superior、另一个Web接管/人工动作开始、急停/卸力、策略/Modelo变化、关键状态失效时，结束会话并清理一次。恢复Fonte或Conexão不自动复活旧会话。暂não suporta关闭Página后继续。
- Serviço端必须独立维持新鲜 de 机器人反馈 e 实体手柄状态，不可跳过原有新鲜度/扭矩/姿态Verificação。音乐Fonte未知节拍时等待；不合成假节拍、不更换运动Modelo。
- 同一Página后台仍可被其它Página接管；后台音乐不能重新夺回已转移 de Controle权。清理 e 输出使用现有有序锁，停止后不得发送已排队旧音乐帧。
- 前端在后台音乐会话 em 不因blur/activity失活主动发送stop，也不继续假装发送高频心跳；断线仍 em 断。返回Página显示Atual会话/节拍状态，提供停止入口。Instruções文案明确后台继续、断开停止。
- 同一WebSocket内切换`/pad`与`/logs`等路由也保留已经确认的独立音乐会话。未确认启动的页面销毁、真正断线及过期回复使用会话token隔离。
- 通用网页30秒应用心跳超时保持。独立音乐所有者在JavaScript心跳暂停时，通过本地`studio.ws_protocol`提供的原生WebSocket Ping/Pong确认连接存活：随机匹配payload，最多等5秒，失败即关闭并结束会话。不编辑vendored依赖、不伪造应用心跳或观测者活动。

## Validação

先用FalhaTeste覆盖后台超过500mse10秒无人观看后 de 继续、前台普通会话仍停止、断开/接管/手柄/失效/音源关闭停且不复活。ProtocoloTeste覆盖正确/错误/缺失Ponge父Protocolo事件处理；本地真实Edge过滤JavaScript应用心跳，保持原生Pong，切日志页超过30秒后仍有输出，返回可停止，真正断开后不复活。真机只做已站稳策略Execução条件Inferior de 小幅Cabeça音乐动作观察。不将接口accepted或假机器人输出当成实物动作验收。现用Modelo未训练身体姿态跟随，仍如实标记身体限制。

## 范围

本轮只更改音乐会话生命周期，不改DSPAlgoritmos、Controle幅度、Modelo、Rede、ServoParâmetros或音频录放。停止条件eDados状态Validação优先于后台持续。
