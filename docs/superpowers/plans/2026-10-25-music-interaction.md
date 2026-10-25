# Music Interaction Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development, with specification and code quality reviews before deployment.

**Goal:** 外放音乐时鸭子随节拍小幅律动，听到明确提问后按音乐感觉发出叫声。

**Architecture:** 沿用 continuous_audio 的单路 PCM，MusicFeel 提取节拍；专门的本地流式问题识别与普通坐站识别互斥处理音频。私有 Unix socket 提供有界状态与开关，Studio 复用网页动作会话的优先级和心跳发出头/身体意图。

**Tech Stack:** 标准库、现有 Vosk Model、AF_UNIX、Studio Python/JavaScript。

用户后续修正：实际开启监听短叫一次，日常模式默认duck原生回应，不原样复读。录音复读保留为显式echo/record独立功能，单独按键这轮不做。此修正优先于早期“普通话语继续复读”的过渡设计。

### 1. 感知与问题识别

- [ ] `music_feel.py`/tests：20ms RMS 起音、8秒/64点上限、BPM/节拍新鲜度、轻快/低沉/摇摆/不确定、明确提问白名单。快慢不等同准确曲风。模拟75/125BPM、摇摆、恒定噪声、静音、变速、错误声道必须分别覆盖。
- [ ] `music_interaction.py`/tests：复用 Vosk Model，单独有界流式提问队列；允许背景音乐未静音时对稳定完整问题作回应，partial词置信度至少0.8，完整白名单稳定0.5秒，4秒防重复。音乐模式不把整段歌曲当普通复读或坐站口令。每次回应经 ContinuousAudio 抑制自身音频，使用提问前的近期可靠节奏。清空队列或丢帧重置识别状态，不能保留任意转写。

### 2. 本地控制服务

- [ ] `audio_control.py`/tests：`/run/duck-echo/control.sock`，0600，有界JSON单请求，方法只有 status 和 set；只能开关监听、音乐模式，不能接受任意机器人命令。状态只有开关、节奏和故障，无PCM或对话文本。启动默认关闭。R3与网页修改使用同一真实active状态，关闭/Select/断开取消。web音乐可以在实体手柄关闭时开启麦克风。
- [ ] 集成 daemon 保持主线程能处理无手柄状态和重连；套接字退出收尾；unit使用 RuntimeDirectory，安装manifest含所有模块。测试开关竞争、输入过大、无效字段、关闭后旧问题不叫。

### 3. 网页与律动

- [ ] Studio本地客户端在后台取状态，快照不阻塞事件循环；已认证的 pad.op 提供监听和音乐入口。
- [ ] MotionStudio新增音乐会话/节拍采样，沿用动作准备、心跳、失联、实体手柄接管和坐站屏障；只发小幅头/身体意图，不自动上力或启动策略。人工手柄连接时网页律动暂停并显示原因；用户关掉实体手柄后可在网页开启听音乐。没有可靠节拍先等待；声音/状态过期停止输出并清理锁存。
- [ ] 现有手柄页在录制面板旁显示“语音/听音乐”开关、监听状态、BPM和粗略音乐感觉；停止、页面离开、急停仍按现有流程。

### 4. 验证和发布

- [ ] Python单元+Linux假ALSA/假机器人IPC、前端和浏览器检查；验证模式之间切换与反馈抑制。
- [ ] 冻结组件包、文件hash、设备原文件备份，停止状态下只重启必要服务；核对robotd/padd进程不变，记录负载温度与剩余真人验收。
- [ ] 总账F16/17更新，新增音乐律动/音乐问答编号，明确软件验证和真人音乐混响验收边界。
