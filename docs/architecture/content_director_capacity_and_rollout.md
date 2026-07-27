# Content Director Capacity and Rollout

## Capacity

The first supported operating envelope is one creator/three accounts, then ten
creators/one hundred accounts. Plan/item, experiment, metric-due, creator,
account, intent, and state indexes keep routine reads bounded. Plan building
does not scan global metric history; supervised recommendation lookup remains
creator/account/intent scoped.

Hard blockers before two thousand accounts include account-health projection
latency, review throughput, schedule conflict resolution, metric-history and
receipt growth, audio cooldown contention, generation concurrency, storage,
and ThreadsDashboard export throughput. These require measured capacity work,
not speculative optimization in the planner.

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
