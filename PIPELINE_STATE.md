# Pipeline State

**Last updated:** 2026-07-07. This is the single source of truth for the current state of the Creator OS pipeline. It supersedes the old one-shot planning/runbook/audit docs (removed). Operational details live in `ARCHITECTURE.md`, `AGENTS.md`, and `docs/`.

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

## Current state (2026-07-07)

- **All plan-doc work is COMPLETE and the docs are deleted** (61 items + 12 gap-closure edges, PRs #323–#345, adversarially verified). Do not re-audit or recreate them; content is in git history.
- **Learning loop is closed and armed** (PRs #354/#355/#356): shared feature vocabulary (`reel_factory/feature_extract.py`), rank scoping + QC filtering, caption weights preserved on empty sync, `next_batch_plan` uses the full feature-key set. Hourly `sync_threadsdash_performance` runs via launchd on the operator Mac. Outcomes are 0 until posts flow — expected, not a bug.
- **Reference Factory teach loops are fed** (2026-07-02): 266 TikTok references imported, 1,330 frames OCR'd, audio patterns analyzed, 80-track audio catalog imported into Campaign Factory. Remaining: pattern export + `build-learning-system`; gold labeling is operator-only.
- **Instagram is the reel outlet (owner decision 2026-07-02), and the IG publish pipeline is BUILT and PROVEN** (35 reels published 2026-06-05..09; TD campaign scheduler is Instagram-only by design; licensed-embedded-audio path shipped CF #284 + TD #224). Do not re-declare IG "unbuilt".
- **Orchestrator + approval inbox wiring is merged** (PR #370 and prerequisites): the gated tick can run `pipeline_run`, require an estimated cost before paid generation, ingest pipeline evidence, promote top-ranked assets into `awaiting_approval`, and export approved sidecars. It remains disabled until the operator sets local config with `enabled = true`.
- **Recipe bandit reads `reel_outcomes`** (`campaign_store.py` `_recipe_bandit_state`): the legacy `publish_metrics` table remains only in compatibility/write/export/test paths and must not be deleted until those references are retired.
- **ThreadsDashboard autoposter is OFF deliberately** (owner, 2026-06-30). Separate system from the reel pipeline; do not treat as an incident or restart unasked.

## Open work

1. **Operator enablement**: create local orchestrator config and flip `enabled = true` only after confirming campaign, creator, reference image, and cost estimate.
2. **Gold labeling**: reference labels remain operator-only; do not force coverage with uncertain labels.
3. **Time Machine backup destination**: still unconfigured on the operator Mac.
4. **ThreadsDashboard hosted reliance remains external**: local `main` contains the `fix/mobile-verification-findings` merge; hosted/mobile reliance still belongs to the external ThreadsDashboard repo.
5. **Frontend decomposition debt** (ThreadsDashboard): `Composer.tsx` + `Autopilot.tsx` monoliths — tracked in TD issue #120; e2e for deep-link paths is the prerequisite.
6. **Archived standalone repos**: soak completed; deleting them is owner-gated and optional (archived is harmless).

## Owner-only (out of scope for automated agents)

- Secret rotation / OAuth re-encryption / git-history purge (P0) — provider consoles. See `docs/security/`.
- Scale proof (50/100/200 load, QStash-outage/reconciliation-drain).
- IG audio title resolution (optional), autoposter restart decision (30 accounts need reauth), and provider-console work.

## How to work here

- Fix a tool: edit it in creator-os (it's canonical now), open a PR, green checks, merge.
- Dashboard work: fix it in `/Users/aderdesouza/Developer/ThreadsDashboard`; Creator OS has no committed dashboard mirror.
- See `AGENTS.md` for agent conventions and `ARCHITECTURE.md` for system design.
