# Funnel-V1 + Attribution-Schema Scope — Track A (for Codex)

**Goal:** make the smart-link → conversion chain attribute at **arm grain**, so it can feed both the bandit (TD) and winner-DNA/recommendation learning (creator-os) from **one** normalized feed. This is the "money move": we already create content; we don't yet measure *which arm made money*.

**Scope discipline:** this is plumbing, not a new funnel. The HMAC postback, click recording, dedup, and the `funnel_intent.v1` intent metadata already exist. Track A adds **arm tagging at click time** + **one export view**. Keep it boring.

---

## 0. Current chain (verified, file:line)

- **Click handler** `api/go/[code].ts:553` inserts `smart_link_clicks` with `source_platform, device_type, country, referrer, utm_source/medium/campaign/content, event_name, fingerprint, user_agent_hash, ip_hash`. `utm_content` is already overloaded as a device/browser granularity field (`[code].ts:160-163`).
- **Conversion postback** `api/go/convert.ts:80-143`: HMAC-SHA256 over `code+order_id+value` (`:108-112`), idempotent on unique `(smart_link_id, order_id)`, links to **most-recent click within 30 days** (`:118-126`) → `smart_link_conversions(click_id, order_id, conversion_value, currency, source, ...)`.
- **Smart link** `smart_links` table ties to a post via `smart_links.post_id` (FK, nullable). Created via `api/_lib/handlers/smart-links/create.ts:104-116`. `metadata` JSONB exists (appearance/pixels) — **no** arm/campaign/account fields today.
- **Consumption** `analytics-sub/autoposter-performance-attribution.ts:302-358` aggregates clicks (count) + conversions (sum value) **grouped by `smart_link_id`, joined to post via `smart_links.post_id`**, surfaced into `performanceFirst.ts:461-463` as `smart_link_clicks/conversions/revenue` per post.
- **Arm components already first-class** on `autoposter_post_performance_facts`: `account_id, content_archetype, visual_style, hook_type, topic_label, format_type, surface (posts.content_surface)` + the three smart-link metrics. **What's missing is a stable `arm_id`** and **click-level arm capture**.
- **Funnel intent already stubbed** `scheduleAndInsert.ts:83-121` (`funnel_intent.v1`): `attribution.measurementPath:"smart_link_redirect"`, `smartLinkId:null`, `redirectCode:null`, `utm{source,medium,campaign}`, `operatorActionRequired:"attach_or_verify_profile_smart_link"`. **This is the hook point** — when a link is attached, stamp arm params here.

**Current minting:** the autoposter mints **no** smart link today; it records `funnel_intent.v1` with null `smartLinkId`/`redirectCode` and defers to an operator to attach one. So link generation is greenfield — define the param convention now; there is no legacy reuse to migrate.

---

## 1. The arm

```
arm_id = stable_hash(account_id, content_archetype, visual_style, surface, time_bucket)
```

