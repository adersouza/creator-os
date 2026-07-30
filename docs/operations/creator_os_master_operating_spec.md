# Creator OS Master Operating Specification

**Status:** active product policy
**Reconciled:** 2026-07-28

This document records the operator's current product decisions. The durable
component map is [`../../CREATOR_OS_SYSTEM_MAP.md`](../../CREATOR_OS_SYSTEM_MAP.md).
Dated audits preserve historical proof but do not override this policy.

## Product Outcome

Creator OS must provide a dependable daily content system that:

1. starts from an approved creator identity and source;
2. creates or reuses a postable visual;
3. applies only a supported creative recipe;
4. adds the correct verified audio;
5. preserves complete immutable lineage;
6. blocks technically invalid media;
7. requires exact-SHA human creative approval;
8. exports a validated draft;
9. leaves account scheduling and publication to ThreadsDashboard;
10. learns only from real, comparable, publication-linked outcomes.

The normal operator thinks in creator, intent, count, account, audio, and
budget—not provider implementation identifiers.

## Active Creative Policy

### Normal provider

Higgsfield is the only active normal visual-generation provider.

Normal production must not:

- choose WaveSpeed;
- fall back to WaveSpeed;
- require `WAVESPEED_API_KEY`;
- route through Arena or Router;
- choose a local model;
- silently substitute an unresolved recipe.

Historical WaveSpeed receipts, rows, costs, media, hashes, and lineage remain
readable.

### Supported visual recipes

| Product need | Current policy |
|---|---|
| New creator still | Higgsfield Soul 2 with explicit creator Soul ID |
| Zero-cost Reel from still | deterministic local static MP4 |
| Passive motion | product-pinned Higgsfield Kling 3 or Seedance 2 |
| Finished Creator OS media | strict existing-media reconciliation |
| Reference-Reel structure recreation | bounded experimental Seedance 2 path |

The passive recipe disables provider-generated sound. The product configuration,
not the ordinary operator, selects Kling 3 or Seedance 2.

### Unresolved capabilities

- talking selfie with exact supplied creator voice;
- motion copy or dance transfer;
- talking motion copy.

The tested Kling Motion Control results remain rejected. InfiniteTalk remains
rejected for robotic voice quality. Veo text dialogue is not represented as
creator-voice preservation. Unresolved does not mean permanently removed; it
means normal production must fail before a paid request.

### Human quality authority

The operator's would-post decision outranks vendor marketing and aggregate
technical scores. Review binds the exact final MP4 SHA.

Required human fields may include:

- identity;
- anatomy;
- attractiveness;
- natural motion;
- motion-copy accuracy when relevant;
- casual-phone appearance;
- lip-sync and voice quality when relevant;
- would post;
- notes.

Blank means unknown/unreviewed. Automated identity or anatomy approval must not
be claimed when no analyzer reported it.

## Source And Identity Policy

- Every source must be creator-bound and explicitly approved.
- Stored source bytes must match their SHA-256 before use.
- A creator Soul ID is explicit internal configuration and must match the
  selected creator.
- Source compatibility is checked before paid submission.
- Learning may reorder approved sources but cannot approve one.
- A source failure or incompatibility must remain visible so later batches do
  not repeatedly spend against it.
- Reference-performer identity never substitutes for the intended creator.

## Batch Policy

`count=N` means N independent retained jobs.

Each job keeps:

- source identity and SHA;
- prompt and fingerprint;
- seed;
- provider request/generation ID;
- quote and authorization;
- output and output SHA;
- QC evidence;
- audio choice and segment;
- final media SHA.

Partial success is preserved. An ambiguous provider submission is reconciled,
not blindly retried.

## Spend Policy

- Dry-run is the default for generation planning.
- Every paid apply requires a finite maximum credit ceiling.
- Quote and live balance are checked before submission when exposed.
- Unknown cost is not zero.
- Authorization is scoped to the exact creator, job, provider, model/tool,
  source/anchor/reference hashes, resolved prompt, seed, executable command,
  work item, attempt, request fingerprint, amount, and expiry.
- Authorization is consumed once at the provider-call boundary.
- `providerRequestFingerprint` identifies the exact remote request.
  `executionFingerprint` additionally binds local output/review destinations and
  the Reel Factory plan version.
- The provider plan is rebuilt and its signed scope is compared immediately
  before authorization consumption. Any request or quote-fingerprint change
  requires a fresh authorization.
- A batch may not exceed its total cap or one authenticated balance snapshot
  after the retained minimum and existing active reservations. Authorization is
  serialized under the provider-account lock.
- Concurrent jobs use provider-reported credits only. If those credits are not
  exposed, per-job actual cost remains unknown; a shared account-balance delta
  is never guessed as one job's cost.
- Actual cost below the authorized maximum is valid. Unknown actual cost remains
  unknown. Actual cost above the maximum is recorded, raises a
  `provider_overspend` incident, and blocks asset progression.
