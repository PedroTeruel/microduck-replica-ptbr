# Sensor Status Band Implementation Plan

**Goal:** Add truthful low-cost camera/ToF status cards without starting hardware services.

**Architecture:** Extend readonly camera metadata with bounded local mediad hello health; reuse fresh ToF snapshots. A visible-only frontend reader updates two cards. No image/system-service/IMU behavior changes.

**Tech stack:** Existing asyncio RPC, Preact, unittest/Node/headless Edge.

- [x] Backend TDD: camera socket service_state/reason, valid hello, refusal/timeout/bad JSON/limit, connection close and Windows unavailable; config source remains unverified. CLI controlled socket address. Own sensors.py, __main__.py and sensor backend/HTTP tests.
- [x] UI TDD: mappings for online/test/sim/waiting/unavailable/error and strict freshness; 10-second bounded reader with cancellation and no hidden polling. Add cells before handpad and update seven-card responsive grid. Own sensors.js, app.js, styles.css and Node UI tests.
- [x] Browser test checks seven card order, links, missing/ready/sim/test/error, hidden/navigation pause, desktop/390px/320px fit; preserve no extra media.frame/WebRTC/robot commands during band checks.
- [x] Review source evidence for service-policy answer; update README and mark that automatic hardware-based service startup remains separate unfinished work.
- [x] Run focused sensor/HTTP/band/browser and affected overview/pad regressions; independently review, commit and integrate local studio-dev preserving private records and other changes; verify destination and remove clean isolated worktree.

Baseline: 33 sensor backend/HTTP/UI tests passed before changes. Branch based on studio-dev 9d0fe05, outside repository checkout directories.

Verification:

- Independent spec and quality review found no material P1/P2; reviewer verified actual mediad hello implementation and reran 47 backend/HTTP tests plus 22 Node UI tests.
- Combined sensors/backend/HTTP/UI and overview browser regression: 69 tests passed in 141.154 seconds.
- Affected handpad/backend/battery regression: 223 tests passed in 56.133 seconds. Combined with the separate sensor browser test, 293 Python tests passed; this was targeted verification, not a new full-suite run.
- Extended sensor browser E2E passed in 25.496 seconds. It checks valid/missing/sim/test states, no WebRTC from band checks, no hidden polling over10seconds, and desktop/390px/320px width and card contents. Camera fixture receives only hello; ToF fixture only tof.stream.
- Screenshots/logs: F:/chengshenzhilu/Robot/Microduck/artifacts/sensor-band-20261023-v2.
- JS syntax, Python compilation and git diff checks passed. Existing overview harness emits nonfatal file-handle ResourceWarnings; assertions passed.
- No IMU, image service policy, hardware startup or real-board change. Hardware validation remains unperformed as requested.

Integration: feature eb9aba8 applied to studio-dev as6b86006. Destination Studio subtree matches the reviewed feature; all49 focused sensor/HTTP/UI/browser tests passed again in30.856seconds. IMU and image files match9d0fe05. Existing software/studio/docs private records were preserved. Local-only delivery; automatic hardware-based service startup remains unimplemented.