- All components already exist on `autoposter_post_performance_facts` + `posts.content_surface`.
- `time_bucket` = coarse slot (e.g. day-part), not timestamp — keep arm count bounded.
- **Future dims (reserve, don't build):** `cta_style` (`voice_profile.cta_style`), `link_variant`. The arm_id hash input is versioned so adding a dim is a new arm-space, not a silent reassignment.
- A **post is one arm draw.** Stamp its `arm_id` at queue-fill (where `funnel_intent.v1` is built) so the post, its facts row, and its smart link all carry the same id.

---

## 2. V1 operating model — manual bio link (honest attribution)

**The real funnel is a manually-placed bio link, one per account — no link injected into posts.** A static bio click **cannot** identify which reel drove it. V1 must not pretend it can. So attribution is **moded**:

- **`attribution_mode="account_bio"` (V1 default):** clicks attribute exactly to **account / platform / block / daypart** — never to a specific reel. The feed may expose recent candidate posts/arms as **non-deterministic context** flagged `exact_post_attribution=false`. Learning must **not** treat a bio conversion as proof a specific reel converted.
- **`attribution_mode="exact_post"` (reserved):** only a URL/landing-block that explicitly carries `aid`/`pid` sets this. Then `arm_id`/`post_id` are real and the conversion inherits them via `click_id`.

**Click-time exact data is unrecoverable if not captured** — so the `aid`/`pid` param mechanism is built now (cheap), but it only fires on the exact-post path; bio clicks leave `post_id`/`arm_id` null and carry account/platform/daypart instead.

> **Consequence (load-bearing):** V1 delivers **total-funnel measurement + account×daypart lift** = a *scheduling* signal (when to post), **not** a *content* signal (which archetype/style converts). The content→conversion reward the bandit and winner-DNA actually consume needs **exact-post** grain — see §3.5.

Post-grain derivation (`smart_links.post_id` → facts) is valid **only** where link↔post is provably 1:1 (e.g. a Threads inline link), never for the shared bio link.

---

## 3. Schema delta (additive, nullable, no backfill)

**Migration** `smart_links`: add
- `attribution_account_id text NULL` — the account this bio link belongs to (operator-assigned)
- `attribution_platform text NULL` — threads / instagram / …

**Migration** `smart_link_clicks` and `smart_link_conversions`: add
- `attribution_account_id text NULL`, `attribution_platform text NULL` — copied from the link on every click (always set in bio mode)
- `post_id text NULL`, `arm_id text NULL` — set **only** when an explicit `aid`/`pid` is present (exact-post mode); null for bio clicks
- `attribution_mode text NULL` — `"account_bio"` | `"exact_post"`

Conversion rows **copy these from the resolved click row** at postback time (self-attributing, no 3-way join). Add indexes for account/platform/time + conversion rollups; regenerate Supabase types. `audio_id` and `campaign_id` **deferred** (media/reel path, not autonomously posted) — note, don't add.

## 3.5 V1.5 — the block landing page = the arm-grain unlock

Account/daypart is too coarse to be the **content** reward (account is ~fixed per persona; daypart is timing). Exact-post attribution from a shared bio link is possible **without** a trackable URL inside the post: route the bio link to the **smart-link landing page** (`smart_links.blocks` jsonb **already exists**), where **each per-post block carries `aid`/`pid`**. A block click → `attribution_mode="exact_post"` → real `arm_id`/`post_id`.

This is the slice that delivers the arm-grain reward the bandit and winner-DNA consume. **Sequence it as V1.5, right after V1.** V1 only has to keep `arm_id` stamped post-side (§4) so it's ready the instant blocks carry it.

---

## 4. Capture path (the plumbing)

1. **Compute** `arm_id` at queue-fill, where `buildFunnelIntentMetadata` runs (`scheduleAndInsert.ts:83`). Add `attribution.armId` to `funnel_intent.v1`.
2. **Stamp** at link attach: when a smart link is created/attached for a post, append params to its redirect target. Param contract (short keys, URL-safe):
   - `aid` = arm_id
   - `pid` = post_id
   - reuse existing `utm_source/medium/campaign` (already in `funnel_intent.utm`)
3. **Persist** in `api/go/[code].ts` click insert (`:553`): read `aid`/`pid` from the request query, write to the new `arm_id`/`post_id` columns. Null-safe when absent (legacy/un-tagged links).
4. **Inherit** in `api/go/convert.ts` (`:129-143`): copy `arm_id`/`post_id` from the resolved click row onto the conversion row.

No change to HMAC, dedup, or the 30-day window.

---

## 5. The one shared feed — `autoposter_attribution_facts.v1`

A **single** normalized export (DB view or RPC), keyed by `arm_id`, emitting per arm:

| field | source |
|---|---|
| `arm_id, account_id, surface, content_archetype, visual_style` | from facts / arm components |
| `impressions, views` | `autoposter_post_performance_facts` (per-arm sum) |
| `clicks` | `count(smart_link_clicks where arm_id = …)` |
| `conversions, revenue` | `smart_link_conversions where arm_id = …` (count, sum value) |
| `click_proxy = clicks / max(impressions,1)` | derived — the **bandit Phase-0 reward** |

- **Join on `arm_id`**, falling back to `post_id` for un-tagged/1:1 legacy rows.
- **TD** `performanceFirst` consumes it directly (replaces the post-keyed `smartByPost` map with an arm-keyed one; post-keyed view kept for back-compat).
- **creator-os** consumes the same rows via the existing `performance_sync.v1` export path → recommendation/winner-DNA learning. **One feed, two readers — not two reward systems.**

---

## 6. Bandit readiness (not built here)

- **V1 (account_bio):** only account/platform/daypart lift is available — enough for a *scheduling* bandit (when to post per account), **not** an arm-level content bandit. Do not feed bio conversions as per-arm reward.
- **V1.5 (exact_post via blocks):** once clicks carry `arm_id`, `click_proxy` per arm is live → Beta-Bernoulli Thompson on the click proxy (TD side, controls live autoposter text). Conversion weighting + delay-correction (Vernade/Chapelle) after ~40 positives/arm. **The arm-grain content reward depends on V1.5, not V1.**

---

## 7. Acceptance checks

1. Click on a tagged redirect → `smart_link_clicks.arm_id` + `post_id` populated; untagged link → both null, no error.
2. **Shared-link test:** two posts (distinct `aid`/`pid`), one shared bio link → two click rows with **distinct** arm_id; a conversion on each resolves to the **correct** arm via `click_id` (not most-recent-click collision).
3. Conversion row carries the same `arm_id`/`post_id` as its linked click.
4. `autoposter_attribution_facts.v1` per-arm `clicks`/`conversions`/`revenue` **reconcile** to raw row totals (sum over arms = table totals).
5. **Shadow:** `arm_id` present and flowing end-to-end, but nothing selects on it yet — verify before any bandit wiring.
6. HMAC/dedup/30-day behavior unchanged (existing convert tests still green).

---

## 8. Open question for Codex

- The arm components live on `autoposter_post_performance_facts`, but the **smart link is attached by an operator action** (`operatorActionRequired:"attach_or_verify_profile_smart_link"`). Where should `arm_id` be computed and handed to the link-creation call — stamped into `funnel_intent.v1.attribution.armId` at queue-fill and read back at attach time, or recomputed at attach from the post's facts row? Prefer the former (compute once, single source), but confirm the attach path can read it.
- `time_bucket` granularity for the arm hash — day-part vs day vs none? Finer = more arms = slower bandit convergence. Recommend day-part; confirm against expected post volume per account.
