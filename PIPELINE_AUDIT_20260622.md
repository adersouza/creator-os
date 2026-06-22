# Creator OS Pipeline Audit — 2026-06-22

Full-pipeline audit: what each stage is *supposed* to do vs. implemented / wired & used / done well / fit for autonomous IG→OnlyFans marketing. Sourced from a 5-subsystem parallel read across creator-os + ThreadsDashboard, with the 3 cross-subsystem ("seam") claims independently verified.

## Verdict (lead)

The engineering is real and mostly works. The **business aim does not exist in code**: there is **no built IG→OnlyFans funnel anywhere** — no link injection, no DM automation, no OF CTA in any publish path; OF terms are even filtered out in default niche mode. The system, as running, is a **Threads text-engagement farm** plus a **separate operator-gated media-draft pipeline**. Both are well-built; neither converts to OnlyFans, and neither autonomously posts the elaborate Reel Factory media.

**The single change that unlocks autonomous OF revenue is the funnel** (ban-aware CTA/link/DM path + niche-mode carve-out), not any of the "dead code" cleanups below.

## Two parallel content paths into ThreadsDashboard (this is the key structure)

1. **Autonomous text engine (live).** TD's autoposter generates its OWN text (genV2 winner-lean) → filter/judge/dedup → schedule → publish to **Threads only**. Self-contained in TD. Does **not** use any creator-os media. This is the thing that posts "confession:/hot take:" hooks.
2. **Operator-gated media pipeline.** Reference → Reel → Campaign → ContentForge produces `campaign_draft_payload.v1`, ingested by TD as **`draft` status** → published only via operator/`scheduled-post-publish`. By design (not broken), but **not autonomous**.

The Reel Factory reels dead-end further still: Campaign Factory imports them as `source_assets` (status `imported`) but builds its TD drafts from its *own* `rendered_assets` — so the burned-caption reels the whole guard saga protects are **enforced-then-discarded**, never posted without a regeneration round-trip.

## Stage map — supposed-to-do vs. status

