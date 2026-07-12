# Creator OS Master Operating Specification

Status: **LOCKED — operator questionnaire answered 2026-07-11**

This document is the implementation authority for the current Creator OS
production-readiness goal. It incorporates the operator's 101 answers and
explicit confirmation that every depicted model is over 18. Where the operator
selected the recommendation, the recommendation is binding until changed here.

## Locked Outcome

Creator OS must become a usable headless production system that:

1. Accepts a reference image and creates a Soul still with captured provider
   prompt and complete lineage.
2. Supports an original candidate and an explicitly governed text-only sexy
   candidate without accidentally repeating the paid reference generation.
3. Automatically creates a free static MP4 for every accepted Soul still.
4. Keeps the static MP4 as the zero-cost fallback output.
5. Offers paid Kling animation only for the best approved candidates.
6. Enforces explicit spend limits and approval boundaries before paid Kling
   submission.
7. Runs identity, anatomy, Reel Factory, and ContentForge gates before draft
   handoff.
8. Sends only signed, draft-only payloads to ThreadsDashboard until publishing
   is separately approved.
9. Preserves ThreadsDashboard as the scheduling and publishing authority.
10. Collects real 1h, 24h, and 72h outcomes and feeds them back into selection
    and reference learning.

## Locked Operator Decisions

### Business outcome and scale

- Primary outcome: grow Stacey's Instagram reach and drive trackable traffic to
  her OnlyFans funnel. Revenue is not a learning input because it is not
  currently observable; use views, engagement, follows, profile visits, and
  attributable link clicks in a weighted score.
- Benchmark direction: the manually operated `@staceybennetx` Instagram account.
- Stacey launches first, then Stacey1, Larissa, Lola, and the operator's other
  verified models. Every creator learns independently.
- Target fleet: approximately 200 accounts. Existing generated media is the
  launch inventory; reference-conditioned Higgsfield generation ramps in over
  subsequent weeks instead of blocking launch.
- Per-account target: one regular reel daily or every other day plus one or two
  trial reels daily. The planner must treat this as a capacity target, not a
  reason to bypass inventory, uniqueness, account-health, or publish gates.
- Initial proof remains a bounded 50-post cohort. It is a launch gate, not the
  long-term manual workflow.
- Instagram is the initial platform.

### Creative and age policy

- All depicted models are verified by the operator as over 18.
- When age wording improves Soul output, the creative prompt uses exactly
  `19 years old`. Age verification stays in metadata/QC, not in creative prose.
  Do not use `adult`, `woman`, `girl`, `teen`, or ambiguous `young` age wording
  in the generation prompt.
- Default look: strongly sexy, candid/amateur, believable phone/selfie or
  propped-camera footage. Mirror selfies, selfies, and casually placed-camera
  scenes are preferred over polished luxury/editorial scenes.
- Sexy does not mean only more exposed skin. Allowed emphasis includes fuller
  cleavage, tight clothing, an amateur feel, and a mischievous expression.
- Preserve identity, pose, outfit, setting, lighting, and expression. Do not
  alter the waist or add unrelated body/scene changes. Selfies may emphasize
  chest/cleavage; full-body shots may additionally emphasize a rounder butt.
- Stacey identity guidance includes dark hair and no tattoos. Identity guidance
  must be applied without overriding the Soul identity.
- Bikinis, lingerie, sheer-but-covered clothing, and deep cleavage are allowed.
  Reject visible nipples, explicit nudity, extreme explicitness, age ambiguity,
  or failed identity/anatomy evidence.
- Block cigarettes, drugs, weapons, and controversial themes by default. Keep
  the reference setting rather than inventing luxury context.

### References and generation

- Reference inputs may come from Reference Factory, operator-uploaded folders,
  and reviewed public examples/accounts.
- Gold references are automatic-first; `maybe` requires approval; `ignore` is
  excluded and may be deleted after evidence retention.
- Select by measured performance when available, balance visual-driven and
  caption-driven patterns, and cap source-account concentration.
