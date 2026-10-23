# IMU bus protocol detection in the delivered image

The user authorized integrating PR #47's DXL 2.0 IMU support into the image and recognizing common IMU variants automatically. This is runtime integration, not copying the separate servo-web application into the image.

## Behavior

- Existing firstboot I²C recognition remains: BNO08x and LSM6DSV16X, with ambiguity reported rather than silently picking a chip. Without an I²C selection, robotd uses ID 200 on the configured 1 Mbps servo UART.
- Bus IMU protocol defaults to `auto`. Read-only startup probes try the existing recognized Feetech identities, then DXL 2.0 ID 200's identity and 124/12 SFLP layout. Invalid packets, device errors, wrong lengths and invalid quaternion samples cannot become live measurements. An unknown Feetech identity remains an explicit error. DXL2 model/firmware identity is reported without guessing its manufacturer.
- Configuration may explicitly select `auto`, `feetech` or `dxl2`; no automatic baud/ID/EEPROM changes. No scanning or protocol switching during an enabled control loop.
- Feetech IMUs keep their existing first/last Sync Read ordering. DXL2 IMU and the fifteen Feetech servos use separate read requests under the same UART owner and a single 20 ms telemetry deadline. Partial servo acceptance retains its existing IMU freshness and error conditions.
- The DXL2 12-byte layout has no sample counter, status, or sensor age. Those values stay absent. Read age and a 25-identical-core-block freeze guard are host evidence only. The existing 25 valid quaternion ready gate remains. Feetech counter/status freshness checks retain their stricter existing thresholds.
- Installation orientation stays a separate calibration. A verified DXL2 bus mount is bound to its protocol; a legacy Feetech mount cannot silently authorize DXL2 motion. Commissioning and explicit orientation verification establish the new binding. Changing hardware still requires recalibration even if its protocol is unchanged.
- Studio shows the actual detected transport/board and missing diagnostics honestly, including commissioning and motion modes. Existing calibration/redo/stand-enable flows remain.

## Scope and alternatives

The selected approach adds a small bounded DXL2 packet codec and transaction path to the native Feetech UART owner. Reusing servo-web as a background reader would create competing UART ownership; a separate proxy service would add another control dependency. rustypot's public transaction API owns its own flush/read timeout behavior and its packet codec is private, so it cannot enforce the native backend's one absolute deadline. The wire codec follows the existing PR and ROBOTIS Protocol 2.0 specification, with shared known-vector tests.

Support is defined by an exact register layout, not a promise that every product called an IMU is interchangeable. Arbitrary Euler-angle, full-float, other-ID and other-baud firmwares need an explicit adapter. I²C source discovery runs at boot provisioning as before; a runtime sensor fault cannot silently switch the calibrated source.

## Acceptance

Test known vectors, stuffing, fragmented/noisy/corrupt packets, wrong IDs, device errors, timeouts, read-only enforcement, mixed UART protocol ordering and total deadline. Exercise Feetech FT6 and replica IMUs, DXL2, I²C source behavior, commissioning sampling/verification, mount protocol binding and Studio display. Cross-build aarch64 robotd; create a new payload manifest with its actual digest, build a fresh regular image, and independently inspect the compressed artifact. Publish source and image with the exact tested commits, checksums, licenses and explicit physical-acceptance limits. No SSH deployment or physical robot motion is authorized by this workflow.