- No automatic paid retry is allowed for ambiguity.
- Campaign-owned provider attempts progress through durable effect states:
  `PRE_EFFECT`, `AUTHORIZATION_CONSUMED`, `SUBMISSION_STARTED`,
  `EXTERNAL_ID_KNOWN`, `PROVIDER_COMPLETED`, `OUTPUT_RETAINED`, and
  `COST_RECONCILED`, with explicit failed, ambiguous, and no-effect states.
- Completed exact local receipts recover without a provider quote or balance
  read. Downloads use a staged file, receipt checkpoint, and atomic final rename;
  mismatched collisions are quarantined rather than overwritten.
- `campaign-factory provider reconcile` reports consumed-without-submission,
  ambiguous submission, missing output, missing cost, and missing registration
  contradictions without making another provider call.
- The global kill switch blocks paid generation and outbound draft export while
  leaving read-only diagnosis and zero-cost local rendering available.

Provider caps are operator/runtime configuration, not an invitation to spend
the entire amount.

Kling 3 Turbo exposes no sound-control argument in the authenticated command.
Its authorization therefore records no fictional sound flag; silent output is a
postcondition, and any returned audio stream is rejected. Kling 3 and Seedance
retain their actual exposed sound-disable arguments.

## Visual And Caption Policy

### Still generation

The active still path is direct reference-image Soul generation. It preserves
the input reference, Soul ID, provider prompt, generation ID, and output hash.

The established original/body-emphasis variant recipe remains:

1. clean the reference of cropable UI;
2. run one reference-conditioned Soul generation;
3. capture and clean the provider composition prompt;
4. retain that output as the original;
5. create the optional body-emphasis variant text-only so the edit survives;
6. preserve both receipts and review the exact outputs.

### Burned overlay text

- Overlay text comes from the caption bank.
- Reel Factory placement decides the lane.
- Instagram Sans Condensed is the default font.
- Stacey/Larissa use the `stacey_static_center` preset when appropriate.
- No safe lane means no burned overlay.
- Post captions remain separate Campaign/ThreadsDashboard metadata.

Do not force an overlay across the creator's face or body focal area.

## Audio Policy

For eligible non-talking Reels, the normal path is verified embedded trending
audio:

```text
active Audio Radar cache
  -> fit/cooldown/uniqueness ranking
  -> duration-compatible segment
  -> source probe and SHA
  -> processed-segment SHA
  -> AAC embedding
  -> final stream verification
  -> exact final MP4 binding
```

Provider-generated audio remains disabled for passive motion.

The receipt must preserve:

- platform and music ID;
- title;
- canonical artist when known;
- sound owner separately;
- trend source;
- source track SHA;
- acoustic fingerprint;
- segment start/end;
- processed segment SHA;
- final MP4 SHA.

A re-embed creates a new final artifact and requires a new binding and review.

Talking content cannot use trending audio as a substitute for unresolved
creator speech.

## Audio Radar Refresh Policy

- SocialCrawl TikTok trending videos are the primary TikTok discovery source.
- SocialCrawl Instagram is used when available.
- TikTok Creative Center is optional enrichment.
- TikLiveAPI resolves selected TikTok music IDs.
- The per-run download cap is `--max-new`.
- Provider failures and invalid empty feeds are unavailable observations, not
  successful absences.
- An all-source outage cannot age or prune active tracks.
- Pruning requires two valid consecutive absences and all retention gates.
- Sound-owner metadata is not silently presented as performer metadata.

The refresh never generates, exports, schedules, or publishes.

## QC And Approval Policy

Hard technical blockers remain mandatory:

- missing, symlinked, escaped, or hash-mismatched files;
- invalid or undecodable media;
- unacceptable stream/aspect/duration requirements;
- duplicate output bytes where distinct jobs are required;
- blocking collision/distinctness evidence;
- unsafe or unverified caption placement;
- missing required embedded-audio proof;
- final receipt/media SHA mismatch;
- invalid lineage;
- revoked or missing creative approval.

Soft attractiveness, motion, and taste signals may rank candidates but do not
replace the human would-post decision.

## Existing-Media Policy

Existing-media intake is allowed only for media whose source, generation,
provider receipt, raw visual, final MP4, audio, and technical-QC evidence can
all be resolved by exact hashes.

Intake:

- is dry-run first;
- does not regenerate or re-encode;
- is idempotent;
- does not copy arbitrary downloaded/camera-roll media into canonical state;
- does not approve, export, schedule, or publish.

Exact-SHA review and compatible plan attachment remain separate actions.

## Reference-Reel Policy

`recreate_reel` accepts one explicitly authorized Instagram, TikTok, YouTube
Short, direct-media URL, or local video. Creator OS uses its own downloader and
private local storage; third-party downloader websites are not part of the
system.

- Dry-run downloads and derives media only in a temporary directory.
- Authorized apply deduplicates by platform/media identity and exact SHA,
  stores private artifacts outside Git, and records the reference audio as one
  canonical Audio Radar identity plus occurrence.
- `--through analyze` stops before visual-provider selection, spend
  authorization, or generation. An authenticated Gemini CLI may make one
  read-only structural-analysis call and records its unexposed cost honestly.