- Reuse strong references when useful, but vary captions/timing and keep similar
  uses separated across accounts. Crop salvageable interface borders; reject
  interface elements covering the subject.
- Reference approval is batch-based and must be easy for the operator to review.
- One reference-conditioned Soul pass produces and preserves the original.
  Capture its provider prompt. Create one text-only sexy candidate without
  paying to regenerate the original. One automatic retry is allowed only after
  identity/anatomy failure; then reject the reference.
- Generate in the aspect ratio that best serves the shot (`3:4`, `2:3`, or
  `9:16`), then produce the Instagram-ready 9:16 reel without destructive
  subject cropping.
- Reference Factory is the long-term learning source: successful past assets,
  prompts, patterns, captions, and measured outcomes become future generation
  examples so the system does not depend forever on new reference images.

### Static MP4, captions, and audio

- Every QC-passing still produces a free-provider-cost static MP4; failed stills
  do not. Duration is deterministically randomized within 5–7 seconds.
- Preserve a clean locked/no-zoom MP4 and, when caption placement passes, a
  captioned MP4. The clean static remains the fallback for every candidate.
- Overlay hooks come from the caption bank. Use Instagram Sans Condensed by
  default and the approved larger bold style occasionally. Caption work remains
  an active weekly optimization area.
- Placement must find the best safe lane and never cover the face/body focal
  area. If no safe lane survives measurement, regenerate for negative space or
  use the clean MP4; do not force an unsafe overlay.
- Burned overlay text and post captions remain separate. Campaign Factory owns
  post captions.
- Native/platform audio remains a ThreadsDashboard or Notify Publish decision.
  Evaluate a free audio path, but do not burn or license audio speculatively.

### Paid Kling policy

- Kling may run only after at least two safe, human-approved static candidates
  are ranked and one unique best candidate receives a durable selection receipt.
- Rank with identity/anatomy as hard gates and a balanced score using visual
  quality, attractiveness, reference fidelity, predicted engagement, and the
  optional Higgsfield virality predictor when it is free. Explain wins/losses.
- Never animate a candidate that failed identity, anatomy, ContentForge, human
  approval, or receipt validation. If Kling fails, retain/use the static MP4.
- Operational ceiling: at most 10 Kling videos in one day, with zero automatic
  paid retries. This is a ceiling, not a daily target.
- Hard monthly provider ceiling: 1,000 credits across Soul/Higgsfield/Kling,
  subject to live balance verification. Pace daily spending so the monthly
  allocation cannot be exhausted early; the runtime must fail closed if current
  balance or price is unknown.
- Each Kling charge requires explicit approval until at least five real paid
  runs complete successfully. Afterwards, only receipt-backed candidates may
  use an operator-configured automatic budget lane.
- Investigate provider-supported no-audio/short-duration/settings options before
  changing the assumed price. Never claim savings without a live quote.

### Drafts, scheduling, and publishing

- After approval, signed HMAC draft creation is automatic and idempotent: one
  winning asset creates exactly one ThreadsDashboard draft.
- Creator OS never publishes directly. All posts flow through ThreadsDashboard,
  which either uses the approved Meta publishing path or sends a Notify Publish
  handoff to the operator's phone for accounts operated there.
- Human final approval is required during the initial cohort and the first day
  or two of launch. The target state is no routine manual posting except phone
  Notify Publish accounts.
- After proof, high-confidence posts may auto-schedule and automatic publishing
  becomes an operator-controlled option. Native-audio/publishability proof still
  applies to direct TD publishing.
- Account assignment is automatic. Trial reels test non-follower distribution
  and may use different/randomized posting windows from regular reels.
- Use randomized, testable posting windows. Keep identical/similar visuals and
  captions far apart across accounts; change overlay/caption/other safe features
  where appropriate.
- One confirmed publish/reauth failure pauses the account. A global kill switch
  stops paid generation, drafts, scheduling, and publishing.

### Learning, operations, and operator experience

- Always collect 1h, 24h, and 72h evidence; 24h is the primary reward.
  Normalize per account and learn original-vs-sexy and Kling-vs-static lift.
