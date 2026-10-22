# IMU Revalidation Implementation Plan

**Goal:** Allow saved IMU installation quaternions to be recalibrated with the unchanged original coarse/runtime verification flow.

**Architecture:** A persistent bounded helper session temporarily returns motion-mode robots to commissioning, then narrowly restores their original motion_enabled after runtime verification. Existing factory flow stays direct; UI exposes redo/resume/cancel. No abandoned auto-label or new capture-session changes are reused.

**Tech stack:** Existing Python3.13 helper/async RPC, systemd configuration, Preact, unittest/Node/Edge fake fixtures.

- [x] Backend/helper TDD: enter/status/finish/cancel, strict arguments, safe fresh gates, original execution config and calibration backups, owned override, readback/rollback, preserved non2048 joint calibration, collision guards, sudoers installation and docs. Wire async imu.op redo-start/redo-cancel and automatically finish after successful original verify + exact source/quat readback. Expose redo state read-only.
- [x] Frontend TDD: verified=true still exposes redo, TwoStep confirmation, original commissioning coarse capture unchanged, motion start/resume/cancel, retained progress/success/failure, precise upright-before-verify wording. Keep fine collection and solver unchanged.
- [x] Browser: actual page against fake motion-limp with verified mount, two-click enter, original captures and verification, restored mode and same joint values, retry and cancel; original factory commissioning regression.
- [x] Independent spec and quality review. Run focused original IMU/helper/HTTP and browser regressions; full Studio regression if needed for privileged workflow. Integrate to studio-dev preserving private and unrelated training work; verify and remove clean worktree.
- [x] Record board acceptance steps. User subsequently explicitly requested a new image and update/push; that release is a separate follow-up, with no board connection implied.

Baseline:134 original IMU/calibration/wizard/helper tests passed in4.544seconds. Worktree based on studio-dev9b447b2, outside checkout directories.

Focused final verification:165 Python tests passed in5.341seconds; all9 commit/IMU browser scenarios passed in94.087seconds;5 standalone Node tests passed. Full Studio regression:1009 tests passed,4 skipped,590.143seconds. Spec and quality review found no remaining blockers. Integrated feature0c0de63 into studio-dev, preserving concurrent training commits; destination165 focused tests passed in5.366seconds.
