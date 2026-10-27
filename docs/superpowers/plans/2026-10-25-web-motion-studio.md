# Web motion recording, playback and lively head motions

> **For agentic workers:** Use subagent-driven-development for bounded backend implementation, then independent spec and code review. Work in this isolated worktree. The human authorized implementation (“开始吧…灵动…先做在网页版里头”). Do not repeat an execution or approval question.

**Goal:** Add a complete recording/library/playback flow and a lively head/mouth mode to Studio's existing web remote controls.

**Architecture:** A versioned, bounded recording library and single-owner motion session live in independent modules. Integrate only at PadOps' already-checked intent/request boundaries and lifecycle hooks. All movement continues through robotd; the lively mode adapts the old servo-page gesture style to head/mouth intents, without opening the servo bus. Store generated intent samples so recorded lively motions replay deterministically.

**Tech Stack:** Existing Python 3.13/Starlette, Preact/HTM, PadOps locks/leases, unittest, fake robotd, Edge/CDP browser harness. No new runtime dependency.

## Scope and behavior

- Preserve the 10-24 recording design: webpage controls, one clip up to 60s, 20 saved clips, 6,000 events/1MiB per file; name up to 32 characters; playback 1/3/5 times; pause/resume, finish/save/discard, rename/delete. No import/export, editing, infinite loop or video/audio recording.
- Recording captures only accepted whitelisted movement/head/body/mouth intents and known sound/skill requests, plus relative monotonic time. Never save robot init/enable/sit/relax/config operations. A preparation-state change ends the session rather than replaying it later.
- Validate type/range/finiteness, file/schema/IDs, timestamps and duration when loading. Use atomic file replacement; storage is below Studio state dir. Snapshot list errors explicitly; file corruption must not crash existing pad control.
- Fingerprint relevant actual policies/config/limits. Reject replay after incompatible model/config changes, including overwritten model files where accessible. Do not hash changing enabled/sitting telemetry as identity.
- One owning web connection, one recording/playback session. Heartbeats every100ms with a per-session token; >500ms without a matching heartbeat stops automated output. Old heartbeats/late worker requests cannot revive a closed session.
- Navigation, hiding, viewport exit, websocket loss, physical pad attachment, takeover, relax, invalid/stale robot state, close and manual takeover stop automation. Reconnection never resumes playback. Ordinary manual controls during playback stop it before issuing their own commands.
- Pause/stop/completion clear velocity and all automated head/body/mouth/held-sound latches through the existing ordering. A started skill's physical cancellation is not assumed; preserve completion barriers for ordinary pause, distinguish emergency relax, and reject unsupported skill recording if lifecycle completion cannot be verified. No catch-up bursts of late events.
- Lively mode: randomized small head/mouth gestures based on existing servo_ops.GESTURES; no leg commands or automatic torque enable. Requires existing ready/running policy, fresh state and no physical-pad conflict. Generated goals go through the same gates; low-amplitude smooth samples, interruptible between samples. May run during recording. Playback and lively mode cannot compete.

## Frontend/backend contract

Use existing `link.cmd('pad.op', args)` with `args.op='motion'`, `args.action` in:

```javascript
{op:'motion', action:'record_start'}
{op:'motion', action:'record_pause'|'record_resume'|'record_finish'|'discard'}
{op:'motion', action:'save', name:'展示一号'}
{op:'motion', action:'play', id:'recording-id', loops:1}
{op:'motion', action:'pause'|'resume'|'stop'}
{op:'motion', action:'rename', id:'recording-id', name:'新的名字'}
{op:'motion', action:'delete', id:'recording-id'}
{op:'motion', action:'idle_start'|'idle_stop'}
{op:'motion', action:'heartbeat', session_id:'returned-session-token'}
```

Return `session_id` for session starts and keep it in `pad.motion_studio`. Snapshot shape:

```javascript
{
  state:'idle', // recording, record_paused, draft, playing, play_paused, idle_motion
  session_id:null, owner:null, // owner={mine:boolean,by:string}
  elapsed_s:0, duration_s:0, loop:0, loops:1,
  recordings:[{id:'id',name:'name',duration_s:1.2,events:30}],
  draft:null, // {duration_s,events,reason}
  record_available:{ok:false,why:'先站起来并准备好走'},
  idle_available:{ok:false,why:'先站起来并准备好走'},
  last_result:null, error:null,
  idle_running:false
}
```

Frontend tolerates missing capabilities on old backends and reports unavailable. Existing pad.motion continues describing the original remote controls; do not rename it.

