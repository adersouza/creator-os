# Creator OS Complete Audit Map

This is the active coverage index for the 26-area Creator OS audit. The
pre-hardening evidence snapshot remains at
[`archive/creator_os_complete_audit_map_20260730_pre_hardening.md`](archive/creator_os_complete_audit_map_20260730_pre_hardening.md).
Durable behavior belongs in [`../../CREATOR_OS_SYSTEM_MAP.md`](../../CREATOR_OS_SYSTEM_MAP.md);
changing source/runtime/operational facts belong in
[`../../PIPELINE_STATE.md`](../../PIPELINE_STATE.md).

Status language is strict:

- **source-complete**: an owner, legal path, evidence, and recovery path exist.
- **operational**: the installed runtime has exercised the path successfully.
- **collecting**: the system is working but needs real elapsed-time outcomes.
- **external/manual**: another owner or operator must perform the final effect.

| # | Area | Canonical owner and evidence | Current state |
|---:|---|---|---|
| 1 | Repository census and execution topology | `CREATOR_OS_SYSTEM_MAP.md`, package CLIs, architecture checks | source-complete |
| 2 | Runtime, promotion, and rollback | `scripts/creator-os promote`, authenticated promotion and rollback receipts | operational; every new merge still needs exact-SHA promotion |
| 3 | Databases and migrations | domain repositories, schema versions, migration ledgers, `scripts/reel_database_readiness.py` | source-complete; migrate canonical Reel DBs only from a verified backup |
| 4 | Configuration, environment, and secrets | runtime-path resolver, fail-closed env loaders, secret scan | source-complete |
| 5 | Creator identity lifecycle | creator governance, Soul/reference approvals, suspension and retention state | source-complete |
| 6 | Campaign lifecycle | campaign governance and legal transition services | source-complete |
| 7 | Daily production orchestration | Campaign Factory `orchestrate-daily`, `scripts/run_daily_orchestrator.sh` | source-complete; recurring plan mode requires one supervised runtime plan |
| 8 | Source-asset intake and catalog | source registry, exact SHA, media probe, creator/campaign attribution | source-complete |
| 9 | Filesystem and artifact storage | canonical runtime roots, atomic file operations, backup and reconciliation receipts | source-complete |
| 10 | Prompt and model governance | prompt registry, low-effort creative context, exact provider/model/request fingerprint | source-complete |
| 11 | Reference Factory lifecycle | authorized intake, signed rights lifecycle, patterns, invalidation, promotion | source-complete |
| 12 | Reel Factory local rendering | deterministic static render, caption placement, audio binding, atomic finalization | source-complete |
| 13 | ContentForge analyzer governance | pinned analyzers, fixture calibration, production-authority qualification | source-complete; real-sample qualification is machine-specific evidence |
| 14 | Provider cost and budgets | quote, authorization, attempt, reconciliation, unified ledger | source-complete |
| 15 | Operator CLI and authority | dry-run/apply separation, signed approvals, audited destructive actions | source-complete |
| 16 | Observability, reconciliation, and incidents | pipeline jobs, activity events, bounded reconciliation summaries and guarded repairs | source-complete |
| 17 | Scale and capacity | capacity runbooks, SQLite/index checks, provider and batch caps | source-complete; million-asset production load remains unclaimed |
| 18 | Learning and experiments | immutable observations, equal-age cohorts, supervised recommendations | operational and collecting real outcomes |
| 19 | Multi-creator isolation | creator-bound sources, prompts, accounts, inventory, approvals, and learning scope | source-complete |
| 20 | Security and local trust boundaries | safe paths/subprocess arguments, schema validation, redaction, secret scanning | source-complete |
| 21 | Privacy, likeness rights, and retention | creator consent/governance plus signed reference-provider rights evidence | source-complete |
| 22 | Backup, restore, and disaster recovery | canonical-root backup, coverage audit, restore verification, rollback bundle | source-complete; installed backup drift must remain monitored |
| 23 | Test architecture and release gates | focused suites, contracts, architecture checks, `make verify`, runtime health | source-complete |
| 24 | Dependencies and supply chain | lockfiles, pinned native tools/models, Trivy, CodeQL, secret scan | source-complete |
| 25 | Operator reports and dashboard truth | Creator OS receipts plus ThreadsDashboard scheduling/publication truth | source-complete; publication remains external |
| 26 | Deprecation and legacy removal | runtime reachability classification and read-only historical compatibility | source-complete; removal stays evidence-driven |

## Execution topology

```text
operator or recurring trigger
→ Campaign Factory reads governance, inventory, learning, and budgets
→ Reel Factory writes exact visual/audio bytes and lineage
→ ContentForge writes blocking QC evidence
→ Campaign Factory records exact-SHA review and signed draft handoff
→ ThreadsDashboard owns schedule, publication, reconciliation, and metrics
→ measured outcomes return to supervised Creator OS learning
```

Every mutating entrypoint must identify:

```text
owner → data read → data written → external effect
→ receipt → downstream consumer → failure/recovery owner
```

## Remaining proof, not missing architecture

- Paid provider generations require fresh spend authority and operator review.
- Instagram, Reddit, and Story publication require their platform-specific
  external/manual owner.
- Learning strength requires real equal-age 24-hour and 72-hour outcomes.
- Large-scale and different-Mac restore claims require those environments.

These are evidence windows or external effects. They must not be reported as
source gaps, silently simulated, or marked complete from fixtures.