- Notify actionable failures immediately via macOS and Discord; send routine
  state in a daily digest.
- Run headlessly after reboot. Keep the machine light: short local hot retention,
  offload durable approved media/evidence to the configured Supabase recovery
  layer, and delete expired rejected media only after retention proof.
- Produce a weekly improvement digest covering performance, caption/reference/
  timing experiments, Kling ROI, failures, recommended configuration changes,
  and the next bounded tests. Recommendations must cite real outcome evidence.
- The operator experience must not require terminal commands for routine use.

## Current Safety State

- Paid generation stays disabled except for an explicitly approved bounded run.
- `CREATOR_OS_KILL_SWITCH=1` is the canonical emergency stop. It blocks every
  Creator OS paid-generation reservation and outbound ThreadsDashboard draft
  export while leaving read-only checks and local zero-cost static rendering
  available for diagnosis and recovery.
- Automatic publishing stays disabled.
- Native audio is selected and verified in ThreadsDashboard, not burned into
  Creator OS MP4s.
- A ContentForge blocking code rejects the candidate.
- No readiness claim may substitute tests or fixtures for a real approved post
  completing the performance loop.

## Resolved Implementation Gaps

1. Campaign Factory now invokes the captured-prompt variant policy directly:
   the completed reference-conditioned original supplies the provider prompt,
   and a separate image-only call creates the text-only sexy candidate without
   attaching the reference or triggering Kling.
2. The variant helper previously implied a second reference-conditioned
   “original” run after the first run already produced it. Its contract now
   reuses that first result and plans exactly one additional text-only sexy
   generation.
3. The deterministic Kling compiler previously emitted terms rejected by the
   Kling prompt validator. The compiler now validates its own output against
   the shared contract before returning it.
4. A live read-only provider quote on 2026-07-11 reports 1 credit for the
   planned Soul still and 8 credits for five-second Kling Pro with sound off.
   The active path now reserves those native-credit quotes atomically; no live
   Kling result is present in current runtime evidence.
5. Free static MP4 rendering now runs as a mandatory, idempotent transition in
   the same live front-generation invocation that downloads each QC-passing
   original or sexy Soul still. It no longer waits for a second
   `--accepted-still` command, and an original fallback remains durable if the
   later sexy candidate or optional Kling generation fails.
6. Best-only Kling receipt validation now proves that the selected candidate is
   the unique evidence-backed rank-one result, that every eligible candidate is
   present exactly once, and that ranking itself cannot authorize spending or
   publishing.

## Current Live Evidence Snapshot — 2026-07-12

This table separates current runtime proof from code/test coverage. `PARTIAL`
means the system must not claim the master goal is complete yet.

