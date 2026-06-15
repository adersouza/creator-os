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
