# Creator OS Beast Mode Audit — 2026-07-27

Audit time: `2026-07-27T21:24:10Z`

> Historical snapshot: this report preserves the system truth observed at the
> audit time. Its draft-PR and runtime statements are not current operating
> status after the final integration. Use the system map and operator runbooks
> for current commands and truth levels.

This report is read-only production reconciliation plus source inspection. It
does not authorize generation, export, scheduling, publication, database
mutation, schedule changes, or runtime promotion.

## Executive verdict

Creator OS has a strong, receipt-backed **create-to-review** lane and a strict
**export-to-metrics** contract, but it is not yet one closed autonomous product.
The strongest real loop ends at one Stacey Instagram publication with one
canonical approximately-one-hour observation and measured Reference
provenance. There are no real 24-hour or 72-hour comparable outcomes, persisted
knowledge packs, measured recommendations, or real adaptive create decisions.

The two highest-leverage confirmed gaps are:

1. normal `create` calls non-rejected imported images “approved” and can select
   them without an explicit source approval;
2. normal status cannot answer scoped operator questions without raw database
   work.

Draft PRs #526 and #527 address those independently. Neither is merged or
promoted.

## Authoritative reconciliation

| Fact | Current evidence | Truth level |
|---|---|---|
| Creator OS source | `ce977e3801f36f711c6e1ba4336d8b9e74cb196b` | merged; Release and Security green |
| Creator OS runtime | `b596fe2521a4f459a08ecd6da2bf02db0f3351a1` | promoted, clean, behind source |
| ThreadsDashboard source | `f8a57f5ea6acc0d205fa0e3928523f8832671d17` | origin/main |
| ThreadsDashboard production | `f8a57f5ea6acc0d205fa0e3928523f8832671d17` | successful Production deployment |
| Benchmark investigation | PR #525 merged; provider-free benchmark ordering stabilized | merged, not promoted |
| Open Creator OS PRs | #526 explicit source approval; #527 scoped status | draft, unmerged |
| Creator OS source checkout | clean | local |
| Runtime checkout | clean detached checkout | runtime |
| ThreadsDashboard checkout | `skills-lock.json` modified and 16 commits behind | local warning; untouched |

The clean stale Creator OS worktrees contain no unique product code after tree
comparison with `origin/main`; they were not deleted. Several Campaign rows
still store source/runtime-checkout paths even though canonical copies exist
under `~/.creator-os/artifacts`. Three such `source_assets.stored_path` values
are missing at their recorded runtime paths; hash-matching canonical copies
exist. Historical evidence is retained, but the live pointer metadata is stale.

## Maturity matrix

| Subsystem | Implemented locally | Merged to main | Promoted to runtime | Proven operationally |
|---|---:|---:|---:|---:|
| Higgsfield-only passive production | yes | yes | yes at older source | three real Kling 3 clips |
| Seedance 2 controlled alternative | yes | yes | yes at older source | prior visual bakeoff only |
| Talking / supplied voice | fail-closed | yes | yes | no |
| Motion copy | fail-closed | yes | yes | rejected recipes only |
| Audio Radar hardening | yes | yes | no | live refresh/cache proof exists on source-side code; runtime is older |
| Exact AAC binding | yes | yes | yes | three review canaries |
| Exact draft export contract | yes | yes | yes | historical export/delivery evidence; no action in this audit |
| Real publication reconciliation | yes | yes | yes | one strongest canonical trace |
| Age-aware performance sync | yes | yes | yes | one 1h observation |
| Learning consumption | yes | yes | no | fixture-proven only |
| Explicit source approval | draft PR #526 | no | no | no |
| Scoped operator status | draft PR #527 | no | no | local read-only proof |

## Live canonical counts

- Campaign: 8 campaigns, 881 source rows, 736 rendered assets, 736 generation
  attempts, 742 output blobs, 172 export attempts, 13 approval decisions, 1
  performance snapshot, and 3 completed fanout ledger entries.
- Source inventory: Stacey 470 rows (134 images), Larissa 208 videos, Lola 203
  videos. All normal source images are `imported`; zero are explicitly
  `approved`. No hash appears across different creators. Stacey has 19
  same-hash rows across campaigns.
