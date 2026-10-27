# Software-only release including the Qinmo runtime

The user authorizes publishing the completed IMU work to GitHub and asks how existing users can update without reflashing. The chosen user flow is two explicit steps on the existing software-update page: install the signed webpage/voice package, reconnect, then complete the bundled main-program update while supported and unloaded. Old cards without an update entry use the existing one-time SSH bootstrap. No new SD image is required.

## Compatibility boundary

Keep the existing 20261027 signed software envelope, signing key, controller and Rust engine compatible. Do not silently broaden its robotd/padd restart whitelist or install arbitrary files outside its managed release tree. The new signed package adds a fixed native payload under `studio/deploy/native/`, which the old package path rules already accept. Existing engine apply still updates Studio/helper/voice only. The new helper performs a separate, explicitly confirmed native transaction after that software update has completed.

The default IMU selection remains `自动识别（现有板卡）`; Qinmo remains an optional persistent selection. Users need not update the main program simply to retain existing behavior. The UI must distinguish webpage/voice version, main-program availability/currentness, and actual running main-program identity. It must never announce the complete Qinmo chain ready after only the webpage changed.

## Fixed signed native payload

Publisher input is the reviewed ARM64 ELF from runtime commit `bdf494ab3fd74898b5159419fbffe87113b4097c`, build `0791fcd-feetech-qinmo-control.45`, official0.15.1/modelAPI2, SHA256 `febf44e2e5d4e573f4513f25a1ae6480b976c3988dd3d5e7cdfcf84d2a2d5063`. The original known 20261027 native binary SHA is `edf182edb7bf11aeeeedfdab98170ab2ec48a9ec18417f9b68c744b0a60c6d16`.

The builder's optional native input injects `studio/deploy/native/robotd` and `studio/deploy/native/manifest.json`; both join the signed suite's per-file hashes. The manifest has a versioned schema, architecture, software version, native source/build identity, exact size/hash, model/API compatibility and explicit supported installed-binary hashes. Device callers cannot provide any of these fields, paths, commands or URLs. A missing native input keeps existing package-building behavior and reports native update unavailable.

The root helper's fixed `robotd-update` verb accepts only `status`, `install`, `recover`, a bounded actor name, and `confirmed=true` for mutations. Native code is a separate focused module loaded only from the installed, root-owned immutable managed release, validated against its suite file hashes. Never execute from uploads, source checkouts, caller paths, user-writable directories, symlinks or an unverified release. Its payload path and installation target `/opt/robot/feetech-ft5-r5/robotd` are constants. Unknown installations refuse automatically; there is no force override.

## Native transaction

Use the existing detached-helper mechanism, helper/service-management locks and the updater motion lease. Exclude concurrent software install/rollback, bus ownership, IMU sessions, active recording/music and other control operations. The new native journal/marker blocks webpage and voice actions, including after reboot; emergency relaxation and status remain available. Capture controller-service states and stop padd, gamesir and duck-echo before the final physical gate. Never restart Studio itself during this transaction.

Validate native architecture, known actual installed bytes, direct known ExecStart, socket/port/config/calibration paths, permissions and real running process identity. Normal control requires two fresh, stopped snapshots: policy off, torque confirmed off, no pending unload/home or temporary-gain restoration, fifteen fresh stable joints, sufficient battery and disk. No HOME requirement is added after unloading. Explicitly supported pre-control startup/factory recovery may use the known lifecycle proof plus user support confirmation; it never claims unknown physical torque is off and always lands in factory commissioning. Unknown state refuses before mutation.

Back up the native binary and exact main/saved parameter and calibration bytes to root-private storage before changes. Preserve models, Wi-Fi, pairing, personal state, actions and AI credentials; native installation changes no parameter/calibration contents. Recheck pinned files before writing. Journal every material phase with fsync. Install an owned persistent commissioning override before replacing the native file, so interruption or reboot cannot start unverified motion. Atomically replace only the known regular binary; verify target bytes, deployment identity and the actual running executable/PID generation.

First start in commissioning. For a previously healthy normal installation, return to its original normal mode only after the new runtime and unchanged user files are verified; confirm it remains unloaded and policy-disabled, then restore previous controller states. For pre-control recovery, hand off to the existing owned factory commissioning flow so the user can choose IMU type and validate direction without a trapped helper session. An IMU still needing selection is shown as such, not as walking acceptance.

Failure restores the prior binary where possible and verifies it before restoring normal mode; otherwise keep the commissioning guard and a recoverable journal. Never overwrite subsequently changed user files to make rollback look successful. `recover` handles an unfinished transaction safely and idempotently, refuses concurrent/foreign ownership and cannot resume motion based on a version file alone. A later voluntary native downgrade after user configuration changes is outside this release; existing webpage/voice rollback must be explicitly labelled with its actual scope.

## Browser/API and voice

Extend the existing authenticated same-origin/CSRF update API with bounded native status/install/recover operations. Mutations require explicit support/unload confirmation, contain no caller-selected paths, and execute outside the browser connection lifetime. Display progress from persisted actual state, reconnect truthfully, retain the global Space/emergency path, and show interrupted recovery. Merely opening settings or keeping the default IMU option must not alter a robot.

Voice guards use the native update journal as well as the existing software marker/motion lease, failing closed on malformed active state and avoiding heavy repeated parsing. Native recovery after reboot cannot leave latched R3 actions able to enable motion. The update readiness endpoint excludes a native transaction; native preflight checks readiness before setting its own busy state to avoid self-deadlock, then performs the final physical gate after exclusion.

## Release and verification

Publish source and a signed `2026.10.28.software-update.tar`, corresponding manifest/signature/hash/public-key reference and updated bootstrap inputs. Preserve old release assets. Keep remote README/training changes and private local documentation intact. Publish corresponding native source or an accessible source reference. Release notes and a short Chinese guide give separate instructions for existing update-page users, offline package upload and old cards needing initial bootstrap.

Native/Qinmo hardware support remains explicitly experimental pending physical acceptance; normal existing hardware retains its default behavior. Do not claim device deployment or physical standing/walking tests: the user's device is off.

Required proof: TDD unit/service tests for trust/path/ownership/scope, stale/unknown state, mutual exclusion, successful update, running-byte identity, protected-data preservation, startup/factory landing, failures, interrupted recovery and voice protection; real browser authenticated actions and reconnect/status; actual legacy ARM updater accepting the new signed payload and retaining its original restart scope; actual bundled ARM binary deployment-info and existing independent PTY checks. Independent spec then quality review gates each implementation task and publication.
