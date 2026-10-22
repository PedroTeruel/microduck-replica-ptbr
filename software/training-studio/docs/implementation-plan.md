# Microduck Training Studio Implementation Plan

> **For agentic workers:** Use subagent-driven-development for isolated implementation and independent spec/quality reviews. Steps use checkbox syntax for tracking. Parent owns the browser UI and end-to-end integration; one implementer owns service files and service tests. Never edit each other's files or stage unrelated changes.

**Goal:** Deliver a usable visual HD1910 training workspace with truthful demo/real modes, advanced controls, process pause/resume, checkpoint evaluation and export.

**Architecture:** A standard-library Python local service controls the existing frozen training project. Browser components consume the documented JSON API. The UI is independent of robot availability; existing Studio provides shared CAD assets and optional robot profile exports.

**Tech Stack:** Python 3.12 standard library, unittest, native browser ES modules, SVG charts, existing Three.js CAD renderer, Playwright/Edge for acceptance.

---

## Task 1 — Durable training service

Files: `run.py`, `training_studio/{__init__,config,commands,environment,service,server,demo_worker,evaluate}.py`, `tests/test_service.py`, `tests/test_http.py`.

- [x] Write behavior tests first. For example:
  ```python
  run = service.create_run({'name': 'check', 'recipe_id': 'hd1910-flat', 'kind': 'smoke', 'config': {}})
  wait_for(lambda: service.get_run(run['id'])['status'] == 'completed')
  assert service.get_run(run['id'])['progress']['total'] == 5
  ```
- [x] Run `python -m unittest discover -s tests -v`; confirm absent-service tests fail before implementing.
- [x] Implement bounded recipe validation, atomic JSON state, real subprocess ownership, metrics/log parsing and one-operation locking. Smoke settings cannot be overridden; formal training requires a successful same-recipe smoke.
- [x] Add real SIGSTOP/SIGCONT group control on Linux and acknowledged cooperative pause in the portable demo worker. Test that iterations remain stable while paused and advance after resume. Stop keeps existing checkpoints; restart recovery cannot signal arbitrary PIDs.
- [x] Implement safe checkpoint evaluation with a bounded rollout and existing normalization-aware ONNX export. Demo export writes records, never fake models.
- [x] Add HTTP and path/token protection. Run the full service tests to green.

## Task 2 — Browser workspace

Files: `web/{index.html,app.js,state.js,client.js,newrun.js,views.js,ui.js,styles.css}`, `tests/state.test.mjs`.

- [x] Add Node behavior tests for default/advanced differences, smoke normalization, state transitions and comparison selection; run `node --test tests/state.test.mjs` and verify red.
- [x] Implement the Chinese workspace and new-run drawer with semantic controls and real API calls. The drawer retains customized values when collapsed and shows the difference count.
- [x] Implement run detail, SVG progress plots, latest evaluation video, checkpoint timeline, collapsible logs, paused/stopped/completed states and comparison/model views. CAD is labeled separately from evaluation video.
- [x] Implement demo labels, profile import validation, environment diagnostics, access-token entry, connection retry and meaningful errors.
- [x] Run Node tests to green and use a live demo server for all subsequent browser acceptance.

## Task 3 — Integration and verification

Files: `dev/browser-check.mjs`, `README.md`, `NOTICE.md`, `.gitignore`, `start-demo.cmd`, `start-demo.sh`.

- [x] Run `python run.py --demo --port 18723 --state-dir <temporary-directory>`.
- [x] Browser acceptance at 1440×1000 and 390×844: create smoke run, complete it, create formal demo run, pause/verify/resume/stop, resume from checkpoint, compare, export records, reopen/refresh and check state persistence. Capture screenshots and reject page errors/overflow.
- [x] Independently review spec compliance, fix gaps, then review code quality and rerun affected checks.
- [x] Document exact demo and real startup commands, Linux-only real pause, retained VRAM/cloud billing, latest-checkpoint semantics, profile limitations, licensing and GPU verification limits.
- [x] Commit only this new directory. Integrate locally into the user's `studio-dev` checkout after validation, retaining unrelated untracked docs. Open the running local preview in Codex.

## Task 4 — Match the existing central Studio

- [x] Inspect the actual Studio stylesheet, navigation and running page; record the approved direction in `design.md`.
- [x] Align the duck mark, shell, chart colors and mobile navigation without altering training actions.
- [x] Apply the central Studio palette, typography, cards, buttons and gray CAD stage throughout the stylesheet.
- [x] Run Node/browser checks and independently review desktop, narrow-screen and drawer screenshots.
- [x] Integrate the reviewed style change into `studio-dev` and refresh the local preview.
