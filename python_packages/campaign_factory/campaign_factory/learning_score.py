from __future__ import annotations

import math
from datetime import UTC, datetime
from statistics import median
from typing import Any

PRIOR_RELATIVE_REWARD = 1.0
PRIOR_STRENGTH = 5.0
RECENCY_HALF_LIFE_DAYS = 21.0
DEFAULT_REWARD_BASELINE = 0.35
MIN_ACCOUNT_BASELINE_SAMPLES = 2
EXPLORATION_FLOOR = 0.15
EXPLORATION_MIN_EFFECTIVE_TRIALS = 5.0


def account_reward_baselines(snapshots: list[dict[str, Any]]) -> dict[str, float]:
    rewards: dict[str, list[float]] = {}
    for snapshot in latest_snapshots_by_post(snapshots):
        account = str(
            snapshot.get("instagramAccountId") or snapshot.get("accountId") or ""
        ).strip()
        if not account:
            continue
        reward = snapshot_reward(snapshot)
        if reward is None:
            continue
        rewards.setdefault(account, []).append(reward)
    return {
        account: max(0.000001, median(values))
        for account, values in rewards.items()
        if len(values) >= MIN_ACCOUNT_BASELINE_SAMPLES
    }


def aggregate_performance(
    snapshots: list[dict[str, Any]],
    *,
    account_baselines: dict[str, float] | None = None,
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    latest = latest_snapshots_by_post(snapshots)
    totals = {
        "views": 0,
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "saves": 0,
        "impressions": 0,
        "reach": 0,
        "watchTimeSeconds": 0.0,
    }
    for snapshot in latest:
        metrics = snapshot.get("metrics") or {}
        for key in totals:
            value = metrics.get(key)
            if isinstance(value, (int, float)):
                totals[key] += value
    count = len(latest)
    averages = {
        key: (value / count if count else None) for key, value in totals.items()
    }
    engagement_total = (
        totals["likes"] + totals["comments"] + totals["shares"] + totals["saves"]
    )
    exposure_total = totals["impressions"] or totals["reach"] or totals["views"]
    rates = {
        "engagementRate": (
            engagement_total / exposure_total if exposure_total else None
        ),
        "saveRate": (totals["saves"] / exposure_total if exposure_total else None),
        "shareRate": (totals["shares"] / exposure_total if exposure_total else None),
        "viewThroughRate": (
            totals["views"] / totals["impressions"] if totals["impressions"] else None
        ),
    }
    learning = learning_summary(
        latest, account_baselines=account_baselines or {}, reference_now=reference_now
    )
    return {
        "count": count,
        "totals": totals,
        "averages": averages,
        "rates": rates,
        "latest": latest[0] if latest else None,
        "learning": learning,
    }


def performance_score(summary: dict[str, Any]) -> int | None:
    if not summary.get("count"):
        return None
    learning = (
        summary.get("learning") if isinstance(summary.get("learning"), dict) else {}
    )
    score = learning.get("score")
    if isinstance(score, (int, float)):
        return int(max(0, min(100, round(score))))
    return None


def performance_planning_score(summary: dict[str, Any]) -> int | None:
    if not summary.get("count"):
        return None
    learning = (
        summary.get("learning") if isinstance(summary.get("learning"), dict) else {}
    )
    bandit = learning.get("bandit") if isinstance(learning.get("bandit"), dict) else {}
    score = bandit.get("planningScore")
    if isinstance(score, (int, float)):
        return int(max(0, min(100, round(score))))
    return performance_score(summary)


def learning_summary(
    snapshots: list[dict[str, Any]],
    *,
    account_baselines: dict[str, float],
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    if not snapshots:
        return {
            "status": "unmeasured",
            "scoringVersion": "account_normalized_decay_shrinkage.v1",
            "score": None,
            "effectiveSampleSize": 0.0,
            "priorRelativeReward": PRIOR_RELATIVE_REWARD,
            "priorStrength": PRIOR_STRENGTH,
            "recencyHalfLifeDays": RECENCY_HALF_LIFE_DAYS,
            "defaultRewardBaseline": DEFAULT_REWARD_BASELINE,
        }
    now = (
        reference_now
        or max(
            (_parse_time(snapshot.get("snapshotAt")) for snapshot in snapshots),
            default=None,
        )
        or datetime.now(UTC)
    )
    weighted_total = 0.0
    weight_total = 0.0
    measured = 0
    unmeasured = 0
    beat_weight = 0.0
    miss_weight = 0.0
    baseline_source_counts = {"account_median": 0, "default_prior": 0}
    for snapshot in snapshots:
        reward = snapshot_reward(snapshot)
        if reward is None:
            unmeasured += 1
            continue
        account = str(
            snapshot.get("instagramAccountId") or snapshot.get("accountId") or ""
        ).strip()
        baseline = account_baselines.get(account)
        if baseline is None:
            baseline = DEFAULT_REWARD_BASELINE
            baseline_source_counts["default_prior"] += 1
        else:
            baseline_source_counts["account_median"] += 1
        relative_reward = reward / max(0.000001, baseline)
        weight = recency_weight(snapshot.get("snapshotAt"), now=now)
        weighted_total += relative_reward * weight
        weight_total += weight
        if relative_reward >= PRIOR_RELATIVE_REWARD:
            beat_weight += weight
        else:
            miss_weight += weight
        measured += 1
    if measured == 0 or weight_total <= 0:
        return {
            "status": "unmeasured",
            "scoringVersion": "account_normalized_decay_shrinkage.v1",
            "score": None,
            "measuredCount": 0,
            "unmeasuredCount": unmeasured,
            "effectiveSampleSize": 0.0,
            "priorRelativeReward": PRIOR_RELATIVE_REWARD,
            "priorStrength": PRIOR_STRENGTH,
            "recencyHalfLifeDays": RECENCY_HALF_LIFE_DAYS,
            "defaultRewardBaseline": DEFAULT_REWARD_BASELINE,
            "baselineSourceCounts": baseline_source_counts,
        }
    weighted_mean = weighted_total / weight_total
    shrunk = (
        (PRIOR_STRENGTH * PRIOR_RELATIVE_REWARD) + (weight_total * weighted_mean)
    ) / (PRIOR_STRENGTH + weight_total)
    score = 50 + ((shrunk - 1.0) * 30)
    bandit = bandit_summary(
        beat_weight=beat_weight, miss_weight=miss_weight, effective_trials=weight_total
    )
    return {
        "status": "measured",
        "scoringVersion": "account_normalized_decay_shrinkage.v1",
        "score": int(max(0, min(100, round(score)))),
        "measuredCount": measured,
        "unmeasuredCount": unmeasured,
        "effectiveSampleSize": round(weight_total, 4),
        "weightedRelativeReward": round(weighted_mean, 4),
        "shrunkRelativeReward": round(shrunk, 4),
        "priorRelativeReward": PRIOR_RELATIVE_REWARD,
        "priorStrength": PRIOR_STRENGTH,
        "recencyHalfLifeDays": RECENCY_HALF_LIFE_DAYS,
        "defaultRewardBaseline": DEFAULT_REWARD_BASELINE,
        "baselineSourceCounts": baseline_source_counts,
        "bandit": bandit,
    }


def bandit_summary(
    *, beat_weight: float, miss_weight: float, effective_trials: float
) -> dict[str, Any]:
    alpha = 1.0 + max(0.0, beat_weight)
    beta = 1.0 + max(0.0, miss_weight)
    posterior_mean = alpha / (alpha + beta)
    exploration_priority = (
        "explore" if effective_trials < EXPLORATION_MIN_EFFECTIVE_TRIALS else "exploit"
    )
    # Deterministic Thompson-ready planning score: posterior expectation plus a
    # bounded cold-start floor. The random sampler can be introduced later
    # without changing stored arm statistics.
    exploration_bonus = EXPLORATION_FLOOR * max(
        0.0, 1.0 - min(1.0, effective_trials / EXPLORATION_MIN_EFFECTIVE_TRIALS)
    )
    planning_score = min(1.0, posterior_mean + exploration_bonus) * 100.0
    return {
        "algorithm": "beta_bernoulli_decayed_v1",
        "rewardEvent": "relative_reward_beats_account_baseline",
        "alpha": round(alpha, 4),
        "beta": round(beta, 4),
        "posteriorMean": round(posterior_mean, 4),
        "planningScore": int(round(planning_score)),
        "effectiveTrials": round(effective_trials, 4),
        "explorationFloor": EXPLORATION_FLOOR,
        "explorationPriority": exploration_priority,
        "explorationMinEffectiveTrials": EXPLORATION_MIN_EFFECTIVE_TRIALS,
    }


def latest_snapshots_by_post(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for index, snapshot in enumerate(snapshots):
        key = str(snapshot.get("postId") or snapshot.get("id") or index)
        current = latest.get(key)
        if current is None or _sort_time(snapshot) >= _sort_time(current):
            latest[key] = snapshot
    return sorted(latest.values(), key=_sort_time, reverse=True)


def snapshot_reward(snapshot: dict[str, Any]) -> float | None:
    metrics = snapshot.get("metrics") or {}
    exposure = (
        _number(metrics.get("reach"))
        or _number(metrics.get("impressions"))
        or _number(metrics.get("views"))
    )
    if not exposure or exposure <= 0:
        return None
    engagement = sum(
        _number(metrics.get(key)) or 0.0
        for key in ("likes", "comments", "shares", "saves")
    )
    engagement_rate = engagement / exposure
    return math.log1p(exposure) * engagement_rate


def recency_weight(value: Any, *, now: datetime) -> float:
    parsed = _parse_time(value)
    if parsed is None:
        return 1.0
    age_days = max(0.0, (now - parsed).total_seconds() / 86400.0)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def _sort_time(snapshot: dict[str, Any]) -> datetime:
    return _parse_time(
        snapshot.get("snapshotAt") or snapshot.get("createdAt")
    ) or datetime.min.replace(tzinfo=UTC)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
