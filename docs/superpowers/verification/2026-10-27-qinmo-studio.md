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


## Specification review correction: explicit unknown profile

Independent specification review of frozen Studio `f071ed1f5e1b4c321f2668c2a96b9556e7c0a6ab` found one fail-closed gap: an explicitly unsupported `imu_bus.profile` was projected to absent metadata. With no configured-profile field, that could incorrectly retain a legacy verified mount and accept old pending work. A raw Qinmo binding without any current source/discovery/configured/effective mount evidence also needed defensive invalidation.

Four new regression tests were added before this correction. The red run reproduced dropped explicit evidence, raw verified promotion, ordinary helper commit acceptance, and old redo entry acceptance. The correction preserves unsupported profile evidence for readable diagnostics, refuses effective mounting/pending/solve/capture/verify/commit/redo trust, and preserves truly absent old-server legacy behavior. Same-wire transitions to unknown invalidate in-flight results. Raw Qinmo bindings remain unverified even when source and discovery are entirely absent or a stale top-level mount says verified. The actual browser now shows unsupported type / units pending rather than selecting the legacy 0.0175 conversion; explicit calibration actions are disabled while the error is present. Supported profile selection recovery and I²C behavior retain their existing paths.

Final correction checks: Windows Qinmo **32 tests OK, 1 POSIX-only skip**; Linux Qinmo **32 tests OK, no skips**; backend 37, commit 46, wizard 12, helper calibration 32, old redo 23, actual Edge 1 all OK. Commands are the same focused commands recorded above. Browser red first failed at the missing unsupported-type status and exposed the incorrect legacy unit; green confirms both readable status and absence of that guessed unit.

Before requesting this correction, root independently checked the exact frozen `f071ed1` source: full non-browser Windows **1229 tests in 244.110s, OK, 76 skipped**; Linux Qinmo28 + oldredo23 OK; actual Edge1 OK; shipped-config preservation4 OK. Those results apply to `f071ed1`, not to the subsequent correction commit. The original 1219-test run and its platform warnings remain recorded above with their original provenance. No deployment or physical acceptance took place during review or correction.


## Quality review correction: raw metadata presence (2026-10-28 Tokyo)

Quality review of frozen `46be79da84fcdbbddfee3adc16862d63882aa9c5` found one P2 class of gaps: unknown wire protocols were still lost by projection, and ordinary helper paths did not consistently validate explicitly present configured-profile metadata. Root independently verified that revision with 170 Linux focused tests, Edge1 and actual shipped-config4; those passing checks did not cover the new reproductions and do not establish final correction coverage.

A single pure `imu_bus_metadata` validator now inspects all explicitly present native/top-level wire protocol, data profile and configured-profile fields before projection. The same function is mirrored in the standalone helper with parity tests. Explicit null, empty or non-object metadata, unsupported protocol/profile values, Qinmo+DXL2, conflicting providers and configured/effective conflicts are refused. Genuine absent old-server fields remain legacy-compatible. Known configured profiles without discovery remain eligible for the supported pre-control selection recovery. Active I²C calibration retains its existing semantics and ignores unused bus metadata.

The validator gates mount trust, pending candidates and current metadata, in-flight context, solve/coarse/verify, profile selection, ordinary helper commit preview/write, post-restart commit readback and ordinary redo entry/readback/finish. Unsupported raw dictionaries remain visible; malformed non-object presence has an explicit diagnostic error rather than appearing as an absent old server. The page displays pending type/units and disables unsupported actions. It never guesses legacy or Qinmo conversion for invalid current diagnostics. The user's confirmed default UX remains `自动识别（现有板卡）`; Qinmo is persisted only when deliberately selected.

Eight additional test methods cover the four review repros, a 15-case invalid metadata matrix in both native/top-level locations, the mirrored contract and valid old/known-profile positives, post-restart failure, redo finish before writes, malformed pending presence, and I²C preservation. Tests were run red before the relevant fixes: initial matrix run reported 31 failing subtests plus the missing validator API, post-restart commit and malformed-pending cases each reproduced a false success, and the browser exposed the unsupported-protocol legacy-unit fallthrough. The corrected post-restart test was also checked red with its readback guard temporarily removed, then green after restoration. Browser unit assertions inspect the current-value panel separately from the legitimate Qinmo choice label.

Final correction checks, using the same commands above: **Windows Qinmo40 OK (1 POSIX skip); Linux Qinmo40 OK (no skips); backend37, commit46, wizard12, helper calibration32, oldredo23, actual Edge1 OK.** These are focused final-source results; no new full-suite claim is made for this quality correction. `git diff --check` passes. No real device, SSH, deployment, publication, runtime change or physical acceptance occurred.


## Final quality correction: validity transitions invalidate async work

Final quality recheck of frozen `fca43b5a44f511dcb50d89af2885c51b20efdcc1` closed the raw-presence issue and found one residual context gap: adding conflicting secondary metadata could leave the chosen native projection unchanged, so its validation error did not change the context key. Root's independent checks of that frozen parent passed 178 Linux focused tests, actual Edge1, the raw metadata invariant matrix48 (the earlier estimate of84 was corrected), and shipped-config4. Those results apply to the parent revision.

The backend's info-present context now includes the raw validation error; the browser context includes diagnostic validity errors too. Completed results and collection are discarded as soon as the observed context becomes invalid and are not resurrected when it becomes valid again. A monotonic in-process context generation also pins async solve, capture and verifier work: an observed valid→conflict→valid round trip cannot accept the old reply just because the final tuple equals the original. Supported intentional commissioning→control completion retains its existing finish path. No service, config, runtime or detection architecture changed.

Five additional backend regression methods were written red: unchanged chosen projection with a conflicting secondary report retained a completed result and accepted an in-flight solve; after adding validity to the context, explicit valid→conflict→valid tests still reproduced old solve/verifier acceptance and capture continuing past an awaited stale reply. The generation checks made all five green. The actual Edge fixture first reproduced collection surviving the validation conflict; it now checks immediate reset and no resurrection after the error clears while the chosen board/configuration remain unchanged.

Final targeted checks, using the same commands recorded above: **Windows Qinmo45 OK (1 POSIX-only skip), Linux Qinmo45 OK (no skips), backend37 OK, actual Edge1 OK, collection→solver wizard12 OK; git diff --check clean.** No full-suite claim is made for this narrow context correction. No deployment, publication, SSH or physical acceptance occurred.
