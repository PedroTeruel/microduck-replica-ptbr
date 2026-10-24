# Pairing input readiness recovery implementation plan

> **For agentic workers:** Use executing-plans sequentially in this worktree. Request an independent code review before integration. The user reported this recurring pairing failure after the current controller was recovered manually.

**Goal:** Recover a bonded controller's transient Bluetooth connection failure while the pairing wizard waits for real padd input, without forcing the user to forget and pair again.

**Architecture:** Keep configd/helper responsible for bonding. Add a bounded, target-specific reconnect operation to the existing Bluetooth port and use it in the wizard's connection/input readiness wait. Bluetooth success alone never replaces padd's matching attached report. Keep existing cancellation, driver failure and compatibility fallbacks. Do not change radio settings, delete bonds, restart padd or issue robot motion commands.

**Tech stack:** Existing Python Studio backend, bluetoothctl, fake Bluetooth/configd/padd ports, Python unittest, SSH read-only acceptance on the current duck.

## Evidence and scope

The board reported a paired/trusted Pro Controller. configd logged `InProgress: br-connection-busy` but returned a paired result; the wizard then timed out waiting for padd. The input device was absent. After the user put the controller in pairing mode, a normal connect succeeded and padd opened `/dev/input/event4`. Its read-only tap reported the matching controller MAC. Linux Nintendo driver files are present. This is evidence of a missing recovery path, not proof that every historical failure has the same cause.

The fix addresses the observed webpage pairing path. A reboot-only reconnection report requires its own reproduction; no unattended periodic reconnection to arbitrary saved controllers is introduced.

## Tasks

- [x] Run baseline `tests.test_pad`.
- [x] Extend `software/studio/tests/test_pad.py` with a helper-success/transient-disconnect case where only a reconnect produces the matching attached report. Verify failure before implementation. Cover bounded retries, cancellation, wrong-controller reports, and inactive/denied padd.
- [x] Add a bounded `BluetoothCtl.reconnect` in `software/studio/studio/pad.py`, using only the validated requested MAC and the remaining wait budget. Add recovery to `_after_pair` without clearing bonds or changing adapter state. Real input remains the success criterion for a functioning tap; the existing unavailable-tap path continues to say explicitly that input cannot be verified.
- [x] Update the timeout advice to distinguish a sleeping/disconnected controller from missing input after a live Bluetooth link, using observed state rather than assuming the bond is bad.
- [x] Run focused red/green tests, the complete handpad backend suite, and appropriate UI/API regression checks. Review the diff and obtain independent code review.
- [ ] Compare board source to the tested source before any deployment. Preserve an original backup. If compatible and the robot is in a safe idle state, deploy only the verified Studio patch and restart only Studio. Do not interrupt the working handpad or move the robot to force a reproduction.
- [ ] Verify current tap identity, webpage status and deployed file hashes; report which recurring scenario is verified and which still needs the user's next real pairing cycle. Integrate/publish only the small fix, keeping unrelated local training changes private.

Test command from `software/studio`:

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_pad'])"
```

Success requires a matching `attached` report. A Bluetooth `Connected: yes`, a running service or a successful connect command alone is insufficient.

## Verification and deployment status

- Baseline: 144 handpad backend tests passed.
- Reproductions failed before implementation for stale pairing connection, missing post-pair reconnect and late input. Review regressions also failed first for stale configd versus real input, input at the final deadline, cancellation at the final deadline, and attachment during the legacy fallback.
- Final handpad backend suite: 159 tests passed. HTTP and real-browser virtual-handpad regressions: 109 tests passed. Existing test harness resource warnings remain unrelated to this change.
- Independent review: no remaining actionable P1/P2 findings after the readiness commit rechecks actual attachment identity under the lock.
- The board's original pad.py and helper.py match the local baseline byte-for-byte; originals are backed up under the task's local artifacts directory.
- Before deployment the board stopped responding on its LAN address, and a fresh LAN scan found no Studio service. No patch was uploaded and no service was restarted. Deployment and physical acceptance remain pending restoration of the device connection.
