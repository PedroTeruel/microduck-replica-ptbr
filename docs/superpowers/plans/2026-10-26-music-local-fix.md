# 本地音乐跟拍修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. 按下列任务顺序执行，每项先运行失败回归，再实现并审查。

**Goal:** 修复真实麦克风音乐下节拍无法稳定驱动头/身体的问题，明确等待节拍与实际运动状态，验证实体手柄的接管边界。

**Architecture:** 保留单路麦克风、现有 robot.head/robot.pose 接口和运动策略。采集请求20ms周期；节拍使用按样本推进的有限音量包络及周期性证据，对不稳定输入不生成动作。网页端继续保留录制/回放原有保护，音乐控制权仅在证据充分时允许闲置手柄，不删除通用保护。

**Tech Stack:** Python 标准库、ALSA arecord、Studio Python/Preact、现有 Unix RPC 与旁路手柄数据。

## 已取得证据

2026-10-26 用户在播放音乐时进行两组8秒只保存数值的采集：默认周期6000帧/125ms；请求 `--period-time=20000 --buffer-time=80000` 后实际周期960帧/20ms，均正常结束。小周期真实音乐的旧检测器0个稳定快照；同段音量包络在约0.6s延迟存在重复性，不能仅靠相邻帧1.65倍增幅定位鼓点。证据在根工作区 artifacts/music-local-fix-20261026/capture-ab.json，PCM没有落盘。

## 任务1：采集时间轴与真实音乐节拍

Files: `software/duck-echo/continuous_audio.py`, `music_feel.py`, `test_music_feel.py`, `test_alsa_linux.py`；如需额外测试可新增同目录 `test_music_timing.py`。

- [ ] 加入先失败回归：同一固定PCM、20ms均匀输入和125ms成批输入应获得相近BPM与有效且不在未来的last_beat；输入分块边界不得改变能量时间线。
- [ ] 加入真实音乐的数值包络回归（取capture-ab的小周期一段）；BPM须来自重复证据，非固定100/120。保留强鼓点75/125、摇摆、持续等音量、静音/过期、换速等原有用例。
- [ ] capture请求20ms period/80ms buffer；验证语音分句/提示声/取消不回退。有限窗口周期估计在无可靠节奏时保持unknown，并在停止声音后释放旧节拍。
- [ ] 对照测试命令：`python -X utf8 -m unittest test_music_feel test_music_timing test_continuous_audio`；全套 `python -X utf8 -m unittest discover -p 'test_*.py'`。设备Linux运行全部测试再部署。
- [ ] 提交任务代码；独立规格审查后做质量审查，修复重要问题。

## 任务2：动作链路与可见状态

Files: `software/studio/studio/audio_interaction.py`, `motion_studio.py`, `pad.py`, `pad_drive.py`（仅有必要时）、`web/motion-studio.js`, `web/audio-interaction.js`, 匹配测试。

- [ ] 追踪真实控制权与发送路径；确认姿态、BPM、动作会话及robot.pose回读，先定位再改。
- [ ] 将等待稳定节拍显示为明确状态，避免只显示“随乐律动中”却没有任何动作。对状态失效、静音与停止开关验证头回正/pose inactive。
- [ ] 手柄仅连接与主动输入分开；先检查原生padd空闲模式是否持续写head/pose。仅当可确认不争写且旁路新鲜时允许音乐运行，实际操作取消当前音乐；保持急停与录放原有规则。若缺少模式证据，明确其协议缺口，不凭连接状态一刀切删除保护。
- [ ] 运行受影响Studio后端与Node测试。只更新Studio需先检查设备停好条件，保存用户状态与进程身份。
- [ ] 提交并作规格、质量审查。

## 任务3：上机、复核与记录

- [ ] 使用固定提交与哈希部署语音组件，运行设备Linux测试、保存回退备份，只重启必要服务。
- [ ] 回读实际ALSA period、节拍新鲜度/BPM/置信度；必要时用用户正在播放的音乐复测，避免把假麦克风结果当实际通过。
- [ ] 验证网页等待/运动/停止状态与真实头/身体输出；物理动作由用户确认，不用文件存在替代验收。
- [ ] 更新软件功能总账F24/F25与验证记录，分别记录已修代码、已部署、真机通过和尚缺内容。