- Reference: 520 public/reference posts, 339 review labels, 975 source files, 13
  learning runs, 1 measured prompt outcome, 0 prompt cards, and 0 viral pattern
  cards.
- Learning: 0 persisted knowledge packs, 0 recommendation runs, 0
  recommendation items, 0 supervised-active recommendations, and 0 audio
  performance rollups.
- Audio: 126 catalog tracks, 17 active/resolved tracks, 25 cached playable
  objects using 129,000,689 bytes, 1 historical canonical selection, and 4
  refresh runs. Latest refresh is partial.
- ThreadsDashboard production: 88 accounts, 8,443 posts, 269,719 metric-history
  rows, 1,191 autoposter outcomes, 59 learning-state rows, and 74,807 cron-run
  rows. Those totals include unrelated/legacy production; they are not Creator
  OS learning-proof counts.

## Golden path trace

| Transition | Owner and normal process | Identity/evidence | Failure/reconciliation | Current status |
|---|---|---|---|---|
| source intake → intent | Campaign; `creator-os create` | creator, source ID/SHA, Soul profile | missing/substituted bytes fail | **ambiguous:** imported was treated as approved |
| intent → source/prompt | Campaign production lane | creator/account/intent and learning decision | wrong-scope learning discarded | implemented; explicit source gate is draft |
| prompt → recipe | Campaign/Reel | prompt hashes, recipe fingerprint | unsupported talking/motion intents fail before quote | sound |
| recipe → spend | Campaign authorization | bounded credit cap, quote, reservations | over-cap blocks before submit | sound |
| spend → provider | Reel Higgsfield worker | request fingerprint, generation ID, model, Soul ID | ambiguous submission reconciles by original ID; no blind retry | sound |
| provider → local media | Reel/Campaign | downloaded bytes, output SHA, generation lineage | URL alone is insufficient; partial successes retained | sound |
| media → technical QC | ContentForge/Campaign | codec, dimensions, duration, duplicate and audit receipts | hard failure blocks review/export | sound; subjective anatomy/identity remains human |
| eligible video → audio | Campaign Audio Radar | catalog/music ID, source owner, track hash/fingerprint | talking intents reject replacement; empty library blocks | sound in source; runtime behind hardening |
| track → segment/AAC | Campaign audio binding | segment bounds/hash, AAC probe, final MP4 SHA | FFmpeg/hash mismatch fails closed | proven on three canaries |
| final MP4 → review | Campaign/review package | source, prompt, recipe, cost, QC, hashes | blank subjective fields mean unreviewed | packages exist; chat approval is not persisted |
| review → approval | Campaign creative approval | signed approval fingerprint bound to exact asset | changed media invalidates approval | implemented; current canaries lack durable decisions |
| approval → export | Campaign draft delivery | HMAC, stable draft/export ID, final content fingerprint | local and remote bytes rehashed; mismatch blocks | implemented |
| export → draft | ThreadsDashboard ingest | HMAC and campaign asset identity | idempotent delivery/reconciliation | implemented |
| draft → publish | ThreadsDashboard | account preflight, stable post identity, platform response | queue/HTTP success is not publication; ambiguous publish reconciles | external owner |
| publish → metrics | ThreadsDashboard | real Instagram media ID and metric history | missing stays missing; repeated observations append/update canonically | one real 1h trace |
| metrics → Campaign | hourly local sync | post/media/account, observation timestamp, lineage | incomplete/truncated data fails learning eligibility | one eligible snapshot |
| Campaign → Reference | learning fanout | outcome and evidence fingerprints | ledger makes retry idempotent | one measured provenance outcome |
| Reference → pack | `learning-refresh` | versioned pack and source fingerprint | dry-run no writes; apply idempotent | implemented, zero real packs |
| pack → recommendation | Campaign learning consumer | same creator/profile/account/intent/age; ≥3 outcomes | 1h advisory; missing/expired/wrong-scope blocked | implemented, zero real recommendations |
| recommendation → approval | `learning-review` | explicit operator decision | reject/revoke/pin override | implemented, unused in production |
| approval → later create | Campaign production lane | decision receipt states consulted/eligible/applied/changed | deterministic fallback when no active match | fixture-proven only |

## Operator experience

