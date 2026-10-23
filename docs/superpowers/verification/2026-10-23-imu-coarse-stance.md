# Initial IMU commissioning stance verification

Request: allow initial mounting calibration while manually holding the commissioning HOME pose. Delivery was changed by the user from SSH updating to rebuilding an image. No SSH identity was replaced, no authenticated board connection or board write occurred, and no physical movement was commanded.

The original guard rejected every enabled servo state, including a settled commissioning hold. The pinned runtime source at 4734cbb0 explicitly permits IMU verification while holding HOME and reports hold.stage, max_error_deg and torque_state. The fix permits only settled commissioning/holding with all_enabled, HOME error within 5 degrees and no conflicting transition. Persistent recovery sessions remain unloaded-only. Solver, root helper and robotd are unchanged.

Evidence:

- New full capture/solve/verify regression failed on the old torque refusal before implementation.
- IMU backend/calibration suite: 86 passed, 12.834 seconds. Helper redo suite: 21 passed, 0.772 seconds.
- Real browser/HTTP/fake-runtime standing calibration passed with torque all_enabled before and after verification, policy disabled, followed by confirmed torque off after explicit fixture cleanup. Original unloaded commissioning capture also passed.
- Nine of ten cases passed in the latest full browser run. The motion stance case exposed an existing harness race: the fixture reset preceded the first robot.init by 7 milliseconds. After waiting for actual stance readback and independently initializing that case, its isolated browser run passed in 14.043 seconds. A final integrated browser run is required before image publication.
- Harness sample windows now use the UI's 3 seconds; DOM readiness and unload completion are checked rather than inferred from sleeps or command acceptance. No production sampling thresholds were weakened.
- Independent code review reported no P1/P2 findings. Whitespace checks passed.

These are software tests using explicit fake hardware, not physical standing/calibration acceptance. Image verification and final browser results belong in the 20261023b image release record.

Final integrated release run: all 10 browser scenarios passed in 128.920 seconds against release commit 320540ed510c0380b1d01b0cb8187f2c1e6d197e. Standing capture/solve/verify retained all_enabled torque with policy disabled; explicit unload was confirmed off. The motion-case race fix also passed in this complete run.
