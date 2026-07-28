# Creator OS Operator Journey

This is the normal product path. Advanced model, benchmark, queue, and analyzer
commands are diagnostics, not normal inputs.

Creator OS owns creation through validated draft handoff. ThreadsDashboard owns
the final account preflight, schedule, publication, and real Instagram
reconciliation. Normal daily use does not require choosing Higgsfield model
identifiers, WaveSpeed, a local model, Arena, or Router.

## 1. Inspect the system

```bash
creator-os status
creator-os status --creator stacey
creator-os status --learning
creator-os audio status
creator-os plan list --creator stacey
```

Status is read-only. It should show the runtime SHA, approved source count,
active audio count, waiting work, failures, spend evidence, and next valid
action.

## 2. Approve creator sources once

List Stacey inventory:

```bash
creator-os sources list --creator stacey
```

Preview an exact hash-bound decision:

```bash
creator-os sources approve \
  --creator stacey \
  --source /absolute/path/to/reviewed-source.png \
  --operator <operator> \
  --reason "identity and composition reviewed"
```

Apply only after the preview is correct:

```bash
creator-os sources approve \
  --creator stacey \
  --source /absolute/path/to/reviewed-source.png \
  --operator <operator> \
  --reason "identity and composition reviewed" \
  --apply
```

Approval never generates or publishes.

## 3. Preview a supervised seven-day plan

```bash
creator-os plan \
  --creator stacey \
  --horizon 7d \
  --accounts bennett_s33 \
  --goal growth \
  --count 5 \
  --mode shadow \
  --max-credits <authorized-cap> \
  --dry-run
```

Shadow planning is mutation-free. It may rank only explicitly approved sources
and approved patterns. It proposes posting windows but cannot schedule or
publish. If the plan is later persisted, inspect it through:

```bash
creator-os plan list --creator stacey
creator-os plan show <plan-id>
creator-os plan status <plan-id>
```

Plan execution delegates to the normal create lane and still requires signed
spend authorization. The plan is not a second generation or publishing system.

## 4. Make three passive Stacey Reels

Dry-run:

```bash
creator-os create \
  --creator stacey \
  --intent passive_selfie \
  --count 3 \
  --execution cloud \
  --accounts bennett_s33 \
  --audio embedded_trending \
  --max-credits <authorized-cap>
```

The plan must name the creator/account/intent, count, approved sources, expected
provider credits, Audio Radar policy, data to be written, receipt destinations,
and explicitly state that it will not export, schedule, or publish.

After reviewing the bounded quote, repeat with `--apply`. Three independent
jobs must preserve partial successes and produce three local review-ready MP4s.

## 5. Review

```bash
creator-os review --campaign <campaign>
```

Compare source, output, prompt, recipe, audio, cost, lineage, and technical QC.
Record identity, anatomy, motion, phone-native appearance, audio fit, would-post
decision, and notes. Blank fields are unreviewed, not rejected.

## 6. Approve the selected Reel

Use the exact rendered asset shown by review:

```bash
creator-os approve \
  --campaign <campaign> \
  --rendered-asset-id <selected-asset-id> \
  --user-id <threadsdashboard-user-id> \
  --approved-by <operator>
```

Approval binds the exact MP4 hash and QC/lineage evidence. It does not publish.

## 7. Preview and export

```bash
creator-os export \
  --dry-run \
  --campaign <campaign> \
  --user-id <threadsdashboard-user-id> \
  --rendered-asset-id <selected-asset-id> \
  --max-drafts 1
```

After verifying account, caption, final SHA, embedded audio, and no schedule or
publish action:

```bash
creator-os export \
  --apply \
  --campaign <campaign> \
  --user-id <threadsdashboard-user-id> \
  --rendered-asset-id <selected-asset-id> \
  --max-drafts 1
```

Creator OS ends at validated draft handoff.

## 8. Publish through ThreadsDashboard

In ThreadsDashboard, verify the stable draft identity and account preflight,
then explicitly schedule or publish. A queue receipt is not publication.
Closure requires a reconciled Instagram media ID.

Healthy eligible accounts normally target one regular Reel per account-local
day. Use every-other-day cadence only for warming, account/platform
constraints, insufficient approved inventory, or an explicit operator choice.
ThreadsDashboard must reconcile stale or pending schedule state before adding a
new post.

## 9. Metrics and learning

Machine-local performance sync records canonical metric history. Compare like
age with like age. Missing remains missing.

Preview learning:

