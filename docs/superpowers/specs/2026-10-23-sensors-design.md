# Studio 摄像头与 ToF

用户提出新增摄像头、ToF，并明确确认：两项放在左侧导航的「手柄」和「舵机」之间，分别作为独立页面，提供画面、读数和连接状态。继续仅本地开发，不连接或更新板子。

## 页面与范围

- 导航为总览、手柄、摄像头、ToF、舵机、IMU、模型、日志、设置。手机也能进入这两页，触控入口保持可用。
- 摄像头页接现有 mediad 的 LAN WebRTC 视频信令（默认8443）。不嵌入带运动控制的旧控制台。页面能开始/停止预览、重新连接，显示连接/协商/播放/失败、实际视频尺寸和接收情况。初次进入自动连接，离开或隐藏页面关闭视频和信令，返回后重新连接。
- 摄像头来源区分配置中的 camera/test/未知，与运行端 producer simulated 元数据；配置来源不能冒充已验证的真实硬件。已有镜像默认为测试画面时明确提示。仅请求 media.video 元数据，不发送运动、改设置、录音或上传视频。
- ToF 页提供8×8距离热力图、有效格数、最近/最远有效距离、传感器型号和更新时间。每格可以查看毫米值及原始状态；5/9且距离>0才为有效，255为无目标，其余为无效；不把无目标/错误画成0mm障碍。
- ToF 使用现有 tofd 的 tof.stream 只读接口，按需取最新帧；后台/离开停止轮询，不持续占用串口或运动RPC。几何固定8×8，严格校验数组、数值、消息大小及读超时；缺传感器、服务不在线、等待首帧、坏数据和断开分别说明。
- 本轮不增加避障/导航、不改变舵机或运动保护、不启动/重启系统服务、不修改镜像配置。服务不可用如实显示，不能用演示数据冒充硬件。

## 边界与架构

Studio 新增 sensors.py，提供配置只读汇总 CameraInfo 与按需 ToF 快照。HTTP 端点 GET /api/camera 和 GET /api/tof 均沿用现有登录/Host校验并no-store。ToF读使用独立连接、总超时和并发合并，不阻塞急停。ToF JSON上限64KiB，不接受任意客户端地址。CLI提供受控的开发/安装地址配置，不在网页接受socket或URL。

CameraInfo: `{source:'camera'|'test'|'unknown', source_label, source_basis:'config', source_verified:false, signaling_port:8443, error:null}`。默认HTTP成功只代表读到了配置；实际视频状态由浏览器与mediad握手及视频播放确认。配置找不到时仍可尝试信令，不把配置缺失当摄像头缺失。

ToFView: `{state:'ready'|'unavailable'|'waiting'|'error', connected, sensor, reason, rows:8,cols:8,hz, seq, age_ms, distance_mm:[64],status:[64],valid_count,nearest_mm,farthest_mm, zones:[{kind:'range'|'no_target'|'unusable',mm,status}], simulated:false}`。运行端 sensor 为 sim/fake 时 simulated 必须为 true。没有有效帧时数组为空/统计为空，不能显示旧数值为当前值。tofd 不支持 hello，连接后直接请求 tof.stream。

WebRTC 客户端独立 camera-link.js，复用现有 GStreamer welcome/list/startSession/sessionStarted/peer/endSession 协议。严格对应sessionId，串行处理SDP/ICE，RTCDataChannel只发送media.video读请求；不导入旧控制台的控制部分。媒体/信令均有失败状态、停止释放、隐藏释放和超时；候选/协商消息有大小界限。没有可识别本机producer时明确失败。

## 验证

先写失败用例再实现：ToF有效/无目标/无效/负距、数组错误、首帧超时、断连、读合并和socket释放；相机来源配置、只读HTTP会话保护；WebRTC信令顺序与视频状态真实回读、错误/停止释放/重连；浏览器两页导航、8×8图、空/错误态、离开/后台停止请求、手机布局。测试可使用明确标记的假传感器和视频流。真机验收留待用户另行确认连接后进行。
