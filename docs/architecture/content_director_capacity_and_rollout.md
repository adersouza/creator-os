# Content Director Capacity and Rollout

## Capacity

The first supported operating envelope is one creator/three accounts, then ten
creators/one hundred accounts. Plan/item, experiment, metric-due, creator,
account, intent, and state indexes keep routine reads bounded. Plan building
does not scan global metric history; supervised recommendation lookup remains
creator/account/intent scoped.

`creator-os capacity benchmark` is the only capacity-claim path. It builds a
new isolated Campaign Factory database, Reel Factory queue, sharded artifact
tree, local media corpus, and backup/restore drill below an explicitly selected
non-runtime workspace. It never calls a paid provider or publishing route.

The defined exact tiers are:

| Tier | Creators | Assets and asset files | Claim status |
|---|---:|---:|---|
| `smoke` | 2 | 128 | never claim-eligible; correctness testing only |
| `10-creators-10k-assets` | 10 | 10,000 | supported by the 2026-08-01 exact-tier local receipt |
| `100-creators-100k-assets` | 100 | 100,000 | unmeasured |
| `1000-creators-1m-assets` | 1,000 | 1,000,000 | unmeasured |

A tier is supported only when its exact requested database rows and files
exist and every mandatory lane passes: query/index use, SQLite contention,
filesystem traversal, SHA/FFprobe, local FFmpeg, local ContentForge,
render/admission queues, report latency, backup/restore, and interrupted-work
recovery. The receipt must also pass the versioned thresholds and its own
claim validator. Partial, skipped, smoke, projected, or smaller-tier evidence
cannot support or infer a larger tier.

Example:

```bash
creator-os capacity benchmark \
  --tier smoke \
  --workspace /private/tmp/creator-os-capacity
```

Large tiers are explicit local release operations and do not run in CI. CI may
run the smoke tier, but a smoke receipt always records
`largestSupportedTier: null`.

Hard blockers before two thousand accounts include account-health projection
latency, review throughput, schedule conflict resolution, metric-history and
receipt growth, audio cooldown contention, generation concurrency, storage,
and ThreadsDashboard export throughput. These require measured capacity work,
not speculative optimization in the planner.

Until exact-tier receipts are produced and reviewed, the existing
ten-creator/one-hundred-account operating ceiling remains unchanged. The
projection-only doctor fixture is not measurement evidence and all of its
`measured_inputs` values remain false.

The retained local receipt at
`~/.creator-os/artifacts/reports/capacity-10-creators-10k-assets-20260801.json`
passed all twelve mandatory lanes and supports exactly the
`10-creators-10k-assets` tier. It does not imply support for the 100k or 1m
tiers.

## Real-production rollout

1. Shadow-plan Stacey for seven days; compare with operator judgment; generate
   nothing.
2. Run one supervised Stacey plan; approve every item; bounded generation; no
   automatic publication.
3. Export/schedule three comparable approved Stacey Reels through
   ThreadsDashboard; collect 24h/72h outcomes; refresh and approve learning;
   verify Reel four's receipt shows a real changed decision.
4. Expand to multiple Stacey accounts while proving account isolation and
   schedule proposals.
5. Expand to Larissa and Lola while proving no cross-creator learning leakage.
6. Consider approved-plan autopilot only after real evidence. Never enable
   unrestricted autonomous publishing.

Until stage three succeeds, the Content Director is implemented and
fixture-proven, not operationally proven to improve production.
