# Background Music Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement the lifecycle task with spec and quality review. Steps use checkbox syntax for tracking.

**Goal:** Only standalone music motion continues while its still-connected owner page is in the background.

**Architecture:** Reuse MotionStudio ordered session/output handling, but make the standalone music session server-timed. Keep an internal fresh robot-state subscription while it runs and preserve input arbitration. Browser inactivity stops manual inputs without killing this music session; actual disconnect and safety conditions still terminate it.

**Tech Stack:** Python3.13 Studio, existing Unix robot/audio clients, Preact and Node tests, local Edge fake-robot E2E.

## Task 1: Implement the complete lifecycle in the isolated worktree

Files to inspect/modify as necessary:
- `software/studio/studio/motion_studio.py`: narrowly identify standalone background music; skip only frontend activity/heartbeat gates; expose state for frontend; retain closed/invalid/model/source/robot/physical-pad checks and ordered cleanup.
- `software/studio/studio/pad_drive.py`, `pad.py`: distinguish drive-area leave from true disconnect, ownership and task-driven state polling.
- `software/studio/studio/robotd.py`, `app.py`: retain fresh telemetry via existing internal watcher mechanism if no browser watches.
- `software/studio/studio/ws_protocol.py`, `__main__.py`: studio-owned wsproto subclass exposes a native random-nonce Ping/Pong probe without vendored dependency edits; music-only application heartbeat exception is conditional on successful bounded5sec protocol liveness. Generic30sec behavior is preserved; no Pong means disconnect/cleanup.
- `software/studio/web/motion-studio.js`, `motion-heartbeat.js`, relevant activity code: music-specific inactivity handling, pending start/stop races, readable explanation.
- Relevant tests in `software/studio/tests/`, existing Node tests.

- [x] Reproduce with tests before editing production: start standalone music, mark owner drive area left, advance >.5s and >10s without browser heartbeat; session/output should survive with fresh simulated robot/audio data. Existing behavior must fail this assertion.
- [x] Add tests that recording+music, ordinary lively, playback still stop on inactivity/timeout; standalone music stops on actual disconnect, physical pad attached or unreadable, another controller taking ownership/manual operation, source-off, stale telemetry, policy/model changes and estop. Assert neutral cleanup occurs once and old queued output/heartbeat cannot revive.
- [x] Implement the narrow predicate and background path. Example interface (adapt to existing architecture):

```python
def background_music(self):
    s = self.session
    return bool(s and self.state == "idle_motion" and s.get("idle_kind") == "music")
```

All bypasses must depend on this predicate and only skip foreground/heartbeat gates. Do not let a general `invalidate()` ignore safety reasons. Handle fresh telemetry with an actual internal subscriber, not a fake fresh timestamp.

- [x] Add Node tests for no stop/heartbeats on music blur, ordinary blur still stopping, true disconnect and late start response cancellation.
- [x] Protocol/app tests must verify matched Pong, wrong Pong, missing Pong, connection loss/shutdown, inherited event dispatch, ordinary heartbeat deadline and JavaScript-silent music surviving native Pongs. Pending start cannot overwrite a competing explicit stop.
- [x] Run `py -3.13 -m unittest tests.test_audio_interaction tests.test_motion_studio` in `software/studio`, then relevant pad/server tests and `node --test` for changed Node modules. Inspect failures, self-review, commit only task files.
- [x] Independent spec review, fixes/review as needed; then independent quality review, fixes/review as needed.

## Task 2: Browser and device verification (root agent)

- [x] Exercise actual local Edge with fake robot/audio: stable music plus blur and `/logs` route/unmount with JavaScript heartbeat filtered >30s continues; native browser Pongs work independently of JS; returning renders active status; no music action heartbeat, source-off and real socket disconnect end with cleanup/no revival; ordinary record/replay baseline remains passing.
- [x] Recheck current device state and component identities. Stage frozen tested files with hash manifest and backup. Apply only when motion stopped/standing per current deployment contract; verify user-state hashes and core daemon identities unchanged.
- [ ] With music playing and current stable policy, verify received rhythm timestamps and real head feedback over a foreground→background interval; report head motion separately from known body-model limits. If a physical step needs user action, request only that action after all independent work is ready.
- [x] Update feature ledger/verification with exact revisions, checks, actual measured result and unresolved music-locking/body limits. Do not mark original music repair complete on software-only tests.

Physical follow-up: after user confirmed started,450 fresh45s samples showed no head position change although136 rhythm samples were valid. Session state/reason still needs confirmation; this physical step remains unchecked. Details: `../verification/2026-10-26-background-music.md`.
