# R3 Continuous Voice Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Each task receives specification and code quality review.

**Goal:** R3 单击开关持续语音，停顿后自动处理口令或复读。

**Architecture:** 新增有界分句器和持续 ALSA 输入控制器，复用 VoiceControl 与现有播放模块；保留 hold 路径用于回退。单一流接口为后续音乐分析提供入口。

**Tech Stack:** Python 标准库、ALSA arecord/aplay、现有 Vosk、evdev、unittest。

### Task 1: Continuous input and toggle

Files: `software/duck-echo/continuous_audio.py`, `test_continuous_audio.py`, `duck_echo.py`, existing tests.

- [ ] Write failing tests: one down/up pair enables; next down disables; repeat and duplicate down do nothing; initially held requires release; disconnect and overflow cancel queue; silence endpoints a phrase; maximum phrase splits without disabling session; own playback suppressed; bounded memory and capture exit.
- [ ] Run `python -X utf8 -m unittest test_continuous_audio` and record expected failures before implementation.
- [ ] Implement `ToggleButton` with `start/stop/tick` controller contract and `ContinuousAudio` using one arecord stream, bounded per-phrase buffer, explicit shutdown, selected microphone channel and injectable PCM segmentation.
- [ ] Add `--trigger-mode toggle|hold` (default toggle) and keep old hold operation available. Session off must clear recognition before playback, capture must never acquire an exclusive controller grab.
- [ ] Run affected tests and Linux fake ALSA integration; commit only component sources and tests.

### Task 2: Packaging and rollout

Files: `software/duck-echo/install.py`, `duck-echo.service`, `README.md`, feature ledger and verification note.

- [ ] Package new runtime module and configure trigger mode without losing existing voice/microphone settings.
- [ ] Test installation, rollback and both trigger modes. Review semantics, then code quality.
- [ ] Verify live unit, hardware devices and motion service identities. Stage frozen source and backup. Restart only duck-echo after checking no in-flight voice job; verify installed hashes, process and logs, leaving listening off.
- [ ] Document exact revision, test results, rollback location and user acceptance steps; continue music interaction from the shared stream.
