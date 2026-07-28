# Creator OS Documentation Map

This index separates active operating authority from dated evidence and
historical design work.

## Active Authority

Read in this order:

1. [`../AGENTS.md`](../AGENTS.md) — repository working rules and current
   creative product decisions.
2. [`../CREATOR_OS_SYSTEM_MAP.md`](../CREATOR_OS_SYSTEM_MAP.md) — durable
   architecture, ownership, lifecycle, and evidence boundaries.
3. [`../README.md`](../README.md) — supported operator entrypoints.
4. [`../PIPELINE_STATE.md`](../PIPELINE_STATE.md) — dated source/runtime and
   operational snapshot.
5. [`operations/creator_os_master_operating_spec.md`](operations/creator_os_master_operating_spec.md)
   — active product policy and invariants.

## Active Architecture

- [`architecture/autonomous_content_director.md`](architecture/autonomous_content_director.md)
  — supervised plan domain and authority.
- [`architecture/content_director_scheduling.md`](architecture/content_director_scheduling.md)
  — account-local cadence and proposal policy.
- [`architecture/content_director_experiments.md`](architecture/content_director_experiments.md)
  — bounded experiment semantics.
- [`architecture/content_director_capacity_and_rollout.md`](architecture/content_director_capacity_and_rollout.md)
  — rollout truth and scale gates.
- [`architecture/media_provenance_contract.md`](architecture/media_provenance_contract.md)
  — immutable media identity.
- [`architecture/creative_approval_and_ai_disclosure.md`](architecture/creative_approval_and_ai_disclosure.md)
  — exact-SHA review and disclosure.
- [`architecture/monorepo_deployment_promotion.md`](architecture/monorepo_deployment_promotion.md)
  and [`architecture/runtime_promotion_runbook.md`](architecture/runtime_promotion_runbook.md)
  — guarded source-to-runtime promotion.
- [`architecture/github_protection_settings.md`](architecture/github_protection_settings.md)
  — current three-context protected-branch policy and separate exact-SHA
  promotion evidence.
- [`architecture/tooling_hardening.md`](architecture/tooling_hardening.md) —
  verification and dependency rules.

## Active Operations

- [`runbooks/creator_os_operator_journey.md`](runbooks/creator_os_operator_journey.md)
  — normal create/review/approve/export sequence.
- [`operations/audio_refresh.md`](operations/audio_refresh.md) — live weekly
  Audio Radar refresh.
- [`operations/creative_quality_review.md`](operations/creative_quality_review.md)
  — provider contract and human review boundary.
- [`operations/learning_cohort_daily.md`](operations/learning_cohort_daily.md)
  — fixed-cohort daily controller.
- [`operations/reference_refresh.md`](operations/reference_refresh.md) —
  Reference Factory refresh.
- [`operations/threadsdash_performance_sync.md`](operations/threadsdash_performance_sync.md)
  — canonical metrics return.
- [`runbooks/stacey_real_learning_proof.md`](runbooks/stacey_real_learning_proof.md)
  — real supervised-learning proof sequence.
- [`runbooks/operator_failure_runbooks.md`](runbooks/operator_failure_runbooks.md)
  and [`runbooks/content_director_failure_matrix.md`](runbooks/content_director_failure_matrix.md)
  — recovery boundaries.

## Provider Truth

- [`providers/higgsfield_production.md`](providers/higgsfield_production.md) —
  active normal provider recipes.
- [`providers/HIGGSFIELD_CAPABILITY_AUDIT_2026-07-27.md`](providers/HIGGSFIELD_CAPABILITY_AUDIT_2026-07-27.md)
  — authenticated capability snapshot from that date.
- [`providers/wan_wavespeed.md`](providers/wan_wavespeed.md) — historical
  WaveSpeed implementation evidence; not an active production guide.

## Research And Historical Evidence

The following are retained for evidence and context, not current operator
instructions:

- `docs/archive/`;
- dated migration, stabilization, simplification, debloat, local-model, and
  split-repository documents;
- `CREATOR_OS_TARGET_STATE_PROGRESS_AUDIT.md`;
- `CREATOR_OS_BLOAT_INVENTORY.md`;
- `CREATOR_OS_SIMPLIFICATION_PLAN.md`;
- `reports/`;
- `research/`;
- local Wan/LTX Arena/Router documentation.

Historical rows, receipts, media, and hashes remain readable even when the
corresponding execution path is no longer active.

## Resolving A Conflict

If documents disagree:

1. inspect the actual code and current command schema;
2. use `AGENTS.md` for active operator decisions;
3. use `CREATOR_OS_SYSTEM_MAP.md` for ownership;
4. use the active master operating specification for product policy;
5. use fresh read-only status for volatile state;
6. treat older dated documents only as evidence of their capture date.

Do not silently import an old model, cadence, native-audio, branch-protection,
or runtime assumption into current production.
