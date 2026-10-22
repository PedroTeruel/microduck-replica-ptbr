# Microduck Training Studio — 2026-10-22

Approved direction: an independent English-named folder under `software`, a Chinese-first visual training workspace, simple defaults with collapsible advanced controls, visible progress, and genuine pause/resume behavior. Existing engine stays in `../training`; robot controls stay in `../studio`.

## First release

- A cloud/local GPU training service and a browser UI. No account/billing platform or robot motion commands.
- HD1910 flat and rough velocity recipes; flat is the initial recommendation. Both are simulation baselines, not certified hardware policies.
- An environment check before real training. Windows can run the explicitly marked CPU demonstration; real training requires the existing Linux/NVIDIA environment and frozen engine dependencies.
- A short run is always 64 environments / 5 iterations and only checks the pipeline. Formal training is a separate choice and requires a successful short run for the same recipe and effective configuration family.
- Basic fields: name, recipe, smoke/formal run, optional duck profile. Advanced fields only expose actual engine arguments: environment count, iteration limit, save interval, seed, learning rate. No decorative controls for unsupported rewards.
- A persistent run list, real logs/iteration metrics, saved checkpoints, and a detail page. Refreshing or closing the browser must not stop a run.
- Linux pause uses process-group SIGSTOP/SIGCONT and retains memory; it does not stop GPU rental billing. Stopping retains already-written checkpoints. Continuing a stopped run creates a new run from a selected checkpoint. No claim that an interrupt saves the current iteration.
- Checkpoint evaluation runs a bounded MuJoCo rollout on the GPU machine and records a video. An untrained CAD preview is labeled as a model preview. Demonstration animation is explicitly labeled as a motion illustration, never inference evidence.
- Export uses the existing `scripts/export.py` with its embedded observation normalizer, then packages ONNX, effective configuration, optional profile, source/checkpoint provenance and available evaluation evidence. Demonstration export contains no fake ONNX or PT file.
- Duck profile data is archived and summarized for compatibility review. Calibration, masses and inertia are not silently applied to physics.
- One active GPU operation at a time. Invalid transitions and mismatched checkpoints are rejected by the server.

## Interface

Desktop sidebar: workspace, experiments, models, environment. Primary panel: selected run or onboarding with an actual CAD model, latest checkpoint evaluation video, concise status, progress chart, checkpoint timeline and collapsible log. A new-run drawer progressively reveals advanced fields. Changed advanced values remain visible as a count and difference summary when collapsed. Mobile layout keeps controls reachable without horizontal overflow.

Every screen in demo mode carries a visible demo label. Empty, loading, disconnected, unauthorized and failure states have actual messages. Buttons use pending states, and errors are shown without replacing the page. No random live-looking production metrics.

## Architecture and files

`run.py` is a standard-library Python HTTP entry point. `training_studio/` owns recipe validation, process control, durable run storage, metrics parsing, checkpoint/evaluation/export work and HTTP routing. `web/` owns browser state, components and styling; no build step or external CDN. `tests/` contains behavior and subprocess tests. `dev/` contains a headless browser acceptance script. Shared 3D/viewer assets are served from explicitly allowed paths in sibling `../studio/web`, retaining their existing notices and licenses.

Default listener is loopback. Non-loopback hosting requires an explicit access token; origin/host validation and path containment protect mutation and download endpoints. State/log directories are ignored. Training commands are argv lists with allowlisted numeric arguments, never shell text.

## API contract (v1)

- `GET /api/state`: `{mode, environment, recipes, runs, active_run_id}`.
- `GET /api/environment`: environment diagnostic.
- `GET /api/runs/{id}`: full run, `metrics`, `checkpoints`, `logs` and effective `config`.
- `POST /api/runs`: `{name, recipe_id, kind, config, profile?}` → `{run}` (201). `kind` is `smoke` or `train`.
- `POST /api/runs/{id}/pause|resume|stop`: `{run}`. A paused resume continues its process; a stopped resume accepts `{checkpoint_id}` and returns the new run.
- `POST /api/runs/{id}/evaluate|export`: `{checkpoint_id}` → `{run}`; operation progress appears in detail `operation`.
- `GET /api/artifacts/{id}/{relative-path}`: contained downloadable artifact, including video or model package.
- `GET /shared/...`: explicitly allowlisted sibling Studio viewer assets only.
- Errors: `{error, detail?}`, HTTP 400/401/403/404/409 as appropriate. Optional token header `X-Studio-Token`.

Run fields: `id,name,recipe_id,task_id,kind,mode,status,phase,created_at,updated_at,config,progress:{iteration,total,elapsed_seconds},metrics:[],checkpoints:[],logs:[],operation?,error?,parent_id?`. A metric has `iteration,reward?,episode_length?,fps?`. A checkpoint has `id,iteration,name,created_at,video_url?,export_url?,demo?`. Statuses: `starting,running,paused,stopping,stopped,completed,failed,interrupted`; an operation can be `running,completed,failed`.

Recipe fields: `id,title,description,task_id,defaults:{num_envs,iterations,save_interval,seed,learning_rate},hardware,validation`. Environment: `ready,pause_supported,checks:[{name,ok,detail}],gpu?,training_root`.

## Acceptance

Automated tests exercise invalid config and transitions, process pause/resume/stop, checkpoint association and resume, persistence, smoke gating, artifact containment, JSON/HTTP errors, and authentication. Browser tests create a demonstration run, collapse modified advanced settings, pause/resume, inspect history/checkpoints, compare runs and export records. Desktop/mobile render checks inspect page errors and overflow. GPU-dependent code is clearly separated; do not claim GPU validation on this Windows machine.

## Studio visual alignment (2026-10-22)

The user requested the training UI match the existing central Studio. Use the central app's actual `software/studio/web/styles.css` and navigation, rather than introducing a second visual identity. The training service stays independent.

Use the same 26 px black/white/yellow duck mark, 216 px light sidebar, 56 px top bar, gray `#F2F2F7` canvas, white 16 px cards, `#1D1D1F` text, black pill primary buttons and gray radial 20 px CAD stage. Use the same Chinese system font stack, 28 px page titles and readable 12–15 px labels/body. Blue indicates interaction and primary chart series; orange distinguishes the comparison series with adequate contrast on white. Green, amber and red continue to communicate actual statuses. Remove decorative English slogans, beta labels and avatars. At 700 px and below, expose all four routes in a fixed bottom tab bar with space reserved in page content. Keep demo labeling, advanced controls, process actions and checkpoint semantics unchanged.

Acceptance compares live central Studio and training screenshots on desktop and phone, then repeats real demo browser flows, responsive navigation, modal focus handling, no horizontal overflow, and console/network checks.