## Task 1 — Baseline and isolated implementation

Files: existing `software/studio/tests/test_pad.py`, new backend tests, no changes to runtime/robot services.

- [x] Run baseline 159 pad backend tests from `software/studio`:

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_pad'])"
```

- [x] Add failing `tests/test_motion_studio.py` tests for actual accepted events, corrupted/oversized files, reload persistence, nonfinite/unknown commands, timeline ordering, pause-excluded time, policy identity change, heartbeat expiry, stale-token rejection and deterministic lively recording.
- [x] Implement `studio/motion_store.py` for validation/storage and `studio/motion_studio.py` for session/lively scheduling. Integrate narrowly into `pad.py`/`pad_drive.py`; never add the whole implementation to those large files.
- [x] Validate accepted movement + sound + safe known skill paths, resets, current driver ownership and real outgoing methods, not only mock call counts. Fail explicitly for unsupported physical skill-cancellation semantics.
- [x] Run new backend tests and the baseline; inspect locks/close races; commit only this feature's backend files after review.

## Task 2 — Web controls and interaction

Files: new `web/motion-studio.js`, new `web/motion-studio.css`, small integration in `web/pad.js`, corresponding Node/browser tests.

- [x] Add a failing browser scenario exercising complete record → manual action → finish → name/save → select/play → pause/resume/stop → rename/delete. Assert fake robotd actually received accepted events in order. Add lifecycle and 320/390px layout checks.
- [x] Add an inline “动作录制与回放” section within Remote. Show clear running/draft/error/owner state, duration, progress, loop counts and an adjacent “灵动” switch. Keep physical-pad/robot-readiness explanations visible.
- [x] Heartbeat the owning session only while the existing remote is active and link connected. Stop heartbeat and send termination when hidden/inactive/unmounted. Use session_id so delayed callbacks do not control another session.
- [x] Keep save/rename forms inline and explicit, no fake success, no arbitrary paths or programming controls. Disable conflicting session mutations while pending and retain unsaved drafts honestly.
- [x] Run browser flow on desktop/390/320px; inspect screenshots for overlap/overflow and existing controls regression.

## Task 3 — Independent review and fixes

- [x] Spec review: compare implemented behavior to this plan and the original 10-24 design, particularly control lifetime and recording actual accepted output.
- [x] Code-quality review after spec issues are closed: locks, thread lifecycle, file boundaries, validation, CPU work at idle, UI async cancellation.
- [x] Fix findings with reproducing tests, rerun affected suites, then full relevant Studio backend/HTTP/virtual-pad/sensor browser regression.

## Task 4 — Delivery and project records

- [x] Update Studio README and feature ledger with exact local versus board/image acceptance. Include source/verification artifact paths and limits.
- [x] Integrate reviewed feature commits into studio-dev while preserving its current uncommitted roadmap/voice notes. Do not overwrite those files by resetting the checkout.
- [x] The human subsequently chose the existing duck control URL. Back up runtime files and user state, verify compatibility and stationary control state, update only Studio runtime files, restart only microduck-studio, and verify hashes/HTTP/snapshot and unchanged robotd/padd/voice process identities. Open the real control URL without issuing automatic movement. No image rebuild or automatic updater change. Installed hashes and HTTP passed; authenticated live snapshot remains behind existing login, not bypassed. UI opening was queued by the app; native browser was minimized. Actual motion acceptance is pending the human's trial.
- [x] Record feature state and packaging follow-up; leave a reproducible test/installation path for subsequent board acceptance.

Delivered runtime commit: c18783c9a2b2e2635124c6c4d53007e3fefb3ba6. Evidence, limits and deployment backup are recorded in [verification](../verification/2026-10-25-web-motion-studio.md). No action-generating test was sent to the actual robot; local browser end-to-end testing used fake robotd.

Follow-up from the human's actual screenshot: the entry is visible, but the skill reset gate incorrectly treated robot.policies.enabled (startup configuration) as live enable state. Runtime fix db970dd470f7cc1586b1ce3a4ed6a2792b1f71ce uses fresh bus.policy_enabled stop evidence while retaining a later verified ready transition. Two new backend regressions and a real-Studio browser recovery sequence passed; all 205 pad/motion backend checks and the complete motion browser flow passed, independent review found no remaining issue. Deployed only motion_studio.py and restarted only Studio, preserving all 12 current user-state files and all control/voice process identities. See the verification follow-up for exact backup and boundaries; physical motion acceptance remains pending.
