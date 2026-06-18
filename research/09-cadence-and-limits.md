# Research 09 — Posting Caps & Conservative Cadence (2026)

> Owner-supplied research, **filtered to the legitimate parts**. See the EXCLUDED section — part of the source material was a coordinated-inauthentic-behavior evasion playbook and is deliberately NOT incorporated.

## Official / documented caps
- **Threads:** 250 posts / 1000 replies / 100 deletes / 500 loc-searches per profile / 24h (documented; replies don't count toward posts; carousel = 1). Query `threads_publishing_limit` live.
- **Instagram:** docs conflict (25 → 50 → 100 history; endpoint returns 50; headline says 100). **Query `content_publishing_limit` live; `config.quota_total` is authoritative per account.** Stories/Reels/carousels share the bucket; carousel = 1 post.
- These are technical ceilings, **not** safe cadences.

## Conservative cadence (legit anti-spam — well under the ceiling)
Meta's Spam standard targets posting "at very high frequencies" — **cadence, not automation, is the trigger.** So default well below the cap:
- **~1–2 feed/Reel posts per day per account** (1/day for newer accounts, 1–2/day established). Stories more frequent.
- **Space consecutive posts ~2–4h apart**, vary by ±15–30min (mimic human, avoid burst patterns).
- Vary content type; **don't recycle identical captions/hashtags** across posts (duplicate-detection signal). ≤~10 hashtags.
- Randomize exact post times within a window rather than a fixed clock minute.
- If account warnings appear or 4/17/32/368 errors rise → reduce cadence immediately.

This confirms `deriveCadence`'s conservative tiers (warming/normal/high-perf, 1–2/day, multi-hour gaps) are the correct posture. The autoposter should hard-cap default cadence regardless of the API ceiling, and never fan **identical** content across accounts in a tight window (reads as inauthentic coordination — which the pipeline's genuine-per-account-distinctness work exists to prevent).

## EXCLUDED — not incorporated into Creator OS (and why)
The source research also described tactics for running a **network of operator-controlled accounts while evading Meta's account-linkage detection**. These are **coordinated inauthentic behavior** under Meta's policy regardless of cadence, and we do not build or document them:
- Antidetect browsers / per-account device-fingerprint spoofing (canvas/WebGL/fonts).
- Dedicated proxies / per-account IP isolation to defeat IP/device clustering.
- Separate SIMs/emails/payment methods to avoid identity linkage.
- "Desync" multi-account activity timing "so it's not obvious one operator runs all accounts."
- New-account "warming" schedules engineered to slip past new-account spam heuristics.

**Why excluded:** these exist specifically to deceive Meta's integrity systems about who controls the accounts — the definition of CIB. The whole-session stance holds: **the system detects and respects platform rules and produces genuinely distinct content for legitimately-separate accounts; it does not coordinate-and-hide.** juno33 is a disclosed scheduler publishing creators' own (or disclosed multi-client) accounts via the official APIs with per-account OAuth consent. If the real situation is one operator running many accounts to look like many people, no tooling here will help evade detection — the durable answer is genuinely separate, authorized accounts with genuinely distinct content.

## What IS legit to build from this
1. Dynamic quota gating (query the limit endpoints before publish) — see research/07.
2. Conservative default cadence caps + multi-hour spacing + time jitter (deriveCadence posture).
3. Don't-fan-identical-content guard (already the goal of per-account distinctness).
4. Reduce-cadence-on-warning feedback (ties to AP3 account-health auto-backoff, research/08).
