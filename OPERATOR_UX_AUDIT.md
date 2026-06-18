# Operator UX Audit — ThreadsDashboard (Juno33)

**Audience:** Codex + owner. **Repo:** ThreadsDashboard (the product the human operates). **Question:** is the *smart* backend **legible** to the human running it — can an operator see what the system knows, why an account is flagged, and what to do next?

**Verdict (from a full UI survey of `src/pages/` + `src/components/`):**
- **UI breadth: strong.** 14 operator surfaces exist (Dashboard, Accounts, Calendar, Composer, Content, Analytics, Autopilot, **Reliability**, Reports, Inbox, Listening, Ideas, Links, Approval Queue). This is not a missing-screens problem.
- **Operational legibility: ~7/10.** Health states are color-coded + filterable; empty states are genuinely helpful; the `Reliability` page already aggregates SLOs, token health, Meta-API quota, webhook/DLQ health.
- **Smart-signal legibility: ~4/10.** The backend computes ranking, winner-DNA, variation/distinctness, reach anomalies, recommendations — **the UI mostly doesn't surface the "why" or the "what next."** This is the gap to close for an *intuitive* ≥9 system.

The system is **smart but not yet self-explaining.** An expert operator can drive it; a new one can't tell *why* an account is flagged or *what action* the smart layer recommends.

---

## What IS already legible (don't rebuild)

| Signal | Where | Quality |
|--------|-------|---------|
| Account health enum (good/idle/warn/critical/offline) | Accounts hero + rows, Composer pills, Dashboard OpsHealthTile | Full |
| Health signals (capability_error, token_expiring, rate_limit, shadowban_risk, engagement_spike, reach_anomaly) | `useAccountHealthSignals`, Composer `ChannelHealthPills`, Accounts detail | Full granularity, sparse layout |
| Token expiry / reauth | `Reliability` Token SLO, Accounts detail | Full |
| Publishing SLO (on-time %, success %, P95 drift, backlog) | `Reliability` hero | Full |
| Meta-API quota usage (%, Retry-After, per-endpoint) | `Reliability` Meta-API card | Good |
| Ghost-post queue (>24h, <10 views, worst accounts, WoW Δ) | `Analytics-v2` GhostPostQueueTile | Strong — this is the model to copy |
| Conversation winner (reply depth, velocity, quote/reply) | Dashboard ConversationWinnerTile | Strong |
| Account DNA archetype + confidence + topics | Autopilot → Agent | Present but raw |

The **Ghost-Post-Queue tile** is the gold standard already in the repo: a signal + worst-affected leaderboard + WoW delta + a one-line "what this means / what to confirm before acting." Every gap below should be built to that bar.

---

## Findings — where the smart backend is NOT legible (the audit)