| Requirement | Status | Current authoritative evidence | Remaining proof |
| --- | --- | --- | --- |
| Locked operating behavior | PROVEN | This specification records the operator's 101 answers and the active runtime implements the locked age, creative, approval, spend, and publishing boundaries | Reopen only when the operator changes a locked decision |
| Release audit and repository hygiene | PROVEN | Creator OS runtime code was promoted to audited commit `70f55c93` before the evidence-only status update. PR #430 fixed detached-checkout branch reporting, all applicable CI jobs passed, and nine merged feature branches plus five clean obsolete worktrees were removed. A fresh checkout of that exact code commit with the live ThreadsDashboard snapshot and production-frontend Playwright artifact produced 39 PASS, 7 WARN, and 0 FAIL; the browser artifact proves the deployed frontend routes with mocked auth/API data, not live authenticated backend behavior | Re-run after the real 24h/72h metric fanout and any separately approved paid proof; open Time Machine/auth/ownership warnings remain warnings rather than hidden failures |
| Free static fallback for an accepted Soul still | PROVEN | Apply-mode front-generation job `job_443a93c3f0a0` reused `asset_a1d5edab7bee` as the same 1080x1920 H.264 file (5.533s, 209,703 bytes) with its audio-intent sidecar and complete lineage; rendered/static/cost/reservation/receipt deltas were all zero | None for the accepted-still transition |
| Persisted static fallback inventory | PROVEN | Two current Stacey static assets (`asset_a1d5edab7bee`, `asset_8e6348fd5fb0`) exist with distinct real Higgsfield provider job IDs, prompt/reference lineage, `paidGeneration=false`, `estimatedCostUsd=0`, and locked/no-audio renders. The published red candidate is now `approved`; the unposted black candidate remains `review_ready` | Continue enforcing the same invariant for every future accepted still |
| Automatic original plus sexy pair materialization | PARTIAL | The active front-generation code and regression suite create a static fallback for every QC-passing downloaded original/sexy candidate before review and preserve an earlier fallback if a later candidate fails | One explicitly approved live paid Soul pair must prove both candidates and both static fallbacks were created by the same invocation; do not spend merely to satisfy this row |
| Best-only Kling boundary | PROVEN | The live apply proof projected 0 credits, kept `publishingAllowed=false`, left `registeredAsset=null`, created no selection receipt, and blocked Kling because no approved multi-candidate rank-one receipt existed | None for fail-closed behavior |
| Kling candidate approval | PARTIAL | Both real static candidates have current safe `approved_candidate` audits. Publication of lineage-matching Trial Reel `3a69a80f-dda1-4a04-95d6-f60271d4e2aa` supplies explicit operator evidence for red candidate `asset_8e6348fd5fb0`; durable decision `approval_67e9b3d03946` records that approval for free ranking only. The black candidate remains `review_ready`, and a dry-run pair ranking fails closed on its missing approval without adding a cost, reservation, or receipt | Operator must explicitly approve or reject black candidate `asset_a1d5edab7bee`; only then may the free pair ranking receipt be created. Paid Kling still requires a separate fresh go |
| Spend and kill-switch guard | PROVEN | Runtime policy is 100 credits/day, 1,000/month, 10/run, 150/cohort, minimum balance 25, and at most 10 Kling generations/day; a read-only balance check returned 465.97 credits. A live subprocess proof with `CREATOR_OS_KILL_SWITCH=1` blocked paid front generation before a provider call while leaving the zero-cost static reuse available; cost/reservation/receipt/asset deltas were zero and publishing remained false | Recheck balance and obtain a fresh native quote immediately before any explicitly approved paid request |
| Paid Kling generation | PENDING | No new paid Kling request was made; current receipt count remains zero | Requires a fresh explicit operator go, a bounded live quote/reservation, one downloaded winner, QC, cost evidence, and retained static fallback |
| Signed review-only draft handoff | PROVEN | Day-2 Trial draft `a13b001d-97d6-49de-9c2b-71103a377b23` and regular draft `4ef9bd38-7a85-4283-be52-7205faa48b8f` were inserted exactly once for `bennett_s33`, with no schedule or QStash publish dispatch | Operator review remains separate from draft creation |
| Notify Publish and post reconciliation | PROVEN | Trial post `3a69a80f-dda1-4a04-95d6-f60271d4e2aa` reconciles exactly once to Instagram media `18094620473086400` and permalink `https://www.instagram.com/reel/DaqdKAqxUW3/`; read-only closed-loop proof passes against `bennett_s33`. ThreadsDashboard PR #313 and production migration `20260712043726` make Mark Posted idempotent, preserve the real Instagram timestamp, cancel stale QStash, and close the matching schedule item. The live batch item is now `completed` while retaining its original QStash receipt; because the operator published early after an account reroute, that receipt proves scheduling rather than notification delivery | Preserve the same invariant for future posts and separately prove scheduled notification delivery on a post that actually waits for its due time |
| Metrics learning loop | PARTIAL | One eligible post and one real 1h history row are reconciled; the current snapshot is 2 views and 1 reach. QStash log receipt `msg_26hZCxZCuWyyTWPmSVBrNB8829kwoVQ4CeGAJUbhkJwkrWdeKLVfRpwTh4HUMV8` targets the exact 24h timestamp `2026-07-12T18:54:35Z`. Because this post predated the deployed 72h scheduler, the missing account and per-post jobs were added explicitly and verified as `msg_26hZCxZCuWyyTWPmSVBrNCtiJFEWKTbGoZSNmBxz9taLm7Pc3dxvcBLU5rNVaTN` and `msg_26hZCxZCuWyyTWPmSVBrNC1RACoiiih7uFWy2iQb6Y1AoxxRVCRWLJQwgWij44x`, both targeting `2026-07-14T18:54:35Z` with two retries | Real 24h and 72h rows must arrive and fan out through Campaign Factory and reference/reel learning before closure; queued receipts are not snapshot evidence |
| Weekly improvement | PROVEN | Launchd job `com.creator-os.weekly-improvement` ran the merged runtime with exit 0 and produced a read-only live report from one measured snapshot. It proposed no underpowered creative changes, separated six recovered failures from one review item, reported zero Kling calls, and marked two legacy provider-call credit amounts as unknown rather than zero | Accumulate at least three measured samples per pattern before accepting a creative recommendation |
| Operations and recovery | PARTIAL | Local backup, ops digest, weekly digest, hourly performance sync, and daily cohort launchd jobs last exited 0. A backup-scope audit found and fixed that runtime-only accepted media was absent from the older canonical-data snapshot. The corrected local mirror now preserves runtime source stills, processed reels, Campaign Factory campaigns/approvals, orchestrator state, acceptance artifacts, and an explicit non-secret recovery-script/launchd allowlist while excluding env/password/key/notification files. The black candidate still and approved static MP4 matched their source SHA-256 hashes after local copy. Encrypted Restic snapshot `c194bbef` was uploaded to the private Supabase recovery bucket; a full repository check reported no errors, and a clean temporary restore recovered 3.142 GiB across 5,528 files/directories, verified 4,746 files, passed integrity checks for all four SQLite databases, and passed every new runtime/config scope assertion. ThreadsDashboard PR #314 changed the Vercel fallback branch glob from `*` to `**`; a real `codex/...` push then created no redundant preview deployment | `tmutil destinationinfo` reports no Time Machine destination and no external disk is attached; the operator must attach/select a destination before Time Machine can be claimed |

