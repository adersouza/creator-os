# Pipeline State

**Last updated:** 2026-07-02. This is the single source of truth for the current state of the Creator OS pipeline. It supersedes the old one-shot planning/runbook/audit docs (removed). Operational details live in `ARCHITECTURE.md`, `AGENTS.md`, and `docs/`.

## Architecture (two active product repos)

```
creator-os (this monorepo) — canonical runtime for the whole pipeline
├── apps/contentforge                  canonical (was a standalone repo)
├── apps/command-center                local operator app (port 4100)
├── python_packages/reel_factory       canonical
├── python_packages/campaign_factory   canonical
├── python_packages/reference_factory  canonical
├── packages/pipeline_contracts        shared contracts (canonical here; also its own repo)
└── tests/integration                  cross-tool integration

ThreadsDashboard (separate repo) ──deploys──▶ juno33.com   (the standalone product; permanently NOT in the monorepo)
```

## Current state (2026-07-02)

- **All plan-doc work is COMPLETE and the docs are deleted** (61 items + 12 gap-closure edges, PRs #323–#345, adversarially verified). Do not re-audit or recreate them; content is in git history.
- **Learning loop is closed and armed** (PRs #354/#355/#356): shared feature vocabulary (`reel_factory/feature_extract.py`), rank scoping + QC filtering, caption weights preserved on empty sync, `next_batch_plan` uses the full feature-key set. Hourly `sync_threadsdash_performance` runs via launchd on the operator Mac. Outcomes are 0 until posts flow — expected, not a bug.
- **Reference Factory teach loops are fed** (2026-07-02): 266 TikTok references imported, 1,330 frames OCR'd, audio patterns analyzed, 80-track audio catalog imported into Campaign Factory. Remaining: pattern export + `build-learning-system`; gold labeling is operator-only.
- **Instagram is the reel outlet (owner decision 2026-07-02), and the IG publish pipeline is BUILT and PROVEN** (35 reels published 2026-06-05..09; TD campaign scheduler is Instagram-only by design; licensed-embedded-audio path shipped CF #284 + TD #224). The only gap is a recurring trigger — closed by the orchestrator plan below. Do not re-declare IG "unbuilt".
- **Next build: orchestrator + approval inbox** (spec: operator's `~/.creator-os/specs/next-level-plan-2026-07.md`; PR slices A–E). Daily tick generates/advances assets through a state machine; top-k land in an approval inbox in `apps/command-center`. The inbox is the ONLY operator UI — no general dashboard.
- **ThreadsDashboard autoposter is OFF deliberately** (owner, 2026-06-30). Separate system from the reel pipeline; do not treat as an incident or restart unasked.

## Open work

1. **Recipe bandit reads legacy `publish_metrics`** (`campaign_store.py` `_recipe_bandit_state`) — migrate to `reel_outcomes` BEFORE deleting that table.
2. **Cost-preflight estimate omission**: `check_higgsfield_cost_preflight` skips the daily-budget check when `estimated_cost_usd is None` — make missing estimate blocking (companion fix in the orchestrator spec).
3. **reel_factory package migration**: ~78 flat root modules remain; migrate into `reel_factory/<mod>.py` with flat shim re-exports (13 shim-critical names; see VERIFICATION_WATCH_ITEMS.md).
4. **Verification watch items**: ranked-audio sidecar misattribution edge, grep-guard scope, video-QC requires `--download` in the same invocation (VERIFICATION_WATCH_ITEMS.md).
5. **Frontend decomposition debt** (ThreadsDashboard): `Composer.tsx` + `Autopilot.tsx` monoliths — tracked in TD issue #120; e2e for deep-link paths is the prerequisite.
6. **Archived standalone repos**: soak completed; deleting them is owner-gated and optional (archived is harmless).

## Owner-only (out of scope for automated agents)

- Secret rotation / OAuth re-encryption / git-history purge (P0) — provider consoles. See `docs/security/`.
- Scale proof (50/100/200 load, QStash-outage/reconciliation-drain).
- IG audio title resolution (optional), Time Machine backup destination, autoposter restart decision (30 accounts need reauth).

## How to work here

- Fix a tool: edit it in creator-os (it's canonical now), open a PR, green checks, merge.
- Dashboard work: fix it in `/Users/aderdesouza/Developer/ThreadsDashboard`; Creator OS has no committed dashboard mirror.
- See `AGENTS.md` for agent conventions and `ARCHITECTURE.md` for system design.
