# Initial IMU calibration while holding HOME

The user requests that first-time IMU mounting calibration also work after manually enabling the commissioning standing pose, with deployment over SSH to their duck. Keep the existing still/forward solver and runtime verifier unchanged.

Allow factory commissioning capture, solve and verification in either the existing relaxed state or an explicitly reported, settled HOME hold: commissioning/holding, all servos enabled, hold.stage=holding, finite HOME error within 5 degrees, no conflicting torque, motion, policy or power transition. Continue to check each fresh sample. Ramping, unknown or partial torque, active movement and pending unload remain rejected. Do not send movement commands as part of calibration.

Persistent motion-to-commissioning redo sessions retain their existing unloaded-only contract because finishing/cancelling restores services and can restart robotd. Their hold prohibition, helper and recovery mechanism are unchanged. Explain this distinction in the page; factory calibration may keep HOME held through verification, which the pinned runtime explicitly supports.

Back up changed board files, verify hashes and syntax, then restart only Studio. Preserve robotd, calibration, model files and network settings. Confirm any changed SSH host identity before connecting. If no authenticated board connection is available, complete and retain the tested local patch without claiming deployment.
