# Research 06 — Meta API Posting Limits & Automation Policy (2026)

> Owner-supplied research. The **legit, official-API** version (not evasion). Feeds AUTOPOSTER_HARDENING_PLAN — publish-path hardening + cadence guardrails. juno33 = disclosed multi-client scheduler on the official Graph/Threads APIs.

## Publishing caps — query dynamically, never hard-code

| Platform | Cap | Endpoint (query at runtime) |
|----------|-----|------------------------------|
| **Instagram** | **100/24h** headline, but docs conflict — carousel subsection + the live endpoint still return **50**. Carousels = 1 post. | `GET /<IG_ID>/content_publishing_limit?fields=quota_usage,config` → enforce returned `quota_total`/`quota_usage` |
| **Threads** | **250 posts / 1000 replies / 100 deletes / 500 loc-searches** per profile/24h (separate buckets) | `GET /{threads-user-id}/threads_publishing_limit?fields=quota_usage,config,reply_quota_usage,reply_config,...` |

- Caps are **per account/profile** → each client gets its own budget. Containers expire if not published within 24h.
- **No dated changelog for the 25→50→100 progression** — Meta changes these silently. So: query the endpoint before every publish, gate on what it returns, re-verify each quarter / API-version bump.
- IG media: JPEG only, no text-only posts (every IG post needs image/video), REELS replacing VIDEO. Threads: TEXT/IMAGE/VIDEO/CAROUSEL, text-only OK, 500-char (+10k text-attachment), video ≤5min, carousel ≤20.

## Rate limits (Business Use Case model — IG + Threads are BUC)

- **BUC: calls/24h = 4,800 × impressions** (impressions = times account content hit a screen in 24h; floor ~10 → ~48k/day). Plus CPU/time ceilings. Counted per app+user pair.
- **Platform (app/user tokens): 200 × users calls/hour** (app-level, shared pool).
- **BUC takes precedence** when both apply.
- **Read headers:** `X-App-Usage` + `X-Business-Use-Case-Usage` report `call_count`/`total_cputime`/`total_time` as % + `estimated_time_to_regain_access`. Throttle at 100%.
- Vendor-reported (NOT Meta-confirmed): per-account Graph ceiling cut 5,000→**200/hr** in 2025. Treat as reported.
- **Retry/backoff:** exponential + jitter on **429 / error codes 4, 17, 32, 613**. Back off locally at **~75–80%** utilization before Meta throttles.

## Multi-tenant engineering (compliant scheduler)
- Track per-tenant + per-app usage locally; throttle yourself before Meta does.
- **Isolate clients** — one heavy account must not exhaust the shared app pool (ties to AP1-2 cron fairness).
- Prefer **system-user / long-lived tokens** (60-day IG/Threads; Threads public-profile grants 90-day) with automated refresh.
- Queue each scheduled post against that account's live `content_publishing_limit`/`threads_publishing_limit`.

## Policy — what's permitted vs prohibited
**Permitted:** disclosed multi-client scheduling via official APIs (`instagram_content_publish` / `threads_content_publish`), with Business Verification, App Review, Tech Provider status, and **per-account OAuth consent** (Developer Policies §1.7 — must have the client's authorization for each account). Account Integrity standard explicitly carves out "authorized API routes."
**Prohibited:** circumventing limits/enforcement (Platform Terms §3.a.vi, §7.e.i.3, §11.e; consumer ToS §7); inauthentic/deceptive/spam behavior (Dev Policies §1.4); buying/exchanging engagement (§2.7); posting "at very high frequencies" (Spam standard — **cadence, not automation, is the trigger**); coordinated inauthentic behavior = network of inauthentic assets controlled by one operator to deceive/evade (content-agnostic).

**The line:** a disclosed scheduler posting authorized content for real, separately-owned accounts is categorically fine. The risk is (a) "very high frequency" posting and (b) **identical content blasted across many accounts simultaneously**, which reads as inauthentic coordination — exactly what the pipeline's genuine-per-account-distinctness work exists to avoid.

## Cadence guardrail (actionable)
Cap default per-account cadence **well under** the technical ceiling — a handful of posts/day per account, not 100/250. Don't fan identical content across accounts in a tight window. If you see account warnings or elevated 4/17/32 errors → reduce cadence immediately. (Confirms `deriveCadence`'s conservative tiers are the right posture.)

## Established-scheduler reference points
Meta Business Suite native: 25/day, 75 days ahead. Buffer doc: 25. Later/Emplifi: 50. Vendor figures lag Meta — corroborate the cap exists, not the current number. Meta Business Partner badge ≠ higher limits, ≠ enforcement exemption.

## Caveats
IG 100-vs-50 unresolved (programmatic endpoint is authoritative per account, can return 50). 25→50→100 undated. 5000→200/hr vendor-reported. Newer/low-trust accounts throttled below documented maxes. Policy clause numbers = Feb 3 2026 versions, re-verify.