| Subsystem / stage | Supposed to do | Implemented | Wired & used | Does it well |
|---|---|---|---|---|
| **Reference Factory** — reference bank | format/hook/caption clusters → CF | yes | YES (CF `reference.py`) | heuristic keyword clustering, not learning |
| Reference Factory — audio catalog | native-audio-first catalog → CF | yes | YES (CF `audio_recommendations.py`) | best module; trend = usage-count buckets |
| Reference Factory — **measured-outcome loop** | reward back from results → rank | yes (code) | **OPEN** — nothing writes `campaign_prompt_outcomes.json` | dormant; falls back to public volume |
| Reference Factory — winner-DNA rich signals | account/persona/reward signals | yes | **dropped at consumer** (CF ignores them) | wasted computation |
| Reference Factory — pattern_cards / playbooks | machine inputs | yes | **DEAD** (no consumer) | scaffolding |
| **Reel Factory** — Higgsfield/Soul still | direct reference-image still | yes | YES (active path) | solid; **3:4 default vs 9:16 spec drift** |
| Reel Factory — motion (Kling) | deterministic motion | prompt only | **manual seam** — operator runs Kling by hand | not automated |
| Reel Factory — zero-cost motion_edit | cheap ffmpeg motion | yes | **ORPHANED** (tests only) | dead |
| Reel Factory — caption render + bank | Instagram Sans, bank text | yes | YES | good; per-creator weighted, ban-safe |
| Reel Factory — focal-safe placement | scored safe lane | yes | YES | **fragile** — cv2/MediaPipe optional → silent top-lane fallback |
| Reel Factory — readiness sidecars | lineage/audio_intent/QC | yes | YES | **structural only** — checks presence, not quality |
| Reel Factory — review_batch_guard | fail-closed gate | yes | YES (CF intake re-runs it, #274) | strict & real; **but its inputs are never produced in-repo** |
| **Campaign Factory** — plan/recommend/readiness | the "brain" | yes | YES | real gating, recs partly operator-seeded |
| Campaign Factory — variation/assign | fan-out safety, account assign | yes | fan-out safety **opt-in/bypassed**; assign = round-robin | not performance-driven |
| Campaign Factory — export to TD | `campaign_draft_payload.v1` | yes | YES (HTTP ingest, status forced `draft`) | clean contract boundary |
| Campaign Factory — learning | performance_sync → better recs | yes (code) | **operator-driven, ~open** | same dormancy as RF loop |
| **ContentForge** — PDQ/SSCD distinctness | block dup-detectable variants | yes (real detectors) | **OFF by default** (`dry_run=True`); SSCD weights absent | strong code, unreached in default op |
| ContentForge — metadata rewrite | device-capture spoof | partial | advisory/warn only | shallow; repo's own audit calls transforms "cosmetic" |
| ContentForge — OCR safe-zone / readability / watchability | quality floor | yes | blocks under campaign profile *if gate runs* | real with OCR; **17 tests skip silently without Tesseract** |
| ContentForge — `campaign_factory_v1` audit | the artifact the guard checks | — | **NOT PRODUCED** by anything | this is why batches block on `missing_contentforge_audit` |
| **TD autoposter** — genV2 + promptBuilder | winner-lean text | yes | YES (live) | real, not cosmetic |
| TD autoposter — filter/prefilter/judge/embed | quality + dedup + safety | yes | YES | **llmJudge + embeddingGate fail OPEN**; judge degrades silently |
| TD autoposter — accountPlanner/warmup/health | ban-safe ramp + slotting | yes | YES | **strongest area** — genuinely autonomy-fit |
| TD autoposter — scheduleAndInsert | slot + approval gate | yes | YES | **starvation chokepoint** (needs_review one-way drain, slot exhaustion) |
| TD autoposter — publisher | post to platform | partial | **Threads only** — `publishToInstagram` is dead code | IG surface absent |
| TD autoposter — performance→winner→gen **learning loop** | self-improve | yes | **CLOSED & real** (daily cron) | only honored when genV2 on |
| TD autoposter — autoReply | engagement | yes | YES | engagement only, **no DM/OF funnel** |

## Three structural truths (verified)

1. **No OnlyFans funnel exists in code.** No link injection, no DM automation, no OF CTA on any publish path. OF terms (`onlyfans`/`fansly`) are in `THIRST_ALLOW_TERMS` — filtered in **default** niche mode, allowed in **thirst** mode (e.g. a "GFE" group). So it's not "banned by mistake"; it's "never built, and gated off where niche isn't thirst." **This is the #1 revenue blocker.**
2. **Instagram is not published.** The autoposter posts Threads text only; `publishToInstagram` is unreachable. "IG→OF" is aspirational — there is no live IG surface, which is also where an OF funnel would naturally live.
3. **The autonomous engine and the media pipeline don't meet.** Autonomous posting = TD text. The Reference→Reel→Campaign→ContentForge media chain produces operator-review drafts and dead-ends reels as source imports. The sophisticated media pipeline is **not** what autonomously posts.

## Ranked fixes (by revenue impact, not tidiness)

1. **Build the funnel.** Ban-aware OF CTA path: niche-mode carve-out for thirst groups, a vetted link/bio/DM-reply strategy, and (if IG is the goal) actually wire `publishToInstagram`. Nothing else moves revenue without this.
2. **Unstarve the queue.** Auto-graduate `needs_review` (batch re-eval), fix `viralScore` defaulting to 0, stop silent slot-exhaustion discards. (Partly bridged manually this week; needs a code fix.) See `td-autoposter-label-leak-2026-06` memory.
3. **Decide the media pipeline's purpose.** Either wire Reel Factory reels through to posted drafts (register as `rendered_assets`, produce the ContentForge `campaign_factory_v1` audit so the guard can pass), or stop investing in a chain that dead-ends. Today the guard saga protects an output nothing posts.
4. **Close the learning loops.** Write `campaign_prompt_outcomes.json` back to Reference Factory; honor it. Otherwise "winner-lean" is competitor imitation, not self-improvement.
5. **Turn on the safety that's off.** ContentForge distinctness gate runs only in `apply` mode with SSCD weights present; the autoposter's judge/embed gates fail open. Provision SSCD, flip the gate on for real fan-out, make the fail-open gates alert.
6. **Fix the silent degradations.** Placement falls back to top-lane when cv2/MediaPipe missing; 17 safe-zone tests skip without Tesseract; expired tokens (4/6 Stacey) kill accounts with no auto-recovery. Each fails quietly — add signal.

## Net

Six subsystems, mostly real engineering, one genuinely excellent area (ban-safe warmup/health) and one genuinely closed loop (TD performance learning). But the product is pointed at Threads engagement volume, not OnlyFans conversion; the conversion mechanism is **unbuilt**; and the elaborate media pipeline is decoupled from the only autonomous posting that happens. Fix the funnel first. Everything else is optimization of a machine that currently cannot convert.