The supported intent-first `create` path hides provider/model IDs. Review,
approval, and export still require campaign, rendered-asset, and user IDs.
`status` has no scoped filters on main, and `audio status` is absent. PR #527
adds bounded read-only summaries without replacing the existing health command.
PR #526 adds a dry-run-first source approval surface and stops normal production
from selecting merely imported images.

The concise journey is documented in
`docs/runbooks/creator_os_operator_journey.md`. ThreadsDashboard remains the
only publication UI/owner.

## Creator identity and intent truth

- Soul bindings remain explicit for Stacey, Stacey1, Larissa, and Lola.
- No source hash currently crosses creators.
- Changed bytes fail SHA validation; three historical path pointers are stale
  but canonical copies preserve bytes.
- Supported normal passive intents: `passive_selfie`, `flirty_portrait`,
  `outfit`, `lifestyle`, and `animate_existing`.
- Kling 3 is the default; Seedance 2 is an explicit controlled alternative.
- `motion_copy`, `dance`, `talking_selfie`, and `talking_motion_copy` are
  **UNRESOLVED** and fail before paid planning.
- Rejected Kling Motion Control and InfiniteTalk evidence remains historical;
  it is not renamed or routed back into production.
- Static/photodump/visual-hook capabilities exist in advanced or legacy
  surfaces, not as falsely supported normal cloud intents.

## Prompt, overlay, and review quality

Normal prompts are intent-bound, deterministic, expanded with the existing
local vision prompt expander, and fingerprinted. Caption-bank and placement
systems own burned text; no-safe-lane means no forced overlay. Exact,
normalized, and asset-hash controls exist in multiple layers, but prompt-family
fatigue is not presented as learned behavior. There is no reliable automated
identity/anatomy approval. Review packages correctly leave these operator
fields blank.

The present review vocabulary is incomplete for “usable after edit” and
specific identity/anatomy/motion/audio rejection reasons. This is P2 usability,
not a correctness blocker, because approval remains explicit and fail-closed.

## Higgsfield reliability and cost

Three retained Kling 3 canaries have distinct sources, seeds, generation IDs,
outputs, and hashes. Generation durations were 214.571, 225.91, and 329.93
seconds (mean 256.8 seconds). Provider audio was disabled. The batch quote was
26.25 credits and actual consumption was 45 credits. Both values are persisted
separately in spend authorization/cost evidence; the +18.75 credit variance is
reconciled and stayed below the 70-credit authorization. It remains a material
cost-estimation warning, not missing spend evidence.

## Audio Radar

TikTok/SocialCrawl is primary, TikLive resolves selected IDs, Creative Center is
optional, and provider failures do not create false absence observations.
Pruning requires valid consecutive absences and retention checks. Sound-owner
attribution is separate from canonical artist metadata. Production selection
enforces creator/account/segment cooldowns and batch uniqueness, probes cached
bytes, selects a duration-compatible segment, embeds AAC, and binds the final
hash. Talking intents reject automatic music replacement.

Metadata supports coarse deterministic mood/content fit, but not reliable
semantic labels for every “flirty/playful/fashion” distinction. Ranking is
explainable in receipts; adding an LLM is not justified. The source has weekly
hardening, while the active runtime predates the latest source SHA.

The recent three-reel canary has file receipts but did not create canonical
`audio_selections` rows. Current normal binding code does persist future
selections. The custom canary should not be published as a learning cohort
until one exact final set is approved and canonical linkage is verified.

## ThreadsDashboard handoff and exact media

Campaign export validates local SHA, signs the payload, uploads/copies the exact
approved file, downloads/verifies remote bytes, and binds content fingerprints.
ThreadsDashboard production is at its current origin/main. The historical
strong-trace post carries the Campaign content fingerprint, but its
`publish_fingerprint` and independent `media_fingerprint` are null. Therefore
unchanged publish bytes for that historical post are not independently proven.
Future exact-hash handoffs are fail-closed in current source.

## Strongest real loop

- Instagram media ID: `18094620473086400`
- ThreadsDashboard post ID: `3a69a80f-dda1-4a04-95d6-f60271d4e2aa`
- Campaign snapshot: `perf_1df487ea5ddf`
- published: `2026-07-11T18:54:35Z`
- one observation at approximately 1.09 hours: 2 views, 1 reach, 0 likes,
  comments, shares, and saves
