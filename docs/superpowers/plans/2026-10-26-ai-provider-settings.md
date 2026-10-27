# AI Provider Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement the integrated feature with spec and quality review. Steps use checkbox syntax for tracking.

**Goal:** A real persistent AI connection manager in existing Studio settings, with compatible-provider test and text chat, ready for later hardware voice integration.

**Architecture:** Private store + bounded backend Chat Completions client + authenticated/CSRF HTTP facade + small Preact settings card. No robot port, microphone ownership, model/gait or audio-service changes.

**Tech Stack:** Python3.13 standard library plus current Starlette, vendored Preact, unittest, Node and existing local Edge harness. No dependency installation needed.

## Task1: Integrated manager (one implementer)

Files:
- Create `software/studio/studio/ai_connections.py`: typed/whitelisted profile validation, private atomic state, redacted payload, current selection and masked secret operations.
- Create `software/studio/studio/ai_client.py`: compatible Chat Completions HTTP call, short test and bounded text reply, fixed safe error mapping, no redirects or automatic retries; no robot references.
- Modify `software/studio/studio/app.py`: instantiate store/service, GET and POST `/api/ai` with existing session/Origin/x-csrf guard, password requirement except dev-local mode, body bounds/no-store; blocking work off event loop. Keep routes and unrelated services intact.
- Create `software/studio/web/settings-ai.js`; modify `web/app.js` settings integration near top and `web/audio-interaction.js` settings link. Use existing look, compact explanatory copy, 320px layout and accessible labels.
- Create focused Python/unit+HTTP tests and Node tests where behavior warrants them.

- [x] Write failing tests for store persistence/Key redaction and draft readiness, atomic error preserving old data, activation/delete/edit behavior, URL/field validation and changed destination never reusing a stored Key.
- [x] Implement minimal store surface (adapt to existing service patterns), example public shape:

```python
{
  "profiles": [{"id": "generated-id", "name": "豆包", "provider": "doubao_ark",
    "base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": "",
    "key_configured": False, "ready": False, "missing": ["model", "api_key"]}],
  "active_id": None,
}
```

Never put `api_key` in this public shape. Persist a single0600 private state file atomically to avoid config/secret cross-file partial writes.

- [x] Red/green local mock HTTP tests for `POST {base_url}/chat/completions`, Bearer/explicit-none auth, real configured model/messages, short test response, text chat, errors/redirects/response size/timeouts. Keep credentials/results pinned to the saved configuration snapshot and invalidate stale UI results after edits.
- [x] Red/green real app HTTP tests: no unauthenticated GET/POST, password guard, exact existing Origin/CSRF requirement, malformed/oversize body, save/list/select/delete/test/chat, no Key or transcript leaks to logs/diag, no motion calls. Saving/selecting never contacts model endpoint.
- [x] Implement responsive settings UI: profile list/current badge, new/edit form/providerURL preset/model/manualKey/keep/remove/explicitnone, save/select/delete, test saved connection, text trial/clear. Only draft fields until save; dirty/incomplete configs cannot be tested. Disabled/busy/error/final states clear and honest. Abort UI request on component disposal; no cloud calls on render/save.
- [x] Run focused Python3.13 and Node checks, self-review, commit task files. Independent spec review first then quality review; implementer fixes findings and reviewers recheck.

## Task2: Controller verification/deployment

- [x] Actual local Edge + mock provider: create2profiles, save/reload/no Key in response or persistence in browser, select/edit/Key retention, test + multi-turn reply, clear/delete, error and320/390/1440 layouts; model mock captures actual valid request and no robot output.
- [x] Freeze code revision and stage only changed runtime files to duck; no real cloud call without user configuration. Verify device readback before service restart and keep existing data/settings/robotd/padd/duck-echo identities intact.
- [x] Update feature ledger F26 with installed vs locally tested vs real-cloud/hardware-voice limits; document actual endpoint/credentials instructions and reference sources. Keep music task recorded as unresolved, do not claim LLM fixes motor behavior.
