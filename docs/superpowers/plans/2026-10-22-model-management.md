# Model Management Implementation Plan

> **For agentic workers:** use subagent-driven-development within this session. User has approved the design and requested implementation; no further execution-choice prompt is needed.

**Goal:** Provide a usable model library on the duck with import, rename, select, bindings, delete and default recovery, without reflashing.

**Architecture:** Studio owns imported packages under its state directory. Reuse robotd's existing policy validation, persistent selection and button binding RPCs. Keep package parsing, service logic, HTTP and browser UI separate.

**Tech Stack:** Python standard library, existing Starlette/ASGI, JSON-RPC, Preact/HTM, existing Node/Edge test harness.

## Task 1 — Runtime/package contract

- [x] Confirm absolute policy paths, deployment sidecars, validate-policy output and RPC persistence/readback.
- [x] Create tests/test_model_package.py covering valid archives, traversal/links/duplicates/oversized members, missing/incorrect identities and failed preflight.
- [x] Run failing tests, implement studio/model_package.py, rerun focused tests.

## Task 2 — Model service

- [x] Create tests/test_models.py with temporary state files and a runtime fake exposing actual policies and bindings shapes.
- [x] Verify installation leaves runtime unchanged, metadata survives restart, defaults are preserved and labels do not replace identity.
- [x] Implement studio/models.py using model_package and existing RPC.
- [x] Verify selected model readback, failed selection rollback, idle guards, button conflict/clear/default readback and protected deletion.

## Task 3 — HTTP integration

- [x] Add optional Models service wiring to app.py/__main__.py without changing existing call signatures incompatibly.
- [x] Add GET /api/models, streaming POST /api/models/import and bounded POST /api/models/op with existing session, Origin and CSRF checks.
- [x] Add integration tests for unauthenticated/cross-origin/missing-token/oversized/failed upload requests and real service mutations.

## Task 4 — UI

- [x] Add web/models.js with model list, import and rename forms, current selection, per-slot recovery and button binding controls.
- [x] Link directly to #/models from tune.js, add routing/navigation in app.js, keep training profile settings separate.
- [x] Keep all error and pending states explicit; no fake loaded/success labels.
- [x] Verify normal desktop and narrow layouts in existing headless browser harness.

## Task 5 — Integration and review

- [x] Run focused tests, then the existing Studio suite; record baseline issues independently.
- [x] Exercise valid import → rename → select → conflict/replace → unbind/default → restore → delete, plus failed install/switch.
- [x] Update README/installation docs with exact package files and supported bindings.
- [x] Review path boundaries, mutation ordering, runtime readback and UI completeness; fix findings and rerun affected checks.
- [x] Integrate the verified changes back into studio-dev while preserving its untracked UI records; report deployment status accurately.

## Verification evidence

- Python 3.13: `py -3.13 -X utf8 -I run_tests.py` completed 931 tests, OK, 4 environment skips.
- Focused model package/service/HTTP/UI/browser suite: 68 tests passed; the UI wrapper runs 9 Node assertions.
- Headless Edge exercised real archive/HTTP/library with explicitly injected test runtime and inference validator; desktop and 390px layouts fit. Physical capture subscribes read-only, waits for stable safe bindings, and restores the snapshot lease on exit.
- Independent review closed actual export-joint layout, disabled-slot recovery, persisted references, JSON limits, refresh ordering and first-key timing findings. No outstanding P1/P2.
- Real board preflight/deployment remains unverified: SSH identity check reported a changed host key; no bypass, board file update or motion was performed.

Local integration: cherry-picked the verified feature into `studio-dev` (`b10ff34`), preserved the existing untracked `software/studio/docs/` UI records, and reran all 68 focused tests successfully in the destination checkout. Studio source is identical to the fully tested feature checkout.
