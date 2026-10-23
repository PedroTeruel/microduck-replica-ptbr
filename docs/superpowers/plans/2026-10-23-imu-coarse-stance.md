# Initial IMU commissioning stance implementation

Goal: permit initial mounting calibration in a settled commissioning HOME hold, preserving redo recovery and all movement restrictions.

- [x] Add a regression that captures still/forward samples, solves and verifies while holding; reject unsettled/conflicting hold states and retain unloaded-only redo.
- [x] Run the regression against the old implementation and confirm its torque refusal.
- [x] Update ImuBackend._coarse_guard and context-sensitive IMU instructions; retain solver, helper and hold command behavior.
- [x] Extend the existing commissioning browser flow to exercise coarse capture while standing, then run backend, calibration, helper and relevant browser checks.
- [x] Review the exact diff, integrate without concurrent training/private-note changes, and verify the integrated patch.
- [x] Build and verify a new image 20261023b from committed source and the previous pinned base/payload. The user switched the delivery request from SSH deployment to rebuilding an image; no SSH host-key changes, board writes or physical motion are authorized by this revised delivery path.
