# Pad camera preview implementation plan

> **For agentic workers:** Use executing-plans sequentially in this worktree; request an independent code review before merging. The user supplied and confirmed the visual placement in the current conversation.

**Goal:** Show posture, camera view and handpad controls together at the user's marked location.

**Architecture:** Reuse CameraLink through a shared session hook and screen. An inline camera card owns only viewport/route visibility; it never becomes a handpad control or opens hardware services.

**Tech stack:** Preact/HTM, CSS Grid, existing mediad WebRTC, Node tests and real Edge browser fixtures through Python unittest.

- [ ] Run baseline sensor UI/browser checks.
- [ ] Extend `software/studio/tests/sensors_e2e.mjs` to fail for missing inline preview, source gating, desktop/mobile layout and lifecycle cleanup. Add a source-policy unit test in `sensors_ui_unit.mjs`.
- [ ] In `web/sensors.js`, extract the existing session lifecycle and video screen without changing dedicated CameraPage behavior; add the compact preview with source gating and visibility cleanup.
- [ ] Pass API/overview route state through `web/app.js` and `web/pad.js`; put the preview below PadDuck. Adjust only relevant `pad.css`/`sensors.css` rules to avoid sticky overlap and fit 320px screens.
- [ ] Run tests red, implement, then green. Run sensor HTTP/backend, overview and virtual handpad regression suites; update the existing desktop sticky expectation to the explicitly approved nonoverlapping stack and retain posture data checks.
- [ ] Inspect generated desktop/mobile screenshots and correct layout issues. Request independent review and fix actionable findings.
- [ ] Update `software/studio/README.md`, commit verified UI, and integrate into local `studio-dev` without publishing unrelated training history. Refresh the local demo for user review; describe physical-camera and deployment limits honestly.
