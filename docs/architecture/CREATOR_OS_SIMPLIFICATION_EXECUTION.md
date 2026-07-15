# Creator OS Simplification Execution Ledger

Date started: 2026-07-15

This ledger implements the locked Creator OS simplification goal. It separates
source, CI, runtime, live seams, provider evidence, publishing evidence,
measured learning, Trial eligibility, backups, and cleanup eligibility. A green
source check never substitutes for missing operational evidence.

## Safety Boundary

- Campaign Factory remains the only operational brain and canonical ledger.
- ThreadsDashboard remains the only account, approval, scheduling, publishing,
  and production-metrics authority.
- Reel Factory creates media, Reference Factory teaches, and ContentForge
  judges/blocks.
- No factory merge, new dashboard, daemon, database, queue, Redis/RQ, Temporal,
  paid generation, schedule, publish, account reconnect, Trial canary, or
  retained-evidence deletion is authorized by this work.
- Public commands and contracts remain compatible unless a versioned
  replacement is explicitly recorded here.

## Authoritative Baseline

Captured from the clean source and detached runtime before implementation.

| Surface | Baseline evidence |
|---|---|
| Source | `main` clean at `5ba5ccc7e248513e3809fded2564fc483c14a1c7`, equal to `origin/main` |
| Runtime | clean detached checkout at the same `5ba5ccc7` revision |
| Worktrees | source and pinned runtime only |
| Open PRs | dependency-only PR #435; no active simplification PR |
| Live read-only status | 8 PASS, 0 FAIL/WARN/NOT_RUN/SKIP; HMAC handshake wrote zero product rows; provider probe created zero jobs and zero cost events |
| Canonical databases | Campaign, Reference, Reel manifest, and render queue all returned `PRAGMA integrity_check=ok` |
| Latest verified backup | `~/.creator-os/backups/runtime/20260715T224121Z` |
| Trial projection | 66 Instagram accounts: 0 eligible, 2 denied, 64 unknown; 0 with verified OAuth-scope evidence |
| Measured learning | 1 eligible post with a real 1h row; 0 with 24h; 0 with both; 50 remain for the autonomy gate |
| Retained Reel evidence | about 1.3 GiB `tmp`, 426 MiB models, 219 MiB audio library; preserved |
| Graphify | local graph exists; installed query skill/package versions differ and targeted queries returned low-fidelity schema matches, so repository architecture/static gates remain authoritative |

### Size Baseline

| File | Lines |
|---|---:|
| `reference_factory/reference_intake.py` | 3,876 |
| `reel_factory/reel_pipeline.py` | 3,498 |
| `reel_factory/generate_assets.py` | 2,424 |
| `campaign_factory/tests/test_core.py` | 27,065 |

`test_core.py` collects 495 tests before the split.

## Ordered Slices

| Slice | Owner | Status | Commit / PR | Evidence |
|---|---|---|---|---|
| 1. Canonical `GenerationExecutionPlan` | agent: generation execution plan | IN_PROGRESS | pending | pending |
| 2. Canonical `AccountEligibilityDecision` | primary agent | PENDING | pending | pending |
| 3. Common `ReadinessFinding` | primary agent | PENDING | pending | pending |
| 4. Slim ThreadsDashboard port | primary agent | PENDING | pending | pending |
| 5. Shared runtime-state evidence | agent: runtime state evidence | IN_PROGRESS | pending | pending |
| 6. Split oversized worker modules | unassigned until prerequisite slices land | PENDING | pending | pending |
| 7. Split Campaign test monolith | unassigned until affected production slices land | PENDING | pending | pending |
| 8. Legacy generation adjudication | unassigned until worker split inventory is stable | PENDING | pending | pending |
| 9. ContentForge export hygiene | agent: ContentForge export hygiene | IN_PROGRESS | pending | pending |
| 10. `CreativeKnowledgeService` | gated by 10-post operational proof | DEFERRED_BY_EVIDENCE | none | current proof is 1/10 and lacks 24h evidence |

Each code-bearing slice must land independently with focused tests, applicable
static/architecture/artifact/secret gates, a clean worktree, a pushed branch,
reviewed PR, and required CI before the next dependent slice is integrated.

## Operational Gates

### Trial Reels

Current state is not autonomous. Unknown is not eligibility. Denied accounts
must not be retried, and reconnects/canaries require exact account-level
operator authorization. The code goal is one fail-closed decision; Meta
eligibility remains external evidence.

### Learning

Campaign `performance_snapshots` remains the sole measured-facts ledger. Only
identity-matched posts with complete lineage and real metric history count.
The 10-consecutive-post operational proof and 50-post 1h+24h autonomy gate
remain closed until real evidence exists.

### Retained Evidence

The retained model, audio, database, migration, and E2E evidence is not a source
cleanup candidate merely because it is large. After the recorded July 22
retention deadline, the report-only verifier must prove retention, a completed
operating cycle, fresh backup/restore, private permissions, and zero active
references. Deletion still requires separate approval.

## Final Measurements And Verification

To be completed only after every actionable slice is merged and the reviewed
runtime is promoted. Record final file sizes, test counts, removed/retained
legacy callers, ContentForge export adjudication, full `make verify`, CI, exact
source/runtime SHA, live read-only status, performance-sync idempotency, backup
verification, branch/worktree cleanup, and every remaining external gate.