- Campaign/Reel/Reference fanout completed
- one Reference measured-provenance prompt outcome
- audio identity remains `deferred_to_notify_handoff`; it must not be backfilled

`posts.metrics_observed_at` is null even though canonical metric history exists.
The importer correctly uses metric history, but the cross-table display field
is an observability inconsistency. The last unproven transition is real
equal-age 24h/72h outcomes → pack → approved recommendation → later changed
create decision.

## Schedules

| Job | Current machine schedule | State/evidence |
|---|---|---|
| performance sync/fanout | hourly | loaded; latest output at 2026-07-27 17:17 ET; canonical 1h row retained |
| learning cohort daily | 08:30 daily | loaded; last exit 0; blocked on prior approved publish confirmation; no publish action |
| weekly improvement | Sunday 21:45 | loaded; last output shows one measured snapshot and zero evidence-backed changes |
| Audio Radar refresh | Monday 04:00 | loaded; last exit 0; latest DB run partial |
| ops digest | daily 21:30 | loaded; last exit 0 |
| knowledge/recommendation refresh | none | intentionally unscheduled |

All use the runtime checkout and the private `run-job.sh` wrapper. Runtime lag
means scheduled behavior does not yet include every current-main change. No
schedule was changed during this audit.

## Query, performance, and scale

Learning consumers query imported current packs and scoped recommendations;
indexes cover recommendation status/run, campaign runs, audio performance, and
refresh/catalog access. The no-learning path returns with zero recommendations
on current state and does not scan ThreadsDashboard production history.

Measured generation throughput is the limiting stage: roughly 4.3 minutes per
Kling clip, with normal concurrency capped at two. A single machine can finish
about 28 clips/hour at that measured mean if the provider sustains concurrency;
this is a projection, not a load test.

| Scale | Bounded projection and principal constraint |
|---|---|
| 1 creator | three-Reel batch: roughly 7–9 elapsed minutes at concurrency 2; about 45 credits observed |
| 10 creators | 30 clips: roughly 65 minutes of provider wall time; operator review becomes the bottleneck |
| 100 creators | 300 clips: roughly 10.7 provider-hours; provider quota, review, and account assignment require batching |
| 1,000 creators | 3,000 clips: roughly 107 provider-hours; single-machine FFmpeg, SQLite write contention, and review are hard blockers |
| 2,000 accounts | publication/metrics load belongs to ThreadsDashboard; account preflight, rate limits, queue partitioning, metric pagination, and human review capacity require measured load tests |

SQLite counts are presently small for Creator OS. ThreadsDashboard metric
history is already 269k rows, so pagination/truncation checks matter more than
Campaign query volume. No high-scale claim is operationally proven.

## Failure matrix

| Failure | Detection and retry/reconciliation | Retained evidence / unsafe action prevented |
|---|---|---|
| quote failure/over-cap | block before submit | authorization plan; no spend |
| submission timeout/ambiguous submit | retain fingerprint; reconcile original generation ID; never blind retry | request/spend evidence; duplicate charge prevented |
| NSFW/provider failure/refund | terminal provider status and cost event | partial successes retained; refund status preserved when exposed |
| download/corrupt media | local download/probe/hash fails | provider result retained; no review/export |
| QC failure/duplicate output | ContentForge and hard-QC blockers | bytes and audit retained; no approval |
| discovery outage | invalid/failed feed is not an absence observation | no false COOLING/STALE/prune |
| resolver/invalid audio/segment failure | candidate rejected and next eligible candidate considered | video retained; no silent output |
| FFmpeg/hash mismatch | probe and exact SHA binding fail | raw video retained; no final registration/export |
| export/HMAC/remote hash mismatch | fail before stable draft acceptance | approval and local bytes retained |
| OAuth/account-health failure | ThreadsDashboard preflight | no schedule/publication |
| QStash/publish timeout | dispatch remains pending/ambiguous; reconcile platform identity | never call queue receipt publication |
| missing Instagram ID | publication unconfirmed | excluded from learning |
| metric outage/partial history | missing observations remain missing; repeat sync | no zero fabrication |
| knowledge refresh failure | fingerprint/schema validation and idempotent imports | prior pack retained |
| stale/revoked recommendation | discarded at create | deterministic base ordering |
| promotion failure | lock, backup manifest, Git bundle, rollback | runtime/private state retained |

