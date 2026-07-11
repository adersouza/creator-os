# Creator OS Master Operating Specification

Status: **DRAFT — awaiting operator questionnaire answers**

This document is the implementation authority for the current Creator OS
production-readiness goal. It records only requirements the operator has
already stated. Unanswered product decisions must not be silently converted
into defaults.

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

## Decisions Awaiting Operator Answers

The questionnaire covers ten decision groups:

1. outcome and scope;
2. creative identity and boundaries;
3. reference selection;
4. Soul stills and sexy variants;
5. free static MP4 behavior;
6. Kling eligibility and budgets;
7. ranking and selection;
8. captions, native audio, and drafts;
9. scheduling and publishing;
10. learning, operations, and ownership.

Until those answers are locked, implementation may repair contradictions and
add non-mutating tests, but it must not guess spend ceilings, publishing
authority, posting volume, or sexual-content boundaries.

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

## Completion Rule

The master goal is complete only when the operator-approved specification is
implemented and the evidence table is satisfied end to end. Green unit tests,
an open pull request, a preview deployment, or an isolated paid still do not by
themselves prove completion.
