# Background Music Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement the lifecycle task with spec and quality review. Steps use checkbox syntax for tracking.

**Goal:** Only standalone music motion continues while its still-connected owner page is in the background.

**Architecture:** Reuse MotionStudio ordered session/output handling, but make the standalone music session server-timed. Keep an internal fresh robot-state subscription while it runs and preserve input arbitration. Browser inactivity stops manual inputs without killing this music session; actual disconnect and safety conditions still terminate it.

**Tech Stack:** Python3.13 Studio, existing Unix robot/audio clients, Preact and Node tests, local Edge fake-robot E2E.

## Task 1: Implement the complete lifecycle in the isolated worktree

Files to inspect/modify as necessary:
- `software/studio/studio/motion_studio.py`: narrowly identify standalone background music; skip only frontend activity/heartbeat gates; expose state for frontend; retain closed/invalid/model/source/robot/physical-pad checks and ordered cleanup.
- `software/studio/studio/pad_drive.py`, `pad.py`: distinguish drive-area leave from true disconnect, ownership and task-driven state polling.
- `software/studio/studio/robotd.py`, `server.py`: retain fresh telemetry via existing internal watcher mechanism if no browser watches.
- `software/studio/web/motion-studio.js`, `motion-heartbeat.js`, relevant activity code: music-specific inactivity handling, pending start/stop races, readable explanation.
- Relevant tests in `software/studio/tests/`, existing Node tests.

- [ ] Reproduce with tests before editing production: start standalone music, mark owner drive area left, advance >.5s and >10s without browser heartbeat; session/output should survive with fresh simulated robot/audio data. Existing behavior must fail this assertion.
- [ ] Add tests that recording+music, ordinary lively, playback still stop on inactivity/timeout; standalone music stops on actual disconnect, physical pad attached or unreadable, another controller taking ownership/manual operation, source-off, stale telemetry, policy/model changes and estop. Assert neutral cleanup occurs once and old queued output/heartbeat cannot revive.
- [ ] Implement the narrow predicate and background path. Example interface (adapt to existing architecture):

```python
def background_music(self):
    s = self.session
    return bool(s and self.state == "idle_motion" and s.get("idle_kind") == "music")
```

All bypasses must depend on this predicate and only skip foreground/heartbeat gates. Do not let a general `invalidate()` ignore safety reasons. Handle fresh telemetry with an actual internal subscriber, not a fake fresh timestamp.

- [ ] Add Node tests for no stop/heartbeats on music blur, ordinary blur still stopping, true disconnect and late start response cancellation.
- [ ] Run `py -3.13 -m unittest tests.test_audio_interaction tests.test_motion_studio` in `software/studio`, then relevant pad/server tests and `node --test` for changed Node modules. Inspect failures, self-review, commit only task files.
- [ ] Independent spec review, fixes/review as needed; then independent quality review, fixes/review as needed.

## Task 2: Browser and device verification (root agent)

- [ ] Exercise actual local Edge with fake robot/audio: stable music plus page blur/activity hidden >10s continues; returning renders active status; stop, source-off, takeover and disconnect end with cleanup; ordinary record/replay baseline remains passing.
- [ ] Recheck current device state and component identities. Stage frozen tested files with hash manifest and backup. Apply only when motion stopped/standing per current deployment contract; verify user-state hashes and core daemon identities unchanged.
- [ ] With music playing and current stable policy, verify received rhythm timestamps and real head feedback over a foreground→background interval; report head motion separately from known body-model limits. If a physical step needs user action, request only that action after all independent work is ready.
- [ ] Update feature ledger/verification with exact revisions, checks, actual measured result and unresolved music-locking/body limits. Do not mark original music repair complete on software-only tests.
