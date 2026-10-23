# IMU bus autodetection implementation plan

> **For agentic workers:** Use executing-plans to implement these tasks in this session. Use requesting-code-review for independent review before publication.

**Goal:** Ship automatic Feetech/DXL2 bus IMU selection in robotd and truthful Studio status in a verified new image.

**Architecture:** One native UART owner performs bounded read-only startup detection and sequential mixed-protocol telemetry. DXL2 sensor evidence remains distinct from the richer Feetech schema. Existing I²C firstboot detection and explicit source configuration remain.

**Tech stack:** Rust 1.99, serialport, serde, Python 3.13, Studio Preact, Linux image tooling.

## 1. Establish baseline and source provenance

- [x] Create isolated replica and runtime worktrees from public master 53285f0 and pinned runtime 4734cbb.
- [x] Run `cargo +1.99.0 test -p duck-control -p robotd-params -p robotd`; supply real ignored ONNX fixtures from the previously verified payload, without weakening hash/contract tests.
- [x] Record baseline failures separately from new regressions.

## 2. Add the bounded DXL2 read path

Files: runtime `duck-control/src/dxl2.rs`, `lib.rs`, `feetech.rs` and transport tests.

- [x] First add failing tests using the PR's PING/READ vectors (`fffffd0001030001194e`, `fffffd0001070002840004001d15`), stuffing splits, CRC/noise recovery, wrong ID/length/error, and a PTY mixed-protocol peer.
- [x] Implement `packet(id, instruction, params)` and an incremental bounded status decoder; only the bus owner performs serial I/O.
- [x] Add `BusImuProtocol::{Auto,Feetech,Dxl2}` and `Bus::set_imu_protocol`, read-only identity probing and DXL2 124/12 reads. Failed forced selections do not fall back.
- [x] Enforce one absolute telemetry deadline across DXL2 and Feetech requests, preserve read-only write rejection, and keep existing strict transition confirmation and partial-read conditions.
- [x] Make `ImuSample.sequence/status` optional; DXL2 uses no invented sequence, sensor age or status. Share a freshness gate between commissioning and motion; use repeated core bytes for DXL2 and the existing counter rule for Feetech.
- [x] Run the new tests red, implement, then green; rerun existing transport tests.

## 3. Integrate configuration, commissioning and diagnostics

Files: runtime `robotd-params/src/lib.rs`, `robotd/src/main.rs`, `feetech_commissioning.rs`, `duck-control/src/feetech_snapshot.rs`, relevant fixture constructors, `IMU-MODULE.md`.

- [x] Test `bus.imu_protocol = "auto"|"feetech"|"dxl2"`, default auto and invalid values. Pass it to both startup paths.
- [x] Report actual `imu_bus_protocol`, board and identity in motion and commissioning. Keep unknown DXL2 counters/status absent.
- [x] Bind a verified bus mount to its actual protocol when verify-imu succeeds. Refuse DXL2 motion under a legacy/different-protocol mount; preserve existing Feetech upgrade behavior and redo rollback.
- [x] Bump the fork build identity and document supported layouts, probing, explicit selection, recalibration and error behavior.
- [x] Run targeted runtime tests, relevant full crate tests and the aarch64 build.

## 4. Integrate Studio

Files: replica `software/studio/studio/imu.py`, `web/imu.js`, `web/state.js` if needed, tests and README.

- [x] Add failing backend and browser assertions for FT6/replica/DXL2 detection labels, absent hardware diagnostics and incompatible calibration binding.
- [x] Display the detected protocol/board; replace obsolete FT6-only help and invalidate in-flight calibration results when transport changes.
- [x] Preserve initial calibration, standing capture, redo, cancel and recovery behavior; run relevant Python/browser regression tests.

## 5. Build and publish the actual integration

- [x] Obtain independent code review and fix concrete findings.
- [x] Commit/push the tested runtime branch; build robotd for aarch64 from that exact source.
- [x] Repack the verified previous payload replacing only robotd and updating its manifest digest/size/provenance. Validate every payload entry before image construction.
- [x] Freeze replica source, build a new image, run checksum/xz checks and independent decompression/read-only filesystem inspection of installed runtime/Studio/factory state.
- [x] Publish a regular Latest release with six canonical assets; verify remote sizes/digests and download response. Update download pointers without rewriting earlier image assets.
- [x] Merge the isolated replica work into local studio-dev while preserving unrelated unpublished training changes and private notes. Report tested scope and outstanding physical acceptance.
