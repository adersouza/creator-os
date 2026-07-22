# Creator OS Operator Failure Runbooks

These runbooks are for safe triage. They do not authorize bypassing gates,
editing production data by hand, or changing scheduling/publishing behavior.

## Publish Preflight Failure

Inspect:

- Campaign Factory publishability explanation.
- Dashboard preflight response and request payload.
- Handoff manifest ID and content surface.
- Account restriction and account-health state.

Do not touch:

- QStash dispatch retries.
- Published media rows.
- Account-health scores.
- Publishability gates.

Safe recovery boundary:

- Fix the source asset, caption, manifest, or metadata in the upstream system.
- Rerun preflight.
- Stop before export/schedule/publish unless the normal gate passes.

## QStash Dispatch Failure

Inspect:

- QStash message ID and delivery log.
- Dashboard publish handler logs.
- Idempotency key and target post/draft ID.
- Account restriction state at dispatch time.

Do not touch:

- Do not manually publish the same draft from a second path.
- Do not delete idempotency records.
- Do not clear restriction events to force dispatch.

Safe recovery boundary:

- Confirm whether the handler reached a terminal state.
- Retry only through the existing idempotent retry mechanism.
- Escalate if delivery status and local lifecycle state disagree.

## Account Restriction

Inspect:

- Restriction event timeline.
- Account health engine output.
- Recent failed preflights or publish responses.
- Whether the account is warming, restricted, or manually paused.

Do not touch:

- Do not schedule restricted accounts.
- Do not lower health gates.
- Do not delete restriction evidence.

Safe recovery boundary:

- Keep the account out of eligible pools.
- Add operator notes if supported.
- Resume only after the restriction system marks the account eligible.

## Inventory Buffer Shortfall

Inspect:

- `50-account-readiness` or staged acceptance output.
- Schedule-safe inventory by surface.
- Latest fresh Reel production batch results.
- Exception queue entries for inventory blockers.

Do not touch:

- Do not pad Reel runs with Story/feed/carousel assets.
- Do not clear quarantines or visual review flags just to pass a gate.
- Do not schedule below the required buffer.

Safe recovery boundary:

- Produce fresh schedule-safe inventory through the normal factory.
- Use old-asset repair only as bonus inventory.
- Rerun the acceptance gate before scheduling.

## Story/Reel Surface Mismatch

Inspect:

- Handoff manifest v2 source-lineage fields.
- Story native source proof fields.
- Visual quality status and no-text proof.
- Dashboard campaign surface validation result.

Do not touch:

- Do not convert Reel-rendered assets into Story proofs.
- Do not hide failed visual/source readiness behind `STORIES`.
- Do not bypass ThreadDash preflight.

Safe recovery boundary:

- Replace the asset with story-native media.
- Rerun Story quality and no-text gates.
- Stop if source-lineage blockers remain.

## Media QC Failure

Inspect:

- ffprobe metadata.
- frame readability.
- duration, dimensions, aspect ratio, codec, and audio presence.
- blank/near-duplicate frame checks.

Do not touch:

- Do not manually mark media QC passed.
- Do not crop or transcode production media without preserving lineage.
- Do not register repaired media over the old asset ID.

Safe recovery boundary:

- Regenerate or repair media through a lineage-preserving path.
- Create a new artifact hash and QC result.
- Rerun handoff readiness after QC passes.

## Paid Soul Or Kling Generation Blocked

Inspect:

- `CREATOR_OS_KILL_SWITCH` and the paid-generation enable flag.
- The live Higgsfield balance and native-credit quote.
- Daily, monthly, per-run, cohort, minimum-balance, and daily-Kling limits.
- The current `best_motion` model selection, spend authorization, candidate QC,
  and approval evidence. Inspect best-only Kling receipts only when reconciling
  historical records; they cannot authorize a new run.

Do not touch:

- Do not disable the kill switch merely to clear a failed smoke.
- Do not edit or delete spend reservations, selection receipts, or provider
  quotes.
- Do not infer candidate approval from a safe audit or from ranking output.

Safe recovery boundary:

- Keep the free static MP4 as the durable fallback.
- Resolve missing audit/approval/ranking evidence before requesting a new quote.
- Recheck the live balance immediately before an explicitly approved paid run.
- A ranking receipt selects a candidate; it never authorizes payment or
  publishing.

## Notify Publish Handoff Or Reconciliation Failure

Inspect:

- ThreadsDashboard post ID, account ID, publish mode, and handoff state.
- QStash delivery evidence and the notification/manual-confirmation timestamps.
- Instagram media ID, canonical permalink, Trial intent, and duplicate count.

Do not touch:

- Do not publish through a second path when the operator may already have
  completed Instagram publication.
- Do not create a replacement post merely because metrics or the permalink are
  delayed.
- Do not overwrite Trial intent while reconciling the final media ID.

Safe recovery boundary:

- Reconcile the existing post by its durable Creator OS/ThreadsDashboard keys.
- Require exactly one row for the Instagram media ID.
- Use the normal account-sync/per-post metric jobs after Mark Posted; never
  fabricate timestamps or metric rows.

## Performance Snapshot Missing Or Late

Inspect:

- Exact `published_at` and the expected 1h, 24h, or 72h window.
- QStash account-sync and per-post message delivery.
- `post_metric_history`, metric availability events, and the current
  performance-sync log.

Do not touch:

- Do not copy current post counters into a missing historical window.
- Do not manufacture a snapshot to satisfy cohort readiness.
- Do not run learning fanout before a real metric-history row exists.

Safe recovery boundary:

- Wait until the window is due, then use the normal idempotent sync path.
- Reconcile Campaign Factory, Reel Factory, and Reference Factory only after the
  real row is present.
- Keep readiness partial when 24h or 72h evidence is absent.

## Supabase Offsite Backup Or Restore Failure

Inspect:

- `com.creator-os.backup`, `offsite-backup`, `offsite-check`, and
  `offsite-restore-drill` launchd status and logs.
- The mode-0600 offsite environment/password files.
- The encrypted Restic manifest and Supabase `creator-os-backups` bucket.
- Repository integrity output and restored SQLite `PRAGMA integrity_check`
  results.

Do not touch:

- Do not delete bucket objects outside Restic retention/prune reconciliation.
- Do not restore a drill directly over the live runtime databases.
- Do not claim Time Machine protection when `tmutil destinationinfo` reports no
  configured destination.

Safe recovery boundary:

- Run backup/check/restore through their installed idempotent jobs.
- Restore into a temporary directory, verify all four SQLite databases and
  static allowlisted directories, then delete the drill directory.
- Supabase offsite recovery and Time Machine are separate layers. Time Machine
  remains an external-hardware task until an operator attaches and selects a
  destination disk.

## Weekly Improvement Digest Has Thin Evidence

Inspect:

- Measured snapshot counts per campaign and pattern.
- Recent pipeline failures and later-success recovery evidence.
- Known and unknown provider-credit amounts and Kling ROI state.

Do not touch:

- Do not accept a creative recommendation with fewer than three measured
  samples in its pattern.
- Do not treat a missing credit amount as zero.
- Do not let the digest mutate configuration, retry jobs, spend, or publish.

Safe recovery boundary:

- Continue the current control/ranked mix while evidence is thin.
- Review unrecovered failures separately.
- Apply only bounded, evidence-backed experiments after the minimum sample gate.
