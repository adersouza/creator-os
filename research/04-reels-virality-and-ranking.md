# Research 04 — Reels Virality & Ranking Factors (2026)

> Owner-supplied research (two deliverables merged). Feeds INTELLIGENCE_AUDIT Track Q — replaces `heuristic_v1` creative scoring with a buildable rubric.

## What Instagram officially confirms (Mosseri / Meta transparency cards)

Top Reels predictions: **how likely you are to (1) reshare, (2) watch all the way through, (3) like, (4) visit the audio page.** Completion is defined relative: "watch more of a reel than **95% of users who watched reels of the same length**" — so short and long Reels are NOT on the same completion scale. Watch time uses **both** relative % AND absolute seconds (longer videos not penalized). Top-3 creator metrics (verbatim Mosseri): **watch time, likes, sends** — likes slightly more for *connected* (follower) reach, **sends slightly more for *unconnected* (non-follower) reach.** Sends = strongest distribution-expander to new audiences.

"Less visible" eligibility triggers (official): **low-resolution, watermarked, muted, bordered, majority-text, or already-posted-on-Instagram.**

## Ranking of factors by real reach impact

1. **3-sec retention / hook hold-rate** — the gate everything depends on.
2. **Average watch time** — confirmed #1 metric; coupled with #1.
3. **Completion rate** — confirmed; length-adjusted (dominant for short Reels).
4. **First frame / hook** — the *craft lever* that produces #1–3 (not itself a measured metric).
5. **Audio / trending** — named signal but weak/short-shelf-life; relevance + originality matter more; some audio required (muted = deprioritized).
6. **Caption** — topic classification / SEO / dwell; not a primary reach lever. 3–5 relevant hashtags (not 30).
7. **Posting time** — weakest; affects early-velocity only. ("Cherry, not the cake.")

Over-performer signal stack (priority): **avg watch time → 3-sec hold → sends/reach → rewatches/loops → length-adjusted completion → likes/reach → saves/reach → follows/reach.**

## BUILDABLE: 100-point Reel Prediction Score (pre-post, file-level)

| Component | Pts |
|-----------|----:|
| Hook / first frame (thumb-stop: face/result/conflict/surprise/motion) | 20 |
| First-3s clarity + curiosity gap | 20 |
| Retention pacing (cut/change every 2–3s, no dead air, no slow intro) | 20 |
| Shareability ("send this to ___" trigger: relatable/useful/funny/surprising) | 20 |
| Originality/quality (no watermark, ≥1080×1920 9:16, not blurry, not a repost) | 10 |
| Caption SEO + audio fit (single clear topic, audio present & fitting) | 10 |

**Gate: <70 → don't post · 80+ → publishable · 90+ → best slot + cross-account test.**

## 12-point pre-post checklist (deterministic + model-backed)
1. Hook in first 1–2s (highest leverage). 2. On-screen text: short, high-contrast, safe-zone, not UI-covered. 3. Cut every 2–3s. 4. Length matched to payoff (discovery 7–30s; story 30–90s; ≤3min for non-follower reach). 5. Loopability (last frame → first). 6. "Worth sending" moment. 7. 9:16 1080×1920, no letterbox, not low-res. 8. No competitor watermark, not verbatim repost. 9. Audio present + fitting. 10. Single clear topic/niche. 11. No engagement-bait phrasing ("like if…"). 12. Raw/authentic over over-polished/obviously-AI (Mosseri Dec-2025 memo: "real human content" through 2026).

## How to compute the score (not heuristics)
- **Higgsfield `video_analysis` + `virality_predictor`** → watch/share/retention prediction signals (currently wired into nothing).
- **VLM judge** on first-3s frames + OCR'd hook text, scored vs the *learned winning hook archetypes* from `reference_factory` pattern cards.
- **Deterministic eligibility pre-checks** map to Meta's confirmed "less visible" triggers: watermark detect, resolution/aspect, muted, majority-text (OCR coverage %), letterbox, already-posted (PDQ self-match).

## 2025–26 changes
Recommended Reel length → 3 min (Jan 2025); watch-time clarified (relative% + abs seconds); sends elevated; originality push / aggregator demotion; "Your Algorithm" topic controls (Dec 2025); Trial Reels (test on non-followers first); unified Views metric; "raw real human content" priority for 2026.

## Caveats
Exact weights/multipliers ("sends 3–5× likes", "60% hold", "10+ reposts/30d") are creator/analytics inference — Mosseri only said sends are "slightly more important." Confirmed = *which* signals; not the weights. Surfaces (Feed/Reels/Explore/Stories) rank differently.
