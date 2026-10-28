# Runtime Software Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. One implementation agent per task, specification review before quality review; no overlapping implementers. Steps use checkbox syntax.

**Goal:** Publish a backward-compatible signed software update that gives existing users the Qinmo webpage configuration and an explicit safe main-program update without reflashing.

**Architecture:** Preserve the old software envelope/engine. Stage1 installs signed Studio/helper/voice plus a fixed native payload in the immutable release. Stage2 is a narrowly scoped helper transaction with persistent commissioning recovery. Existing native code, models and user configuration remain separate from browser code and change only on explicit supported operations.

**Tech Stack:** Python3.13 (Linux3.12 focused filesystem tests), existing helper/std-lib/TOML, existing minisign/Rust updaterd, Edge/Node CDP, ARM64/QEMU, GitHub CLI.

## Task1 — Fixed native transaction and signed payload builder

Files: new `software/studio/deploy/native_update.py`; modify `software/studio/deploy/microduck-helper`, `software/studio/studio/helper.py`, helper install documentation as needed; modify `software/updater/build_package.py`; add focused `software/studio/tests/test_native_update.py` and publisher tests under `software/updater/tests/`.

External helper contract:

```json
{"by":"Studio","action":"status"}
{"by":"Studio","action":"install","confirmed":true}
{"by":"Studio","action":"recover","confirmed":true}
```

`robotd-update` is a fixed verb, not an arbitrary process launcher. Publisher input is an explicit native binary with fixed reviewed source/build identities; no native input keeps current builder behavior. Native manifest and file locations follow the approved spec; payload size/hash and every source file are included in the signed suite provenance.

- [x] Write/run red tests for known native payload trust and malformed caller arguments, the actual fixed target/config paths, known baseline bytes, active/unknown control and unsupported services. Use the existing helper fake contexts with real temporary files; no serial hardware.
- [x] Implement trusted managed-release loading and bounded status, then native install with preflight/exclusion, exact binary/user-file backups, persistent commissioning guard and atomic replacement. Assert real target and running-process identity and unchanged protected data before claiming success.
- [x] Add/run failure and reboot/recover tests around every mutation boundary, rollback failure, changed protected files, controller restoration and factory handoff. Preserve existing IMU/legacy/helper behavior.
- [x] Implement optional frozen native payload injection into `build_package.py`, preserving old envelope/signing/version rules; validate ELF/size/hash/source fields. Test no-payload compatibility and signed provenance of native payload files.
- [x] Run `py -3.13 -I -m unittest discover -s tests -t . -p test_native_update.py -v` from `software/studio`, existing `test_qinmo.py`/helper regressions, Linux filesystem variants, and updater publisher tests. Self-review, document exact results and commit. No publishing/deployment.
- [x] Independent specification review, fix/recheck, then quality review, fix/recheck before Task2.

## Task2 — Existing settings API/UI, persistent gates and voice

Files: `software/studio/studio/updates.py`, `app.py`, helper bridge/one focused native backend module if appropriate; `software/studio/web/settings-updates.js` and existing state helpers; `software/duck-echo/voice_commands.py` plus relevant voice tests; focused Studio API/browser tests and short user/deploy guides.

- [x] Add red tests for authenticated native status/install/recover, confirmation and CSRF, exact argument rejection, old/no-native package behavior, concurrent software/profile/control exclusion and emergency Space/relax.
- [x] Connect fixed helper operations through the current update page. Display webpage/voice and native state separately; installation of only the webpage cannot imply native capability. Retain current upload/install/rollback behavior and label rollback scope truthfully.
- [x] Gate new motor/record/music/setup operations while native journal active, preserve status/recovery/relax, and prevent self-deadlock in readiness. Add the native persistent journal to voice action guards with bounded parsing and tests for reboot/malformed state.
- [x] Exercise the real browser fixture: stage1 current webpage, pending native update, confirmation, progress/reconnect, success, failure/recovery and unavailable/unknown installation. Confirm merely viewing settings/default IMU has no side effects.
- [x] Run focused and appropriate broader Studio/voice checks, document exact source/check boundaries, commit, then independent spec and quality review with fixes/rechecks.

## Task3 — Root release integration and publication

- [x] Preserve current remote master changes and original private local docs/training; verify the cherry-picked Qinmo product tree equals the previously approved local product implementation before new changes.
- [x] Freeze reviewed source, build/sign native-bearing2026.10.28 package with the existing private signing key (never include/print it), verify signatures with the installed public key. Use real old20261027 bootstrap/ARM engine to prove new package envelope and restart-scope compatibility, then validate actual bundled ARM identity/PTy behavior.
- [x] Prepare compact bootstrap inputs/resources and a short guide with existing-page, offline-upload and one-time old-card SSH paths. Include complete operation order and actual native rollback/recovery scope.
- [x] Publish corresponding reviewed runtime source to its appropriate user-owned GitHub source location or attach source with provenance. Build release assets from frozen commits only; GitHub release/tag links and signatures must match.
- [x] Push non-destructively, create draft release, upload all assets, verify server digest/size and signatures, then publish the reviewed release. Do not overwrite old assets/tags. Verify anonymous download/catalog discovery using the actual old client path.
- [x] Integrate reviewed code back locally while retaining local training work/private files. Record source commits, artifact hashes, checks, explicit physical acceptance pending and final user instructions. No live robot deployment or new card flashing.
