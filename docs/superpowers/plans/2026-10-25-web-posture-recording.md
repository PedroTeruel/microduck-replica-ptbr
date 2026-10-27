# Web sit/stand recording implementation plan

> Use subagent-driven-development for the bounded backend implementation, then independent spec and code review. User explicitly authorized including sit and stand, and existing-site SSH deployment. Preserve the original checkout's untracked voice/UI records.

**Goal:** Save and replay sit→stand as actual target posture steps in the existing web recorder.

**Architecture:** A separate posture-step tracker consumes fresh robot.state phases and convergence evidence. MotionStudio integrates semantic steps and timeline barriers through narrow existing PadOps hooks. Existing robotd, padd, voice and bus ownership remain unchanged. See the adjacent [approved scope/design](../specs/2026-10-25-web-posture-recording-design.md).

**Tech:** Existing Python/Starlette, Preact/HTM, unittest, fake robotd and Edge/CDP. No new runtime dependency.

## Task 1 — Backend and executable regression

Owner: backend implementer. Files: new `software/studio/studio/motion_posture.py`, narrow edits to `motion_studio.py`, `motion_store.py`, `pad.py` (fresh view fields), `pad_drive.py` (checked accepted sit/stand hook); tests `test_motion_posture.py` and existing `test_motion_studio.py`; faithful sit/rise/stand phases in `dev/fake_robotd.py` without breaking ordinary fixtures.

- [x] Run baseline 205 checks using the command below. Add failing tests for the concrete user sequence and the design's evidence/lifecycle edges.
- [x] Implement explicit target steps `studio.posture {target:'sit'|'stand'}`, strict v2 validation with v1 compatibility, accepted-output recording, target-aware replay barriers, bounded completion wait, and session-fenced replies. Keep the tracker small and independent; no huge expansion of pad.py/pad_drive.py.
- [x] Add snapshot `posture_step: null | {target,label}` for visible execution/wait reason. Extra fields may be documented but preserve existing state/session fields and heartbeat behavior.
- [x] Keep pause/stop/disconnect semantics honest about an already-issued physical transition. Block later automation until safe verified state, never replay raw enable/init/relax or retry an uncertain toggle.
- [x] Run new tests and all existing pad/motion checks; self-review locks, stale samples, late replies, timeouts and idle CPU use. Commit only owned backend/fake/test files.

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_studio','tests.test_pad'])"
```

## Task 2 — Web feedback and browser workflow

Owner: root. Files `web/motion-studio.js` and `.css` only if needed, `tests/motion_studio_e2e.mjs`, `tests/test_motion_studio_e2e.py`, Studio README. Wait for backend contract before adaptive integration.

- [x] Show backend posture_step label and clarify that started sit/stand finishes even when later steps are stopped. Update supported-content text to include sit/stand; keep skills unsupported. Existing pending/session guards and life heartbeat stay intact.
- [x] Add a failing browser sequence: start recording→sit→await seated completion→stand→await ready→finish/save→replay→observe both real fake robotd transitions; three finite loops; stop/disconnect during a transition emits no future step. Preserve original lively/library/lifecycle assertions and 320/390/1440 screenshots.
- [x] Run the full motion browser wrapper and Node heartbeat tests; inspect screenshots and console errors.

## Task 3 — Review, integrate and deliver

- [x] Independent spec review against the design; fix reproduced gaps. Independent code review after spec issues are closed, then final relevant regression. Do not merge with outstanding critical/important findings. Final source aa825fc: 241 backend, 140 HTTP/web/sensor, 7 Node and 1 full motion browser checks passed; independent reviews passed after fixes.
- [x] Fast-forward into studio-dev without overwriting voice/UI untracked files; run integrated focused checks. Integrated 82 checks passed.
- [x] Freeze tracked runtime bytes, compare dependencies, back up changed files and state. Deploy only while actual runtime policy is disabled and no servo session exists; otherwise request the user to stop, never stop the robot services for convenience. Restart only microduck-studio and verify file hashes/HTTP, preserved state, unchanged robotd/padd/voice process identity. Seven files deployed from aa825fc; twelve user-state files unchanged; control/voice identities unchanged.
- [x] Update canonical feature ledger/verification/README with exact source commit, tests, backup, v2 rollback limits and physical acceptance; archive frozen source/manifest without private data. User already opened the original URL, received exact sequence and confirmed saved recordings replay sit/stand correctly. No image rebuild, OTA enablement, or automatic motion on the real duck. See [final verification](../verification/2026-10-25-web-posture-recording.md).
