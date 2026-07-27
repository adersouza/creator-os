# Creator OS Operator Journey

This is the normal product path. Advanced model, benchmark, queue, and analyzer
commands are diagnostics, not normal inputs.

## 1. Inspect the system

```bash
creator-os status
creator-os status --creator stacey
creator-os audio status
```

The scoped commands require draft PR #527 until it is reviewed and merged.
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

This surface requires draft PR #526. Approval never generates or publishes.

## 3. Make three passive Stacey Reels

Dry-run:

```bash
creator-os create \
  --creator stacey \
  --intent passive_selfie \
  --count 3 \
  --execution cloud \
  --accounts stacey-main \
  --audio embedded_trending \
  --max-credits <authorized-cap>
```

The plan must name the creator/account/intent, count, approved sources, expected
provider credits, Audio Radar policy, data to be written, receipt destinations,
and explicitly state that it will not export, schedule, or publish.

After reviewing the bounded quote, repeat with `--apply`. Three independent
jobs must preserve partial successes and produce three local review-ready MP4s.

## 4. Review

```bash
creator-os review --campaign <campaign>
```

Compare source, output, prompt, recipe, audio, cost, lineage, and technical QC.
Record identity, anatomy, motion, phone-native appearance, audio fit, would-post
decision, and notes. Blank fields are unreviewed, not rejected.

## 5. Approve Reel 2

Use the exact rendered asset shown by review:

```bash
creator-os approve \
  --campaign <campaign> \
  --rendered-asset-id <reel-2-asset-id> \
  --user-id <threadsdashboard-user-id> \
  --approved-by <operator>
```

Approval binds the exact MP4 hash and QC/lineage evidence. It does not publish.

## 6. Preview and export

```bash
creator-os export \
  --dry-run \
  --campaign <campaign> \
  --user-id <threadsdashboard-user-id> \
  --rendered-asset-id <reel-2-asset-id> \
  --max-drafts 1
```

After verifying account, caption, final SHA, embedded audio, and no schedule or
publish action:

```bash
creator-os export \
  --apply \
  --campaign <campaign> \
  --user-id <threadsdashboard-user-id> \
  --rendered-asset-id <reel-2-asset-id> \
  --max-drafts 1
```

Creator OS ends at validated draft handoff.

## 7. Publish through ThreadsDashboard

In ThreadsDashboard, verify the stable draft identity and account preflight,
then explicitly schedule or publish. A queue receipt is not publication.
Closure requires a reconciled Instagram media ID.

## 8. Metrics and learning

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
