# Qinmo matching Studio / helper verification

Scope: local Studio/helper source only. Runtime contract is the independently reviewed frozen runtime `bdf494ab3fd74898b5159419fbffe87113b4097c`. No real device, SSH, deployment, public image replacement or publication occurred. No Qinmo hardware / standing / walking acceptance is claimed. Protocol peers and service fixtures are software models.

The existing IMU page now offers persistent legacy/Qinmo selection through the existing fixed `imu-recalibrate` transaction. Configured and effective types are separate; Qinmo identity is explicitly configured, with raw/16.4 °/s. Known FT6/own-board automatic recognition and generic DXL2 compatible-layout evidence remain distinct. Old daemons retain legacy display and are refused profile writes when additive capability evidence is absent.

The helper is 0.7.2. Its duplicated calibration builder/validator/serializer preserves `imu_bus_profile`, absent means legacy, unknown values fail. Effective mounts, pending work, runtime readback and finish require the profile binding. Profile entry clears only the backed-up bus mount verified field, including when a historical mount already matches the selected profile. I²C mount slots are unchanged. Ordinary commit cannot promote an unverified/mismatched Qinmo mount.

The fixed transaction validates direct robotd argv, known service overrides, `--params`, `--socket`, top-level calibration path, source/protocol, root ownership and every path ancestor. It changes only the two profile/protocol config values, verifies parsed preservation including quoted TOML and inline policy arrays, backs up main/saved config and calibration with hashes, and refuses altered selected config at finish. It uses both shared locks, pauses padd/gamesir and the fixed duck-echo service before the final gate, repeats controller exclusion after reboot, and restores previous service states after safe finish/cancel. Active web control is excluded; explicit calibration and emergency relax remain available. Background music's existing readiness requires live policy and confirmed-on torque, which fail the profile gate's confirmed-off conditions; its voice/rhythm source is also stopped.

Normal control retains two fresh confirmed-off/no-policy/gains-restored snapshots. Supported pre-control states prove lifecycle and capability, without claiming physical torque knowledge, and reconnect only to commissioning. Startup cancellation persists a factory commissioning landing before removing the owned redo override; it ends the session and permits a fresh selection. Factory cancellation works even when discovery still fails. Successful factory verification keeps the firstboot commit flow. Partial failures restore original files or retain a recoverable persistent session.

## Red / green evidence

The initial baseline commands from `software/studio` passed: `py -3.13 -I -m unittest discover -s tests -t . -p test_imu_backend.py -q` (37), and `... -p test_helper_calib.py -q` (32).

`test_qinmo.py` was written before implementation. The first focused red run had 8 tests: metadata projection lost profile/scale/evidence, a configured but undiscovered IMU retained verified, builders dropped the binding, and selection was rejected as unknown args. The missing profile KeyError was the intended builder-contract failure. The test fixture's initial joint IDs were corrected before that focused red run. Additional red→green cycles covered mandatory revalidation of a historically matching mount, unsafe commit promotion, stale selected config, pre-control cancel ordering, web controller exclusion, latched R3 voice, undiscovered factory cancellation, and truthful safe-landing wording. The actual Edge fixture first failed at the missing Qinmo label and then passed the finished UI.

## Commands and results

All commands run locally in `software/studio` unless stated otherwise.

| Check | Command / result |
| --- | --- |
| Final Qinmo Windows | `py -3.13 -I -m unittest discover -s tests -t . -p test_qinmo.py -q` — 28 tests, OK, 1 POSIX-only test skipped |
| Final Qinmo Linux | `wsl.exe --cd /mnt/f/chengshenzhilu/Robot/Microduck/.worktrees/qinmo-studio-20261027/software/studio /root/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12 -I -m unittest discover -s tests -t . -p test_qinmo.py -q` — 28 tests, OK, no skips; actual unsafe permissions, owner and symlink checks |
| Backend regression | `py -3.13 -I -m unittest discover -s tests -t . -p test_imu_backend.py -q` — 37, OK |
| Helper calibration | same discovery command with `test_helper_calib.py` — 32, OK |
| Old redo sessions | same discovery command with `test_helper_imu_redo.py` — 23, OK |
| Commit / duplicated builder | same discovery command with `test_commit.py` — 46, OK |
| Real Node collection→Python solve | same discovery command with `test_imu_wizard_e2e.py` — 12, OK |
| Actual Edge page | same discovery command with `test_imu_bus_ui.py` — 1, OK; configured/effective labels, Qinmo unit/evidence, narrow selection command, missing discovery / old daemon, legacy and I²C labels, pending collection invalidation, actual global Space→relax handler |
| Node lifecycle / updates | `node --test tests/updates_ui.test.mjs tests/motion_studio_lifecycle.test.mjs` — 6, OK |
| Wider Windows suite | `$env:STUDIO_E2E='0'; py -3.13 -I -m unittest discover -s tests -t . -q` — 1219 tests in 259.569s, OK, 75 skipped |
| Whitespace | `git diff --check` — clean (Git reports configured LF→CRLF conversion notices) |

The 1219-test broad run began before the final voice exclusion, web guard and last recovery/message/readback additions; it is wider regression evidence, not exact-final-source full-suite validation. The focused checks above were rerun after the relevant additions; the last wording-only change was rechecked by both final 28-test Qinmo runs. Root will independently rerun the full suite on the frozen commit. The broad Windows run emitted existing AF_UNIX audio-status-thread exceptions, asyncio slow-task messages and resource warnings, while unittest itself reported no failures/errors. These diagnostics are recorded rather than suppressed; targeted final runs passed.

Independent root QA also exercised the pure patcher against the actual shipped main/saved 2203-byte TOML (both SHA256 `2607d98b64818ffc2d27e55fd9722dad022ce43150ea513d410f615f2007f4e9`) for legacy and Qinmo: four parsed-preservation / idempotence cases passed. The committed tests use self-contained fixtures and do not depend on those outside-worktree artifacts.

Remaining limits: maintainer installation of the matching runtime/helper is required. Unsupported argv/config layouts fail closed. No arbitrary config editor or robotd web-updater component was added. Physical Qinmo behavior, mounting, real UART timing and standing/walking remain unverified by this Studio task.
