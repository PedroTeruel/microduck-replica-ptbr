# Qinmo IMU-DXL compatibility

The user approved integrating the audited Qinmo protocol, then asked about automatic detection. Existing FT6/imu_to_dxl detection remains automatic. Qinmo has no unique documented identity: one explicit, persistent selection is required; do not infer vendor or gyro units from ID200, a spoofed XM430 model number, packet layout, or values at rest.

## Frozen inputs

Runtime base: `0791fcd44f71c705dc8bb0fbcde405593b52d19b` in the Microduck-kissqy repository. Studio base: `9ff314c`. Manufacturer protocol1.2 at Gitee QinmoTech/IMU-DXL commit `4644a9d19e07ac47f2c145c5e064c96683a5450b`. Only protocol/docs/debug-page source is available; simulated peers must be labelled specification models, never manufacturer firmware tests. Audit and original Rust reproducer live in workspace `artifacts/qinmo-imu-20261027`.

## First supported mode

Add `[bus] imu_profile = "legacy" | "qinmo"`, default `legacy` for all old files. Qinmo is explicitly supported on the native Feetech servo bus, ID200/1Mbps. `imu_protocol="auto"` or `"feetech"` with Qinmo always selects Feetech before its first packet; explicit `dxl2` is refused. Qinmo DXL2/status143 support is outside this first implementation. Existing legacy mixed-DXL2 and all I²C behavior remains intact.

The user subsequently rejected manual SSH configuration as cumbersome. Selection is therefore exposed on the existing IMU webpage: choose the existing automatic legacy family or Qinmo once, save persistently through a narrowly scoped helper operation, reconnect in commissioning mode and continue the existing mount wizard. There is no arbitrary configuration editor or live runtime switch RPC. Old boards still use the original automatic legacy detection; Qinmo's configured identity is never presented as authenticated automatic detection. Do not extend the software updater's component scope to robotd.

The helper accepts only the two known profile names, changes only `bus.imu_profile` and the compatible `bus.imu_protocol`, preserves every other parsed configuration value, and only handles known root-owned configuration paths belonging to the verified direct robotd ExecStart. Match and back up the main/saved configuration alongside the existing calibration/session backups. Use the shared service-management lock, existing detached operation pattern and controller exclusion. Normal control must have two fresh, confirmed stopped/off snapshots with restored gains; never restart active control. A factory/startup state which never reached control may be handled as recovery only when current daemon diagnostics prove the supported pre-control/commissioning state. Recovery always starts commissioning, never motion or a policy. Unknown runtime state, foreign service overrides, unsupported daemon capability and conflicting updater/bus/redo ownership are refused before writing.

Persist the old profile/configuration and mode for cancellation/rollback. A completed selection stays saved on successful wizard completion. Unknown or frozen sensor data cannot advance the wizard. Failed writes/restarts/readback restore the original configuration where possible and otherwise expose a recoverable persistent session, without automatically enabling motion. The page presents configured and effective profiles separately, invalidates pending work on a change, shows reconnect progress and guides the existing mount verification. A failed saved selection must be recoverable from the webpage using additive `configured_imu_profile` diagnostics even before IMU discovery succeeds. No SSH command is required for the supported user flow.

## Data and discovery

- Qinmo discovery uses documented Feetech PING and a bounded 56/15 read, never assumes address0/5 identity registers. No cross-protocol retry while the board's20s protocol lock may be active. Configured vendor metadata is labelled as configured, not authenticated detection; identity bytes are not fabricated.
- Gyro words are signed LE i16, converted with exactly `raw / 16.4 * pi/180`. Legacy and I²C LSM remain `raw * .0175 * pi/180`.
- Qinmo 56/15: first12 core, byte12 sequence, byte13 bit0 not-ready, byte14 reserved0. Reject undocumented status/reserved bits and malformed/nonfinite quaternion payloads.
- Once explicit status reports ready, XYZ=0 is a valid WXYZ identity quaternion. Continue existing normalization, mounting transform, median and25-valid-sample gate. Legacy all-zero SFLP startup semantics remain unchanged.
- Qinmo has no documented chip-side age. Use real counter advance, host transaction evidence and bounded duplicate detection without fabricating FT6's age upper bound. A not-ready/error/frozen frame cannot reach policy observations or enable motion. Keep the same shared20ms telemetry deadline for15servos plus IMU, with Qinmo at the appropriate last reply position.

## Calibration and telemetry contract

Extend `imu_bus` status with `profile: "legacy"|"qinmo"`, `gyro_dps_per_lsb` and an honest configured-identification label for Qinmo; board label `qinmo`, protocol `feetech`. Existing protocol/board/identity consumers remain compatible; do not add a blanket API-version refusal. Follow the repository's optional-field IPC conventions and document that this new config requires the matching new robotd binary.

Persist the profile used for bus mounting as optional calibration `imu_bus_profile`; absent means legacy. A Qinmo profile with absent/legacy binding, or switching back with a Qinmo binding, invalidates the mount for motion even if the protocol stayed Feetech. Successful verify-imu writes both wire protocol and profile. Apply the same rule in native control, commissioning, calibration-status, read-only sampling, Studio coarse/verify/commit and helper readback. The helper preserves this field through normal commit, redo, cancellation and backups. I²C mount slots keep their existing semantics.

The webpage names Qinmo as configured and shows its unit; changing reported profile invalidates pending wizard samples/results. Old daemons lacking the profile field display legacy semantics. Unknown profile values are refused, not treated as Qinmo.

## Verification and delivery

Test the original reported1640raw=100dps case and negative words; legacy1640raw=28.7dps; valid zero-XYZ versus not-ready; bad quaternion, bad checksum/fragmentation, counter advance/wrap/freeze, mixed15-servo sequencing and the global deadline; profile persistence/validation and mount binding across restart/revalidation. Re-run legacy core/params and targeted commissioning/read-only/single-instance tests. Known17 baseline robotd test failures remain explicitly compared, not weakened.

Compile ARM64 robotd from a frozen reviewed commit and prepare reproducible local deployment inputs/instructions. Independent spec and quality reviews gate integration. No physical device is available, so do not claim Qinmo hardware/standing/walking acceptance or deploy/move a duck. Existing20261027 published image stays immutable until an explicitly versioned successor is built and validated.
