# Action Recipes Implementation Plan

> **For agentic workers:** Use subagent-driven-development to implement tasks and review integration. User has approved execution in this chat.

**Goal:** Connect existing action recipes to real HD1910 training, bounded evaluation and export.

**Architecture:** Separate engine registrations, public recipe catalog/service validation, and UI selector. Keep three existing recipes stable. New task IDs end `-Studio-HD1910`; catalog and engine contracts are independently verified.

**Tech Stack:** Python3.12, mjlab1.3.0/MuJoCo Warp, PPO/rsl_rl, Preact HTM.

## Tasks

- [x] Engine: add tests for35 descriptor mappings and31 independent configs; generalize HD1910 deep-copy adaptation, left kick registration and passive joint handling; preserve original task cfgs. Four teacher-dependent joint variants remain blocked in Studio. Run CPU configuration checks, then sequential GPU smoke.
- [x] Catalog/service: extend `training_studio/config.py` using a focused recipe module; specify31 launchable and4 prerequisite-only variants; preserve existing3. New IDs use `hd1910-<upstream slug>`, explicit task/experiment names agreed with engine. Extend bounded evaluation allowlist. Test creation, command matching, smoke gate and prerequisite rejection before spawn.
- [x] UI: adapt action cards/details and NewRun to large searchable directory, source/hardware and teacher prerequisites; blocked recipes open explanatory detail with links to teacher recipes. Preserve selected recipe and folded advanced controls. Verify JS state and browser flows.
- [ ] Integration: run Python/Node regressions, check catalog/engine parity, sequential64×5 smoke for every independent task and representative evaluation/export. Save evidence outside state; update per-recipe verification only from successful records. Review against spec and code quality; integrate to studio-dev preserving unrelated changes; show8094 after safe active-run check.

## Verification commands

`E:\Python312\python.exe -m unittest discover -s tests -v` from `software/training-studio`; `node --test tests/*.test.mjs`; WSL locked training Python for engine configuration and GPU smoke. Browser uses headless Edge against isolated8095 before stable8094.
