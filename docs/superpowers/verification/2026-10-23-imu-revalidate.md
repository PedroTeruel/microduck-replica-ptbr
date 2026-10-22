# Repeatable IMU direction calibration — local verification

The saved/verified installation quaternion no longer hides the original coarse calibration flow. Motion-mode entry uses the fixed root helper transaction; factory commissioning reopens the existing flow directly. The coarse solver, runtime verifier and fine calibration math are unchanged.

## Verified locally

- 165 focused Python tests passed in 5.341 seconds after the final helper interruption fixes.
- All 9 commit/IMU browser scenarios passed in 94.087 seconds, including original factory and stance flows, two-click redo, page refresh, successful return to motion while limp, retained non-2048 joint zeros, cancel, and interrupted entering/finishing/cancelling recovery.
- 5 standalone Node tests passed.
- Independent specification and quality review: no remaining functional blockers or P1/P2 findings. Review findings were reproduced and fixed before acceptance.
- `git diff --check` passed.

The helper tests distinguish the override on disk, the command loaded by systemd, and the live process mode. They exercise interrupted writes/removals before and after daemon-reload, foreign startup arguments, failure rollback, readback mismatches, source changes, and backup ownership/tamper checks. Browser tests replace only the privileged filesystem/service boundary; no real services run.

Full Studio regression: **1009 tests passed, 4 skipped, in 590.143 seconds**. The suite started before the last narrowly scoped helper interruption fix; the final 165-test focused run above separately verified that fix. Feature `0c0de63` integrated into `studio-dev` without changing concurrent training work or private untracked Studio notes. Destination focused verification: **165 tests passed in5.366seconds**.

## Board acceptance still required

No SSH, real board update, image build or card flash was performed. Studio and helper/sudoers 0.7.0 must be updated together on a test card before hardware acceptance.

1. Back up the working card and current calibration. Start with the robot supported and torque off.
2. Recalibrate an already verified mount: still capture, torso forward capture, physically upright **before** starting runtime verification, then forward on prompt. Confirm motion mode returns while torque remains off.
3. Compare joint zeros/directions/limits before and after. Test cancel, page refresh and a Studio restart with an active session; do not claim success until current-source quaternion and mode are read back.
4. Check model import/key bindings and actual camera/ToF hardware on the same test setup. Camera/ToF hardware-dependent automatic service startup remains separate unfinished image work.
5. Package a new image only after board acceptance; validate first boot on a spare card.