No paid credits or publishing authority were granted by the static-fallback
proof. The 24h/72h metric windows and the optional explicitly approved paid
Kling smoke remain independent gates.

## Required Completion Evidence

| Requirement | Authoritative proof |
| --- | --- |
| Reference-conditioned Soul still | Real provider result, captured prompt, local artifact, cost record, and lineage |
| Original/sexy behavior | Exactly two provider charges total, distinct original and text-only sexy lineage, identity/anatomy QC, and selection explanation |
| Automatic static MP4 | One live front-generation invocation creates a registered 1080x1920 H.264 MP4 plus audio intent for every QC-passing downloaded original/sexy still, with no second command; a later candidate failure leaves earlier fallbacks durable |
| Best-only Kling | Ranking/approval evidence precedes a bounded paid request; rejected candidates cannot spend |
| Kling generation | Real downloaded video, provider receipt, cost record, identity/visual QC, and static fallback retained |
| Draft handoff | Signed HMAC request, durable draft record, and proof that no schedule or publish row was created |
| Publishing boundary | ThreadsDashboard approval/native-audio proof and guarded manual publish receipt |
| Learning loop | The published post has eligible 1h, 24h, and 72h snapshots and updates the correct campaign/reference/reel outcomes |
| Operations | Runtime checkout, launchd health, budget/kill switches, notifications, backup check, and operator runbook verified |
| Weekly improvement | Scheduled weekly digest uses real outcomes and proposes bounded evidence-backed experiments |

## Completion Rule

The master goal is complete only when the operator can upload or select library
content and wake up to new high-quality reels that were selected, gated,
drafted, and scheduled across the fleet; ThreadsDashboard either publishes them
through its approved Meta path or sends the required Notify Publish handoff;
paid generation remains inside budget; real metrics update learning; and the
weekly digest recommends improvements. Routine operation must not require code
or terminal commands. Green unit tests, an open pull request, a preview
deployment, or an isolated paid still do not by themselves prove completion.