## Security, privacy, backup, and release

Private environment files are mode `0600`. No secret value was printed or
written to this report. Source/provider payloads and media remain under private
roots. GitHub Secret scan, CodeQL JavaScript/TypeScript, CodeQL Python, and
Trivy succeeded for exact source SHA `ce977e38`. Promotion requires three
protected PR checks plus exact-SHA release/security evidence and a trusted
workflow identity. The promotion transaction preserves a runtime lock, backup
manifest, Git bundle, rollback SHA, canonical data, and credential-scrubbed
health checks.

Historical runtime-path pointers and multiple retained byte copies increase
storage/retention complexity. They are not safe to delete until canonical
pointer repair and backup verification are separately authorized.

## Test strategy

The release gate separates focused/unit/contract/affected checks from
provider-free end-to-end evidence and security. PR #525 fixed a wall-time
benchmark ordering problem without weakening thresholds. Tests do not count as
operational provider/publication/learning proof. Node 24 is required for the
dependency-cruiser architecture check; Node 25 is unsupported.

## Prioritized findings

| ID | Priority | Evidence / impact | Correction | Complexity / risk / proof |
|---|---|---|---|---|
| SRC-001 | P0 | normal production selects all non-rejected imported images; zero canonical images are explicitly approved | fail closed on `approved`, add hash-bound dry-run approval | medium; compatibility risk; PR #526; requires inventory review |
| COHORT-001 | P1 | two different three-audio review sets exist; chat approval and recent audio selection are not canonical DB decisions | explicitly approve one exact set and verify export linkage before cohort | operational action, no speculative code |
| RUN-001 | P1 | runtime `b596fe25` trails green source `ce977e38` | promote only after chosen draft PRs merge and exact-SHA evidence passes | operational authorization required |
| STATUS-001 | P2 | main status cannot scope creator/campaign/generation/publication/learning; no audio status | bounded read-only status | low; PR #527 |
| PATH-001 | P2 | three source pointers reference removed runtime files though canonical copies exist | separately reconcile pointers by exact hash | medium migration risk; fixture plus backup proof |
| COST-001 | P2 | 26.25 credit quote vs 45 actual (+71.4%) | surface variance in status/review and keep hard authorization | low/medium; real provider behavior remains variable |
| REVIEW-001 | P2 | operator review vocabulary lacks usable-after-edit and structured failure reasons | extend existing review enum/surface only | medium contract compatibility |
| METRIC-001 | P2 | `posts.metrics_observed_at` null while metric history is canonical | fix display/projection semantics without rewriting history | cross-repo, medium |
| DOC-001 | P2 | durable map includes large advanced Wan detail and older master spec contains point-in-time claims | keep active path prominent; archive historical detail | low; this report clarifies truth |
| SCALE-001 | P3 | 1k-creator and 2k-account capacity is projection only | load-test exact queues/DB/pages after real single-creator closure | high; future evidence |
| TALK-001 | P3 | talking and motion-copy remain desired but unqualified | smallest supplied-audio and distinct transfer test only when authorized | paid/product review required |

There is no current P0 evidence of leaked secrets, wrong-creator source reuse,
duplicate publication, data loss, or double spend.

## Shortest path to real closed-loop proof

1. Review PR #526, then explicitly approve the intended Stacey source images;
   do not mass-approve imported inventory.
2. Choose and persist one exact three-Reel final set, including exact audio
   selection/final SHA, Campaign approval, and intended Stacey account.
3. Merge reviewed source/status/docs PRs; wait for exact-SHA release/security;
   promote once.
4. Export the exact approved media and publish through ThreadsDashboard at the
   controlled spacing in `docs/runbooks/stacey_real_learning_proof.md`.
5. Collect comparable 24h or 72h observations for all three, run
   `learning-refresh`, approve one recommendation, and verify Reel 4 dry-run
   records a genuinely changed approved choice.

Until step 5, the learning consumer is implemented and fixture-proven, not
operationally self-improving.
