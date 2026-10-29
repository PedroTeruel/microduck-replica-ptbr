# Studio 摄像头 e  ToF

Usuário提出新增摄像头、ToF，并明确确认：两项放在Esquerdo侧导航 de 「手柄」e「Servo」之间，分别作为独立Página，提供画面、读数eConexão状态。继续仅本地开发，不Conexão或Atualização板子。

## Página e 范围

- 导航为总览、手柄、摄像头、ToF、Servo、IMU、Modelo、日志、设置。手机也能进入这两页，触控入口保持可用。
- 摄像头页接现有 mediad  de  LAN WebRTC 视频信令（默认8443）。不嵌入带运动Controle de 旧Controle台。Página能开始/停止预览、重新Conexão，显示Conexão/协商/播放/Falha、实际视频尺寸e接收情况。初次进入自动Conexão，离开或隐藏Página关闭视频e信令，返回后重新Conexão。
- 摄像头Fonte区分Configuração em  de  camera/test/未知， e Execução端 producer simulated 元Dados；ConfiguraçãoFonte不能冒充已Validação de 真实Hardware。已有Imagem默认为Teste画面时明确提示。仅Por favor求 media.video 元Dados，不发送运动、改设置、录音或Enviar视频。
- ToF 页提供8×8距离热力图、有效格数、最近/最远有效距离、传感器型号eAtualização时间。每格pode查看毫米值 e original状态；5/9且距离>0才为有效，255为无目标，其余为无效；不把无目标/错误画成0mm障碍。
- ToF 使用现有 tofd  de  tof.stream 只读接口，按需取最新帧；后台/离开停止轮询，不持续占用串口或运动RPC。几何固定8×8，严格校验数组、数值、消息大小 e 读超时；缺传感器、Serviço不在线、等待首帧、坏Dadose断开分别Instruções。
- 本轮不增加避障/导航、不改变Servo或运动保护、不Inicialização/重启系统Serviço、不修改ImagemConfiguração。Serviço不可用如实显示，不能用演示Dados冒充Hardware。

## 边界 e 架构

Studio 新增 sensors.py，提供Configuração只读汇总 CameraInfo  e 按需 ToF 快照。HTTP 端点 GET /api/camera e GET /api/tof 均沿用现有登录/Host校验并no-store。ToF读使用独立Conexão、总超时e并发合并，不阻塞急停。ToF JSONSuperior限64KiB，不接受任意客户端地址。CLI提供受控 de 开发/Instalação地址Configuração，不在Web接受socket或URL。

CameraInfo: `{source:'camera'|'test'|'unknown', source_label, source_basis:'config', source_verified:false, signaling_port:8443, error:null}`。默认HTTP成功只代表读到了配置；实际视频状态由浏览器与mediad握手及视频播放确认。配置找不到时仍可尝试信令，不把配置缺失当摄像头缺失。

ToFView: `{state:'ready'|'unavailable'|'waiting'|'error', connected, sensor, reason, rows:8,cols:8,hz, seq, age_ms, distance_mm:[64],status:[64],valid_count,nearest_mm,farthest_mm, zones:[{kind:'range'|'no_target'|'unusable',mm,status}], simulated:false}`。运行端 sensor 为 sim/fake 时 simulated 必须为 true。没有有效帧时数组为空/统计为空，不能显示旧数值为当前值。tofd 不支持 hello，连接后直接请求 tof.stream。

WebRTC 客户端独立 camera-link.js，复用现有 GStreamer welcome/list/startSession/sessionStarted/peer/endSession Protocolo。严格对应sessionId，串行处理SDP/ICE，RTCDataChannel只发送media.video读Por favor求；不导入旧Controle台 de Controle部分。媒体/信令均有Falha状态、停止释放、隐藏释放e超时；候选/协商消息有大小界限。没有可识别本机producer时明确Falha。

## Validação

先写Falha用例再实现：ToF有效/无目标/无效/负距、数组错误、首帧超时、断连、读合并esocket释放；相机FonteConfiguração、只读HTTP会话保护；WebRTC信令顺序 e 视频状态真实回读、错误/停止释放/重连；浏览器两页导航、8×8图、空/错误态、离开/后台停止Por favor求、手机布局。Teste可使用明确标记 de 假传感器e视频流。真机验收留待Usuário另行确认Conexão后进行。
