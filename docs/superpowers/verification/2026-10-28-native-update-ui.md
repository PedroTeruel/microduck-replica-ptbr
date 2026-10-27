# Native update page and voice integration verification

Task 2 implementation on top of approved Task 1 commit `87fe90aa0bb0569c1fb52b6b019e31cac61ee9b6`.
This record covers local software and explicit service fixtures. It does not claim
device deployment or physical Qinmo, standing or walking acceptance. Final signed
package, actual legacy ARM engine and publication verification are separate gates.

## Contracts exercised

- Existing update operations retain the exact old IPC request. Native operations
  stay on the authenticated same-origin/CSRF API with fixed Studio actor and only
  status/install/recover; mutations require literal `confirmed: true`. Extra
  paths, URLs, actor, commands, force and non-boolean confirmation refuse.
- The native submission mutex excludes duplicate requests and conflicting software
  install/rollback without making the root helper's initial app readiness query
  fail itself. A real Linux app readiness socket is ready before the root fixture
  writes its journal and unready after a real public journal is written and read
  through `helper.native_update_state`.
- Actual running identity plus matching target hash determines currentness.
  Thread completion or webpage version alone cannot announce native success.
  Malformed journals override an otherwise healthy helper status; unfinished
  restore/cleanup and all persistent exclusion artifacts remain motion guards.
- Incoming commands, queued native RPC/notifications, autonomous music outputs and
  boot-time servo restoration honor that guard. Emergency stop/relax, audio off
  and neutral cleanup remain available. An idle guard cannot spin the pad tick.
- Standalone voice mirrors the public helper's bounded fail-closed reader, with
  inode/metadata cache invalidation. Tests compare every exclusion and pending
  flag, reject oversized/malformed/unsafe/unknown state, invalidate in-flight
  recognition and latched R3, and guard in-flight music replies.
- Root helper `Op.finish` now retains a non-null native refusal reason in the
  flattened detail without replacing an existing native status reason when the
  finish argument is absent. A real root fixture battery refusal passes through
  `Op.finish`, the fixed helper bridge and HTTP response with its human reason.

## Final scoped results

From `software/studio`, Windows Python 3.13 (`-I -X utf8`, deps and cwd on sys.path):

`tests.test_updates_native tests.test_updates_http tests.test_motion_studio tests.test_pad tests.test_http.ServoSessionBatch3Test tests.test_helper_bus tests.test_helper_calib tests.test_helper_imu_redo tests.test_native_update tests.test_qinmo`

522 tests, 7 POSIX skips, pass. The broad Windows run also reports one unclosed
file ResourceWarning; it does not fail a test. Do not describe this as warning-free.

Linux Python 3.12, same modules except `test_pad` and the full servo batch are
replaced by the focused boot native guard test: 342 tests, no skips, pass.
Standalone `software/duck-echo` discovery: Windows 160 tests, 18 platform skips,
pass; Linux `/usr/bin/python3.11` 160 tests, no skips, pass.
`node tests/updates_ui.test.mjs`: pass.

Edge `tests.test_updates_e2e` plus existing `tests.test_imu_bus_ui`: 2 tests pass.
The former deliberately uses the signed 20261027 package with the real controller
and explicit fake engine, then injects new native-panel states. Its 20 behavior
assertions pass, browser exceptions are empty, 1440/390/320 have no horizontal overflow,
and all six webpage/native screenshots were inspected. Native pending/explicit
acknowledgment, progress/reconnect, success, failure/recovery, absent payload and
unknown installation are covered. The real global Space path reaches
`robot.relax`; no enable/do/init call appears and viewing alone makes no native
mutation. Native mutations recorded are exactly install, install, recover with
fixed Studio actor and true confirmation. HTTP tests separately exercise login,
password, origin, CSRF, body bounds and metadata rejection.

Local evidence lives outside Git under
`artifacts/software-release-20261028/`: `task2-final-studio-windows.log`,
`task2-final-studio-linux.log`, `task2-voice-windows.log`,
`task2-final-voice-linux.log`, `task2-final-browser.log`,
and `task2-e2e-final/{browser.json,native.jsonl,robotd.jsonl,shots/}`.
Earlier `task2-e2e*` attempts include intentionally corrected fixture-contract
errors and should not be mistaken for the final run.
