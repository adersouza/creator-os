# ThreadsDashboard Performance Sync

Run performance sync locally, not from GitHub Actions. The learning SQLite
databases are gitignored local state, so an ephemeral GitHub runner cannot feed
the Reel Factory learning loop.

Required environment:

```sh
export CAMPAIGN_FACTORY_SYNC_CAMPAIGNS='["stacey_learning_cohort_v1"]'
export THREADSDASH_USER_ID="..."
export SUPABASE_URL="..."
export SUPABASE_SERVICE_ROLE_KEY="..."
export LEARNING_LOOP_CUTOVER="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export CAMPAIGN_FACTORY_DB="/absolute/path/to/campaign_factory.sqlite"
export REEL_FACTORY_ROOT="/absolute/path/to/python_packages/reel_factory"
export REFERENCE_FACTORY_DB="/absolute/path/to/reference_factory.sqlite"
export CAMPAIGN_FACTORY_SYNC_LIMIT=10000
```

`LEARNING_LOOP_CUTOVER` is the forward-only learning boundary. Raw performance
sync remains fail-open without it, but every learning reader fails closed and
returns no eligible snapshots until an ISO timestamp is configured. Set it once
at deployment; do not move it backward to backfill historical posts.

Roll out the lineage migration in this order:

1. Deploy the ThreadsDashboard contract mirror and dual-accept ingest first.
2. Verify the ingest accepts both `campaign_factory.threadsdash_drafts.v1` and
   `.v2`.
3. Deploy the Creator OS v2 producer and set `LEARNING_LOOP_CUTOVER` to that
   deployment instant.
4. Run the hourly command once manually and verify all three destination
reports before enabling the recurring job.

The hourly job reads only the explicit active campaign list in
`CAMPAIGN_FACTORY_SYNC_CAMPAIGNS`. Its default scan ceiling is 10,000 posts;
set `CAMPAIGN_FACTORY_SYNC_LIMIT` to another positive integer only when the
active campaign inventory requires it. Pagination still fails closed if rows
remain beyond the configured ceiling.

Never deploy the v2 producer ahead of the dual-accept consumer. Local code may
contain both halves during review, but the production order remains strict.

The hourly command has two phases in one job: Campaign Factory imports the raw
ThreadsDashboard snapshots, then `scripts/learning_fanout.py` fans only
`learning_eligible` snapshots to Campaign, Reel, and Reference through
`learning_fanout_ledger`. Do not restore the old standalone
`metrics_store.py refresh-outcomes` command; it bypasses cutover/provenance and
the correction/retraction ledger.

Each run reports history-source fallback counts and errors, ineligibility
reasons, per-destination `done` / `pending` / `reopenedByHash` / `retryCapped`
counts, and current 50-post 1h+24h readiness in one
`creator_os.hourly_learning_sync.v1` JSON document. `ledgerStates` separately
shows the final durable status counts, including capped rows from earlier runs.
`failed_capped` defaults to five
attempts and reopens only when the source hash changes or an operator explicitly
resets the ledger row.

To retry one deliberately reviewed capped row without changing its source,
reset only that exact destination key:

```sql
UPDATE learning_fanout_ledger
SET status = 'pending', attempt_count = 0, last_error = NULL
WHERE post_id = '<post-id>'
  AND snapshot_at = '<exact-snapshot-at>'
  AND destination = '<campaign|reel|reference>'
  AND status = 'failed_capped';
```

Dry-run the exact commands first:

```sh
python3 scripts/sync_threadsdash_performance.py --dry-run
```

Example `launchd` job, saved outside the repo as
`~/Library/LaunchAgents/com.creator-os.threadsdash-performance-sync.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.creator-os.threadsdash-performance-sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>bash</string>
    <string>-lc</string>
    <string>cd /Users/aderdesouza/Developer/creator-os &amp;&amp; source ~/.creator-os/performance-sync.env &amp;&amp; python3 scripts/sync_threadsdash_performance.py</string>
  </array>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>StandardOutPath</key>
  <string>/tmp/creator-os-performance-sync.out</string>
  <key>StandardErrorPath</key>
  <string>/tmp/creator-os-performance-sync.err</string>
</dict>
</plist>
```

Keep `~/.creator-os/performance-sync.env` local-only and mode `0600`.

`CAMPAIGN_FACTORY_SYNC_CAMPAIGNS` is an explicit JSON list. For this rollout it
must contain only `stacey_learning_cohort_v1`; the old single-campaign setting is
not accepted, preventing stale LaunchAgent configuration from syncing unrelated
campaigns.
