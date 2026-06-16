# Consolidation Plan — Pipeline into creator-os (Phase 2)

**Goal:** make `creator-os` the single canonical home + runtime for the four internal pipeline tools — `reel_factory`, `campaign_factory`, `contentforge`, `reference_factory` — and retire their standalone repos. This eliminates the monorepo↔split drift for those four (one copy, nothing to mirror). **ThreadsDashboard is NOT part of this — it stays a standalone product forever and remains a read-only mirror in creator-os.**

This runs AFTER the overnight remediation (`OVERNIGHT_EXECUTION.md`) finishes. It is staged and reversible: **archive before delete, prove before cut, gate green throughout.** No big-bang.

---

## Hard preconditions (do not start until ALL true)

1. WS1 parity gate is **live + blocking in CI** and green.
2. creator-os runs the four for real: `uv run pytest python_packages/{reel_factory,campaign_factory,reference_factory}/tests` + `pnpm --filter contentforge test` + `tests/integration` all green (the overnight 35-failure fix is this proof).
3. The four standalone repos and their creator-os mirrors are byte-identical per `pnpm check:mirror-parity` (no pending drift to lose).
4. Record current main SHAs of all four standalone repos in this doc before any change (rollback anchor).

If any precondition is false, STOP and report — do not consolidate on top of unfinished remediation.

## Rails

- **Archive, never hard-delete, in this pass.** Deletion is a separate owner decision after the soak.
- No destructive git (no force-push/history-rewrite) on the standalone repos.
- TD untouched.
- No secrets/scale work.
- Prove every step with a command; no "done" without it.

---

## Step 1 — Discover how the four are run/deployed (DO NOT GUESS)

Before changing anything, find every place that invokes or deploys the four from their standalone paths. Report a table, do not act yet.
- Search local + repos for invocations of the standalone paths (`/Users/aderdesouza/Developer/{reel_factory,campaign_factory,contentforge,reference_factory}`): shell scripts, cron entries (`crontab -l`), CI workflows, `Makefile`s, launch agents, any automation, and any docs/runbooks that tell a human to `cd` into them.
- For each: what runs it, how often, from which path.
- Output: `CONSOLIDATION_DISCOVERY.md` — every runner + its current path + the equivalent creator-os path it must repoint to.

## Step 2 — Make creator-os the runnable home

- Confirm each tool's CLI/entrypoint works from the monorepo (`uv run <cli> …`, `pnpm --filter <app> …`) exactly as it did standalone. Add thin wrapper scripts under `scripts/run/` if the old invocation paths need to keep working.
- Run a real dry-run of each tool from creator-os (no live publish/spend) and confirm output parity with the standalone behavior.
- Acceptance: each tool demonstrably runs from creator-os; documented in `CONSOLIDATION_DISCOVERY.md`.

## Step 3 — Repoint runners to creator-os

- Update each runner found in Step 1 (scripts, cron, CI, runbooks) to call the creator-os path/entrypoint instead of the standalone repo.
- Do them one tool at a time; after each, run that tool from the new path and confirm green.
- Acceptance: no active runner still points at a standalone repo path (re-grep proves zero).

## Step 4 — Flip source-of-truth + shrink the gate

- For the four tools, creator-os is now canonical. They are no longer mirrors. **Remove their entries from `mirror-sources.json`** (they're source now, not generated mirrors). After this, the ONLY remaining mirror is `apps/dashboard` ← ThreadsDashboard.
- `pnpm check:mirror-parity` must still pass (now governing only TD).
- Commit; the gate now enforces exactly one mirror (TD), which is correct.

## Step 5 — Archive the standalone repos (reversible)

For each of `reel_factory`, `campaign_factory`, `contentforge`, `reference_factory`:
- Add a top-level `ARCHIVED.md`: "Canonical home is `creator-os/<path>`. This repo is read-only. Do not commit." + the creator-os path + date.
- Commit + push that notice to the standalone repo's main.
- Archive on GitHub (`gh repo archive adersouza/<repo>`) — makes it read-only, fully reversible (`gh repo unarchive`).
- **Do NOT delete.** Deletion is Step 7, owner-gated, after soak.

## Step 6 — Soak (default 7 days)

- Run the pipeline entirely from creator-os for the soak window.
- Watch for anything that breaks or still reaches for a standalone repo (errors, missing paths, a cron that didn't get repointed).
- Log issues; fix forward in creator-os. The archived repos are the rollback if something is fundamentally wrong (`gh repo unarchive`, repoint back).

## Step 7 — Delete (owner-gated, after soak)

- Only after a clean soak AND explicit owner approval: delete the four standalone repos (or leave them archived indefinitely — archived is harmless).
- End state: **two repos** — `creator-os` (reel + campaign + contentforge + reference + pipeline_contracts + integration tests + governance) and `ThreadsDashboard` (the product, standalone, one read-only mirror in creator-os).

---

## Owner decisions (Codex: ask, don't guess)

1. **Soak length** — default 7 days. Confirm or change.
2. **Archive-only vs eventual delete** — default: archive now, decide delete after soak. Confirm.
3. If Step 1 finds a runner whose repoint is ambiguous (e.g. a deploy hook, a paid-generation cron), STOP and ask before repointing — don't risk live runs/spend.

## Deliverables

- `CONSOLIDATION_DISCOVERY.md` (every runner + old path + new creator-os path)
- Updated `mirror-sources.json` (four removed, only TD remains)
- `ARCHIVED.md` in each standalone repo + GitHub archive done
- A consolidation section appended to `OVERNIGHT_STATUS.md`/a new `CONSOLIDATION_STATUS.md`: what ran from creator-os green, what repointed, soak start date, rollback commands (per-repo unarchive + the recorded pre-change SHAs).

## Update these docs when done

- `MONOREPO_MIGRATION_MASTER_PLAN.md` — mark Phases 3/6 done for the four; note creator-os is canonical runtime for the pipeline; TD remains standalone.
- `AGENTS.md` / runbooks — point all pipeline run instructions at creator-os.