Severity: **High** = a smart signal that drives money/safety is invisible or un-actionable. **Med** = present but raw/no-next-step. **Low** = polish.

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| UX-1 | **High** | **Winner-DNA recommendation is invisible.** Backend computes archetype-matching + confidence; UI shows only raw archetype/topics/phrases. No "account X should follow archetype Y because winner Z matches it and outperformed by N%." | Autopilot → Agent (DnaProfileRow) shows traits, not the *recommendation* | Add a recommendation card: matched archetype + the winning exemplar + expected-lift rationale + a "apply to next batch" action. Mirror GhostPostQueueTile structure. |
| UX-2 | **High** | **Variation / distinctness not actionable.** `account_dna.uniqueness_score` exists but only as a fleet **average** in DNA metrics. No per-account leaderboard, no "is 62% good or risky?" guidance. This is the anti-shadowban signal — it should be front-and-center. | DNA metrics aggregate only | Add a distinctness leaderboard (most/least distinct accounts) + a threshold band ("below X = collision risk; raise variation") tied to the shipped PDQ/SSCD Track-S gate. |
| UX-3 | **High** | **Dead-letter queue has no inspection surface.** `Reliability` shows a DLQ **count**; the button routes to `/admin/dead-letters` which may not exist in main routes. An operator can see "12 dead-lettered" but can't see *which* or retry. | Reliability dlqCount; route uncertain | Add a DLQ inspection view: per-message status, error class (from the shipped `metaErrors` taxonomy), age, and a retry/replay action. |
| UX-4 | **Med** | **Reach-anomaly has no investigation tile.** It exists as a health-pill `signal_type` but, unlike ghost-posts, has no dedicated card correlating the anomaly with engagement/ghost-post/webhook state. | account_health_signals only | Add a reach-anomaly tile (flagged accounts + correlation vs engagement + the non-follower-reach collapse the AP3 auto-backoff already computes). Surfaces *why* AP3 paused an account. |
| UX-5 | **Med** | **No fleet-level "what's the top blocker?" view.** Health signals are per-account; there's no aggregate "most common blocker across the fleet right now" so the operator can't triage by theme. | per-account only | Add a fleet blocker rollup (group signals by type, count, trend). |
| UX-6 | **Med** | **Publish failures shown as aggregate, no root-cause taxonomy.** `Reliability` shows `failedTotal` + a flat issue list — but the shipped `metaErrors` taxonomy (transient/window_cap/permanent/dead_letter) isn't used to *group* failures. | Reliability issue list | Group failures by taxonomy class with counts; link each class to its recommended action. Reuses backend that already exists. |
| UX-7 | **Med** | **No "why + what next" on a flagged account.** Account shows state + signals but not the causal story or the recommended operator action. New operators can't self-serve. | Accounts detail slide-over | Add a one-line cause + next-action per flagged account (e.g. "non-follower reach collapsed 3 days → AP3 paused; auto-resumes on recovery, or reconnect token"). |
| UX-8 | **Low** | **No historical trend on Reliability SLOs.** All point-in-time; can't tell if webhook/token/quota health is degrading week-over-week. | Reliability cards | Add 7-day sparkline/line per SLO with threshold-cross markers. |
| UX-9 | **Low** | **Smart concepts unexplained.** DNA profiles, conversation-winner ranking, distinctness have no tooltips/help — a new operator can't interpret them. | sparse tooltips | Add inline "what this is / how it's ranked" help to the smart tiles (the GhostPostQueue footer is the template). |

---

## Suggested sequence for Codex (ThreadsDashboard repo, feature branches off `main`)

The high-value theme: **surface the signals the backend already computes; reuse the GhostPostQueueTile pattern; every tile answers "what / why / what next."** No new backend intelligence — this is making the existing intelligence *legible*.

1. **UX-3 DLQ inspection** + **UX-6 failure taxonomy grouping** — operational safety first; reuses shipped `metaErrors` + DLQ. Confirm/whitelist the `/admin/dead-letters` route.
2. **UX-2 distinctness leaderboard** + threshold band — surfaces the anti-shadowban signal (ties to Track-S, already shipped). Highest brand/safety value.
3. **UX-1 winner-DNA recommendation card** — turns the DNA backend into an operator action.
4. **UX-4 reach-anomaly tile** + **UX-7 account "why + next"** — makes AP3 auto-backoff explainable.
5. **UX-5 fleet blocker rollup**, **UX-8 SLO trends**, **UX-9 tooltips** — triage + polish.

**Constraints:**
- ThreadsDashboard repo; feature branch → PR; never push `main`. One logical change per PR; each adds a test.
- **Read-only on the smart layer** — surface existing signals, don't change ranking/health/distinctness logic.
- No new posting behavior; no evasion. The distinctness leaderboard is detect-and-respect (shows collision risk), consistent with Track S.
- Match the existing component conventions (StatusPill/HealthDot, NovaScreen, the analytics-v2 evidence-tile pattern).

---

## How this moves the score

Operator UX isn't a numbered component in `creator_os_map.html`, but it's the difference between "a smart system" and "a smart system a human can *run well*." Closing UX-1..7 takes smart-signal legibility from ~4/10 to ~8 and is a precondition for the product (not just the pipeline) to feel like a ≥9. It's also the lowest-risk track — pure surfacing, no algorithm changes.
