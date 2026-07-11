# Operating Status Audit — 2026-07-10

Historical operating-status snapshot, refreshed after the July 10–11 rollout.
For current launch decisions, use `PIPELINE_STATE.md` and live gate output.

## Current system map

```text
Reference Factory teaches
  -> Reel Factory creates and records lineage
  -> Campaign Factory decides, gates spend, and exports drafts
  -> ContentForge judges through a local headless contract
  -> ThreadsDashboard handles approval-facing product UI, scheduling,
     publishing, and analytics
  -> hourly performance sync feeds measured outcomes back into learning
```

Creator OS is intentionally headless. ThreadsDashboard is the only retained
product UI. Creator OS operator actions are CLI commands plus local alerts.
Autoposter remains off and every cohort post still requires explicit approval.

## Verified current status

| Surface | Status | Evidence / remaining boundary |
|---|---|---|
| ThreadsDashboard HMAC ingest | Proven | Preview and production signed draft-only handshakes passed; HMAC-only enforcement enabled. |
| Paid provider acceptance | Proven narrowly | One-credit harness exercised quote, reservation, provider invocation, QC, lineage, and draft-only ingest. It did not schedule or publish. |
| Hourly learning sync | Working | Scoped to `stacey_learning_cohort_v1`, raised scan ceiling, pinned runtime/database launcher, fresh launchd exit 0. |
| Runtime backup | Working locally | WAL-safe SQLite snapshot job and ops-digest exit 0. Time Machine still lacks an external/network destination. |
| ContentForge | Headless migration complete | Local stdin/stdout JSON CLI owns `similarity` and `variant-pack`; Campaign Factory invokes it as a bounded subprocess. The Next.js/HTTP shell is deleted. |
| Creator OS GUI surfaces | Removed | Command-center, Reel GUI, and approval-board surfaces are deleted. Orchestrator `status`, `inbox`, and `decide` provide the retained operator contract; backend Reel Factory utilities remain in `operator_tools.py`. |
| Learning cohort | Armed, not autonomous | Runtime campaign exists; no claim of autonomous effectiveness until real posts and metric windows complete. |

## Completed audit work

- HMAC migrations, sender/receiver alignment, signed preview/production proof,
  and enforcement.
- Hourly active-campaign scope and scan-cap repair.
- One-credit real-provider acceptance.
- Branch unification and full gate runs.
- ContentForge browser UI deletion.
- Contract mirror consolidation, duplicate CLI removal, delegation-test
  deletion, and doctor simplification.
- Backup, ops-digest, and performance-sync launchd repairs.
- ContentForge extraction to `packages/contentforge`, subprocess-only Campaign
  Factory integration, and deletion of the local HTTP server contract.
- Creator OS GUI deletion with orchestrator CLI read/write parity retained.

## Completed headless migration

The deletion order is mandatory:

1. Exposed orchestrator `status` and `inbox` through its existing Python CLI.
   Approval writes already use `reel_factory.orchestrator decide`; keep its
   legal-transition and single-writer rules unchanged.
2. Added a ContentForge stdin/stdout JSON CLI for `similarity` and
   `variant-pack`; validate object JSON, time out, and fail closed.
3. Reused the same ContentForge implementation and fixtures beneath the CLI,
   then switched Campaign Factory to subprocess-only execution.
4. Removed `CONTENTFORGE_BASE_URL`, HTTP polling, and the Next.js server shell.
5. Deleted command-center, Reel GUI, and approval-board code after retaining
   their required CLI capabilities and paid-cost confirmation gates.

Do not absorb ContentForge’s FFmpeg/Python/Sharp engines into Campaign Factory.
Keep it as a bounded headless package with a schema-validated process contract.

## Operating exit gate

The code migration is complete. The next operational gate is one controlled
cohort day before any longer
run: two unique concepts, paid guard, ContentForge QC, explicit CLI approval,
HMAC draft ingest, no automatic publish, and a successful hourly metric sync.

Time Machine remains a hardware boundary: attaching an external disk or
network destination is required. The internal Recovery volume is not a backup.
