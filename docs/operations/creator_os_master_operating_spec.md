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
- Automatic publishing stays disabled.
- Native audio is selected and verified in ThreadsDashboard, not burned into
  Creator OS MP4s.
- A ContentForge blocking code rejects the candidate.
- No readiness claim may substitute tests or fixtures for a real approved post
  completing the performance loop.

## Confirmed Implementation Gaps

1. Reel Factory documents conflicting policies for captured-prompt sexy
   variants: the helper implements them, while current production-flow guidance
   disables them.
2. The variant helper previously implied a second reference-conditioned
   “original” run after the first run already produced it. Its contract now
   reuses that first result and plans exactly one additional text-only sexy
   generation.
3. The deterministic Kling compiler previously emitted terms rejected by the
   Kling prompt validator. The compiler now validates its own output against
   the shared contract before returning it.
4. A current provider quote accepts the planned five-second Kling request, but
   no live Kling result is present in current runtime evidence.
5. Free static MP4 rendering now runs as a mandatory, idempotent transition in
   the active accepted-still front path and remains durable if optional Kling
   fails.

## Required Completion Evidence

| Requirement | Authoritative proof |
| --- | --- |
| Reference-conditioned Soul still | Real provider result, captured prompt, local artifact, cost record, and lineage |
| Original/sexy behavior | Exactly two provider charges total, distinct original and text-only sexy lineage, identity/anatomy QC, and selection explanation |
| Automatic static MP4 | Accepted still transition creates valid 1080x1920 H.264 MP4 with audio intent and no manual command |
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