```bash
creator-os learning-refresh --dry-run
creator-os learning-review list
```

After at least three comparable real 24h or 72h outcomes, apply the refresh and
explicitly approve one recommendation:

```bash
creator-os learning-refresh --apply
creator-os learning-review approve \
  --id <recommendation-id> \
  --operator <operator> \
  --reason "three comparable measured outcomes reviewed"
```

Run the next `creator-os create` dry-run normally. Its decision receipt must say
whether learning was consulted, eligible, applied, and actually changed the
final choice. Consultation alone is not adaptation.

## Existing Media Intake

Use this path only for an already-finished Creator OS MP4 with exact retained
source, generation, audio, QC, and final-media lineage. It is not a camera-roll,
downloaded-Reel, or arbitrary historical upload path.

1. Build or inspect one private `creator_os.existing_video_intake.v1` manifest.
   It must identify the exact creator-bound source, generation attempt and
   provider receipt, raw visual, final MP4, audio fulfillment receipt, and
   technical-QC receipt by path and SHA-256.
2. Resolve it without writes:

   ```bash
   creator-os media intake-existing \
     --manifest /absolute/private/path/video.intake.json \
     --dry-run
   ```

   Review every resolved hash, blocker, existing canonical asset, and proposed
   mutation. A filename is never evidence. Dry-run creates no approval, asset,
   plan binding, export, schedule, or publication.
3. Approve the exact source separately with `creator-os sources approve
   --apply` only after its hash-bound preview is reviewed. Intake may preserve
   historical evidence while the source remains unapproved, but the asset
   cannot become executable or export-ready.
4. Apply the intake:

   ```bash
   creator-os media intake-existing \
     --manifest /absolute/private/path/video.intake.json \
     --apply
   ```

   Apply registers or reconciles one canonical `rendered_asset`. It does not
   copy, re-encode, replace audio, or alter the MP4. Repeating the exact intake
   reconciles the existing identity. Original generation spend remains in its
   lineage; intake itself invokes no provider.
5. Record a durable review for the exact final asset and SHA:

   ```bash
   creator-os media review-existing \
     --asset <rendered-asset-id> \
     --final-sha <sha256> \
     --reviewer <operator> \
     --verdict WOULD_POST \
     --apply
   ```

   `WOULD_POST`, `USABLE_AFTER_EDIT`, and `REJECT` are distinct verdicts.
   Blank granular fields remain unknown, and approval of one final SHA never
   transfers to another re-embedded SHA.
6. Attach only to a compatible approved plan item:

   ```bash
   creator-os plan attach-existing <plan-id> \
     --item <plan-item-id> \
     --asset <rendered-asset-id> \
     --dry-run
   ```

   After reviewing all gates, repeat with `--apply`. Attachment records
   `existing_canonical_asset`, costs zero, retains the original generation
   history, and does not claim the Content Director generated the media during
   that plan.

   For a deliberate same-intent learning cohort, use the explicit supervised
   cohort surface instead of changing asset metadata or weakening the rolling
   planner:

   ```bash
   creator-os plan cohort \
     --creator stacey \
     --account <account> \
     --intent passive_selfie \
     --asset <asset-1> \
     --asset <asset-2> \
     --asset <asset-3> \
     --observation-cohorts 1h,24h,72h \
     --mode supervised \
     --timezone America/New_York \
     --dry-run
   ```

   Apply performs only versioned planning, observation expectations, and exact
   existing-asset attachment. It makes no provider call and does not export,
   schedule, or publish. With no explicit `--start-date`, the account/cohort
   timezone determines the date. The three assets propose three consecutive
   eligible local days at approximately the same local time with
   `learnedTiming=false`. Ordinary rolling plans retain their diversity rules.
7. Export only after source approval, exact technical QC, `WOULD_POST` review,
   compatible plan attachment, and all ordinary export gates pass.

Source approval and creative approval are separate decisions. Intake and plan
attachment never publish; a draft or queue receipt is not publication proof.

## Recovery

- Provider ambiguity: reconcile the original generation ID; never resubmit
  blindly.
- Audio outage: retain the generated video and active cache; never silently
  ship mute.
- Export mismatch: stop and compare the approved local SHA with remote bytes.
- Publish ambiguity: reconcile Instagram identity; never assume dispatch means
  publication.
- Missing metrics: retry sync; never write zero.
- Stale/revoked recommendation: deterministic base behavior resumes.
- Runtime issue: use the recorded promotion receipt and rollback SHA; do not
  modify canonical state.