- Planning classifies the source, selects a bounded coherent excerpt, and
  records source writing separately, creates a timecoded motion/camera
  breakdown, and proposes a clean-opening-frame-matched Soul anchor.
- Every generated anchor requires human identity and
  `WOULD_USE_AS_ANCHOR` approval before video generation.
- `AUTO` may recommend an experimental route but may not silently submit it.
- Passive Kling 3 is accepted; structural Seedance, Motion Control, and
  first/last remain explicitly reviewed experimental routes.
- Structural Seedance uses `seedance_2_0 mode=fast`, the bound creator Element
  first, the approved anchor as an image reference, and the Reel only as a
  video reference. It does not combine reference-media mode with start/end
  images or copy source writing into its prompt.
- Motion Control does not claim exact choreography, Seedance does not claim
  performer replacement, and talking remains blocked when exact supplied-voice
  entitlement is absent.

The inspiration Reel is reference evidence, never the intended creator asset.
No intake or plan action exports, schedules, or publishes.

## Content Director Policy

The Content Director is supervised planning inside Campaign Factory.

- `SHADOW` proposes only.
- `SUPERVISED` persists only operator-reviewed bounded decisions.
- `APPROVED_PLAN_AUTOPILOT` may execute only an immutable already-approved item
  set inside signed bounds.
- No mode grants publication authority.

Planning may use only approved sources and approved prompt patterns. It may not
change identity, Soul ID, provider, visual recipe policy, QC, spend, account
authorization, safety, or publication eligibility.

## Cadence And Scheduling Policy

- A healthy eligible account normally targets approximately one regular Reel
  per day.
- Every-other-day cadence is reserved for warming, account health/platform
  limits, insufficient approved inventory, or explicit operator choice.
- Each account advances independently.
- Minimum post gaps remain enforced.
- Pending or stale schedules must be reconciled before new external schedules.
- Content Director times are proposals.
- ThreadsDashboard is final scheduling authority.
- Learned timing is false unless valid supervised timing evidence actually
  applied.

The current fixed Stacey cohort proposes three consecutive eligible account-
local days at approximately the same local time. Publication does not wait for
the previous Reel's 72-hour observation.

## Publication Policy

Creator OS ends at validated draft handoff.

ThreadsDashboard owns:

- account projection and health;
- final account authorization;
- draft approval;
- scheduling;
- publish preflight;
- QStash/Meta/Notify Publish behavior;
- Instagram media-ID reconciliation;
- canonical analytics.

Queue, upload, handoff, schedule, and notification evidence are not publication.
Publication requires a real reconciled Instagram media ID.

Notify/manual completion is an operator assertion, not publication identity.
ThreadsDashboard keeps that post in `publishing` until account sync binds a
real Instagram media ID and records the reconciliation method and confidence.
Both auto/API and notify/manual handoffs require ThreadsDashboard post approval.

## Learning Policy

Eligibility for an operator-reviewed early advisory requires:

- at least three real eligible examples;
- same creator and identity profile;
- matching account scope;
- same content intent;
- equal-age 24-hour or 72-hour observations;
- real Instagram media identity;
- valid source/final-media lineage;
- current fingerprints;
- explicit operator approval.

One-hour evidence is advisory. Missing is never zero.
Three or four comparable outcomes remain `early_advisory`; five through nine
are `preliminary_direction`; ten or more are
`stronger_directional_evidence`. Only a controlled matched experiment may be
described as a causal-evidence candidate. Account-group, creator-wide, and
global evidence remains advisory-only; current production consumption still
requires the exact account match.

Only `SUPERVISED_ACTIVE` recommendations may affect:

- ordering among approved sources;
- ordering among imported approved hooks/prompt patterns;
- Audio Radar soft performance ranking with exact publication linkage.

Learning cannot select a provider/model, modify spend or QC, authorize a source,
change account policy, or publish.

## Runtime And Promotion Policy

Source and runtime remain separate clean checkouts. Merge does not promote.

Promotion requires:

- exact clean `origin/main`;
- strict admin-enforced branch protection;
- protected PR checks `affected`, `hygiene`, and `Secret scan`;
- separate exact-SHA release, Secret scan, CodeQL JavaScript/TypeScript, CodeQL
  Python, and Trivy evidence;
- authenticated operator authority;
- runtime lock, backup manifest, Git bundle, rollback, dependency verification,
  and complete read-only runtime health.

Promotion must not mutate providers, databases, schedules, publishing,
production accounts, or ThreadsDashboard deployment.

## Operational Completion

Creator OS source is complete for the supported scope when the exact merged
source can produce an approved visual, verified embedded audio, final hash-bound
approval, and valid draft handoff.

Runtime is aligned only after explicit promotion to that exact SHA.

The production loop is operationally proven only when:

1. a real approved Reel is published through ThreadsDashboard;
2. its real Instagram identity and final media are reconciled;
3. equal-age 24-hour or 72-hour observations are stored;
4. at least three comparable examples create an eligible recommendation;
5. the operator activates it;
6. a later create decision receipt proves an allowed choice actually changed.

Do not use fixtures, queued receipts, or a single early observation to claim
that real adaptive improvement is proven.
