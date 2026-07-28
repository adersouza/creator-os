# Content Director Operator Runbook

All commands use `scripts/creator-os` (or the promoted `creator-os` wrapper).
Planning `--apply` persists a plan only. It does not generate, export, schedule,
or publish.

## Plan

```bash
scripts/creator-os plan \
  --creator stacey \
  --horizon 7d \
  --accounts bennett_s33 \
  --goal growth \
  --dry-run
```

Repeat with `--apply --max-credits <signed-ceiling>` to persist the exact plan.

## Approve plan

```bash
scripts/creator-os plan approve <plan-id>
```

## Propose schedule and experiment

```bash
scripts/creator-os plan schedule-propose <plan-id> --dry-run
scripts/creator-os plan experiment <plan-id> \
  --variable hook_family \
  --variant curiosity \
  --variant confessional \
  --hypothesis "Observe which hook family retains more viewers at 24 hours" \
  --dry-run
```

These are proposals only. ThreadsDashboard remains final schedule authority.

## Execute

```bash
scripts/creator-os plan execute <plan-id> --dry-run
scripts/creator-os plan execute <plan-id> --apply --max-credits <signed-ceiling>
```

Apply submits only eligible uncompleted plan items through the existing normal
creation lane. Stop and reconcile ambiguous submissions; do not blindly retry.

## Review

```bash
scripts/creator-os plan review <plan-id>
scripts/creator-os plan review <plan-id> \
  --item <plan-item-id> \
  --action APPROVE \
  --reason "operator visual approval"
```

Actions are `APPROVE`, `REJECT`, `REQUEST_SMALL_EDIT`, `REPLACE_AUDIO`,
`REGENERATE`, `DEFER`, and `CANCEL`. A rejected output does not automatically
reject its source, pattern family, intent, provider, or capability. Blank fields
have no verdict.

## Export preview, status, learning, and replan

```bash
scripts/creator-os plan export <plan-id> --approved-only
scripts/creator-os plan status <plan-id>
scripts/creator-os plan list --creator stacey
scripts/creator-os learning-refresh --dry-run
scripts/creator-os learning-review list
scripts/creator-os plan replan <plan-id> --dry-run
```

The plan export command is an identity-complete preview; it performs no export.
Replan apply creates a successor version and retains completed/publication
lineage. Inspect every explained change before approval.

## Operating rhythm

Daily: inspect account health, reconcile ambiguity, review assets, inspect
today's proposals, missing metrics, experiments, blockers, and spend.

Weekly: refresh Audio Radar through its separately supported job, sync
performance, refresh knowledge, review recommendations, generate the next
seven-day plan, inspect mix/capacity, approve adjustments, and authorize a
bounded generation batch. Nothing auto-approves a recommendation or publishes.
