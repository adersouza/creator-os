# PLAN-SCHEDULER — Master Cross-Account Posting Schedule v3

This file records the implementation boundary for the locked scheduler plan supplied on 2026-07-09. Campaign Factory owns distribution, assignment eligibility, trial intent, and promotion history. ThreadsDashboard owns exact scheduled times and publishing. Reel Factory's posting ledger remains noncanonical operator UX.

Safety invariants:

- `auto_posting` remains `false`; no implementation in this plan queues or publishes automatically.
- Missing source-family and real perceptual identity is fail-closed to the first persisted `origin_account_id`.
- Cross-account reuse policy is evaluated by Campaign Factory and exported as `campaign_factory.assignment_eligibility.v1`.
- Trial graduation is manual, same-account, idempotent, and creates an unscheduled regular-reel plan.
- Exact schedule times are account-local ThreadsDashboard decisions; Campaign Factory times are preferences.
- Promotion identity comes from generated lineage. Campaign Factory promotion never computes a fallback fingerprint.

Implementation phases:

1. Reel Factory render/export identity: exact SHA-256 plus frame-sampled pHash and source-family lineage.
2. Fail-closed gate at distribution, assignment, reservation, promotion, CLI, and ledger UX boundaries.
3. Shared eligibility contract artifact and parity consumption without cross-package imports.
4. Trial intent, captured ingest proof, manual graduation, 1h/24h ranking, and 1-main/2-trial cadence defaults.
5. ThreadsDashboard per-account timezone/base slots, deterministic plus-or-minus 20 minute jitter, minimum gaps, and DST proof.
6. Constrained promotion store, typed append-only events, idempotent backfill, reconciliation, and read flip.

Production deployment, scheduling activation, publishing, QStash, account health, and autoposter activation are outside this implementation.
