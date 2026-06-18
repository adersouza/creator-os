# Research 08 — Throttle / Recommendation-Ineligibility Detection via API (2026)

> Owner-supplied research (two deliverables consolidated). 100% legitimate — monitoring your OWN authorized accounts' health. Feeds a new AUTOPOSTER track (AP3): account-health → auto-backoff.

## The core gap
The authoritative signal — **Account Status → Recommendation eligibility** — has **NO Graph API field**. In-app only (Settings → Account → Account Status). So any automated detector is **inferential**, built on Insights proxies + periodic manual Account-Status confirmation. The IG User node exposes only id/username/followers_count/media_count/… — no eligibility/distribution flag.

## PRIMARY signal — non-follower reach ratio collapse (API-accessible, account-level)
`GET /{ig-user-id}/insights?metric=reach&breakdown=follow_type&metric_type=total_value` → reach split `FOLLOWER / NON_FOLLOWER / UNKNOWN`. (Also `metric=views&breakdown=follower_type` — note Meta's real naming inconsistency: `follow_type` for reach vs `follower_type` for views.)
- Non-follower reach = discovery/recommendation surfaces (Explore/Reels-recs/hashtag/search). When recommendation eligibility is revoked, **this share collapses while follower reach persists.**
- Healthy baseline (Socialinsider 2025, not Meta): ~55% of Reel views from non-followers; Reels reach rate ~30.8%. Suppressed: share collapses toward **<10%** (community heuristic).
- **Caveat:** account-level reach-by-follow_type is daily/aggregate; the per-POST follower/non-follower split is **in-app only** (media-insights API has no follow_type breakdown).

## Supporting signals (all API)
- `reach` (account+media; `time_series`+`total_value`; breakdowns `media_product_type`, account-level `follow_type`), `views` (replaced `impressions`, deprecated Apr 21 2025; ~25% higher, not comparable), `accounts_engaged`, `total_interactions`, `follows_and_unfollows` (added 2026-01-23), `reels_skip_rate` (added 2026-04-15, = 3s-skip = hook quality), `ig_reels_avg_watch_time`.
- `breakdown=media_product_type` (FEED/REEL/STORY/AD) shows reach by **format**, not by Explore-vs-hashtag (no API metric reports "reach from Explore").
- NOT API-testable: search/Explore/hashtag visibility from a non-follower view. Automating logged-out/scraping checks = **ToS risk** (keep manual). The "search your own hashtag" test is less reliable in 2026.

## Threads (thin)
`GET /{threads-media-id}/insights?metric=views,likes,replies,reposts,quotes,shares` (lifetime); `GET /{uid}/threads_insights?metric=views,likes,replies,reposts,quotes,clicks,followers_count,follower_demographics`. **No follower/non-follower breakdown, no eligibility field.** Threads periodically rebalances toward followed accounts platform-wide (mimics throttling). Best proxy: per-post views vs rolling baseline; uniform multi-post collapse = warning, confirm in-app.

## Detection logic (multi-signal, multi-day — avoid false positives)
- **Baseline (per account, 30+ days):** rolling daily total reach, non-follower ratio = `NON_FOLLOWER/(FOLLOWER+NON_FOLLOWER)`, per-post reach, reach by media_product_type. Use **median/MAD**, not mean/std (anomalies inflate std not median). Poll daily (respect ~200 calls/hr/account; up to 48h data lag; missing data returns empty set, not 0).
- **"Throttled" trigger** — fire when **≥2 hold for ≥3 consecutive days / 3 same-format posts:** (a) non-follower ratio ≥50% below baseline or <10% absolute; (b) total-reach z-score < −2.5 (tune ~3.0, or 3.5 for MAD); (c) per-post reach down 40–90% vs baseline uniformly. Multi-signal AND, never single weak post.
- **On trigger:** PAUSE posting + alert; prompt human to check in-app Account Status (no API substitute); optional MANUAL logged-out hashtag check.
- **"Recovered":** non-follower ratio AND total-reach z-score back in baseline bands for sustained 5–7 days (community recovery order: stories → hashtag → Explore over ~10–14 days). Don't resume on one good day.
- **Fleet false-alarm suppressor:** per-account baselines, but monitor cross-account correlation — a simultaneous fleet-wide drop = IG algorithm change / platform-wide decay (~12% YoY reach decline), not per-account throttling. Suppress alert when correlated.

## All thresholds are heuristic
Endpoint/metric/breakdown names + deprecation dates = official Meta. Every NUMBER (50% drop, <10%, 40–90%, z −2.5/−3.0, MAD 3.5, 5–7d/10–14d recovery, 55%/30.8%/3.5% benchmarks) = community/Socialinsider, NOT Meta-published. Recalibrate against observed week-one false-positive rate.

## Compliance
Uses only official Graph API + Insights on the operator's own authorized accounts → compliant. No HTML scraping, no logged-out automation. Tokens belong to the monitored account; store encrypted; minimal retention (aggregate metrics, no PII). Frame alerts as "likely restriction, needs manual review," never absolute proof.

## Maps to AP3 (new track)
Account-health monitor → when an account trips the multi-signal throttle trigger, the autoposter **auto-pauses that account + alerts**, then auto-resumes on sustained recovery. Closes the loop: posting behavior responds to measured account health, not blind scheduling into a suppressed account.
