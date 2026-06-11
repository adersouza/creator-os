# Supabase Migration Repair Plan

## Diagnosis

The staging migration failure is caused by migration-history drift, not by the staging smoke script.

Observed on May 26, 2026:

- Production project `apsrvwxfoomhtswlhczo` had 404 migration-history rows.
- Staging project `roobkkfvxqdlwlxcvbro` had 33 migration-history rows.
- The local repo had 416 migration files before repair.
- Staging stopped after `20260206000005_ig_pending_containers`, then had three staging-only MCP patch migrations.
- Local and production histories diverged for many later migrations. Example: production has `20260424041048_add_follows_and_reach_breakdown`, while local had `20260424100000_add_follows_and_reach_breakdown.sql`.

This makes Supabase branch creation/rebase unsafe because the platform sees local migration versions as unapplied even when equivalent schema changes already exist remotely.

## What Changed In This Repair Branch

- Added `npm run check:migrations`.
- Renamed the duplicate local migration version:
  - from `20260513000000_retry_aware_auto_post_queue_index.sql`
  - to `20260513000001_retry_aware_auto_post_queue_index.sql`
- Reconciled the first production-history drift batch by renaming local migration files to the exact versions recorded in production.
- Split the locally consolidated Composer phase 3 migration back into the three production migration-history entries.
- Added reconstructed historical marker migrations for production rows whose SQL had been consolidated into later idempotent local migrations.

## Next Repair Sequence

### June 8, 2026 Production Drift Repair

The production project `apsrvwxfoomhtswlhczo` was checked through the Supabase
connector and `supabase migration list --linked` on June 8, 2026. The latest
remote history rows included:

- `20260606103005_autoposter_autonomy_lineage_probe_fix`
- `20260606143000_restart_warmup_state`
- `20260606192305_claim_auto_post_queue_item_for_publish_rpc_text_id`

The local repo was reconciled to the remote versions for the equivalent
same-logical-name migrations:

- `20260606103005_autoposter_autonomy_lineage_probe_fix.sql`
- `20260606192305_claim_auto_post_queue_item_for_publish_rpc_text_id.sql`

The remaining local-only schema work was:

- `20260606192006_add_posts_content_surface.sql`

Because that local version was older than or equal to the newest remote version,
it was not an ordinary pending migration. The production schema already exposed
`posts.content_surface` in generated Supabase types, so the remote ledger was
repaired with:

```bash
supabase migration repair 20260606192006 --status applied --linked --yes
```

After repair, `supabase migration list --linked` showed the June 6 local and
remote histories aligned through
`20260606192305_claim_auto_post_queue_item_for_publish_rpc_text_id`.

The same audit found 19 older local-only history rows from April-May 2026 with
schema already represented in generated production types and readiness checks.
These were repaired as applied in the remote ledger:

- `20260426000000_cohort_pipeline`
- `20260427100000_rls_close_cross_tenant_reads`
- `20260505190000_index_posts_failed_updated`
- `20260505200000_notifications_subscription_dedup`
- `20260506010000_oauth_scope_drift`
- `20260506020000_tokens_and_fleet_metrics`
- `20260507190000_get_next_up_posts_account_ids`
- `20260508000000_drop_stale_inbox_views`
- `20260508040000_media_account_assignment`
- `20260510170000_storage_bucket_readiness`
- `20260512090000_api_idempotency_keys`
- `20260512100000_publish_jobs`
- `20260513000000_quota_race_hardening`
- `20260513000001_retry_aware_auto_post_queue_index`
- `20260513010000_reply_link_side_effect_hardening`
- `20260513120000_tenant_scoped_competitor_top_posts`
- `20260513143000_smart_link_attribution_hardening`
- `20260513170000_billing_entitlement_write_guards`
- `20260513210000_smart_link_custom_domains`

After this batch, `supabase migration list --linked` reported
`local-only=0` and `remote-only=0`.

1. Export production migration history:

   ```sql
   select version, name
   from supabase_migrations.schema_migrations
   order by version;
   ```

2. Run:

   ```bash
   npm run check:migrations -- --remote-history=path/to/production-history.json
   ```

3. Reconcile every remaining remote-only version, same-version name mismatch,
   and local history gap:

   - Restore committed migration files to the exact production versions when the SQL exists in repo history.
   - Archive or squash superseded local files only after `schema.sql` is verified to recreate the same schema.
   - Keep intentionally pending local migrations as local-only and document them.
   - Use `supabase migration repair --status applied <version>` only for a
     local migration whose schema is already present remotely.

4. Validate `supabase/schema.sql` and the full migration chain against an empty database before using them as a branch baseline.

5. Recreate the staging Supabase branch from the repaired migration history instead of continuing to patch the current staging branch.

6. Repoint Vercel preview env vars to the clean staging branch and rerun:

   ```bash
   npm run smoke:staging-scale
   ```

## Preview Branch Lifetime

The current Vercel preview branch should stay alive only as a temporary smoke surface while migration repair is in progress. Replace it after the repaired Supabase branch can be recreated from committed migrations and the staging-scale smoke passes against that clean branch.
