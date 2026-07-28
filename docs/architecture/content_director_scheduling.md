# Content Director Scheduling Policy

Creator OS proposes windows. ThreadsDashboard schedules and publishes.

Source hierarchy:

1. active supervised account-specific timing recommendation;
2. adequate equal-age measured account windows;
3. configured account schedule policy;
4. deterministic safe fallback.

The current implementation truth is layer four unless stronger authenticated
evidence is present. It labels this honestly and never claims learned timing.
The fallback uses the plan timezone, deterministic weekday/weekend hours,
operator blackout dates, and a per-account minimum gap. It does not use the wall
clock as an accidental default.

Proposals must also respect account health, pending work, cadence, platform
limits, experiment comparability, metric windows, content urgency, and trend
freshness before operational rollout. Operator-pinned times are immutable.
Schedule changes never rewrite creative or media lineage.

Healthy eligible accounts normally use their configured daily cadence. A
warming, health-constrained, inventory-constrained, platform-limited, or
operator-lowered account may use every-other-day cadence. Accounts advance
independently: work assigned to another account does not consume a calendar day
for this account. Minimum gaps still apply, and ThreadsDashboard reconciles
pending or stale schedules before creating external schedule state.

Metric observations do not serialize publication. The 1h, 24h, and 72h windows
are calculated independently from each post's actual publication timestamp and
may overlap. Learning compares equal-age observation buckets rather than posts
sharing a publication date.
