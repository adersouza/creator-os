from __future__ import annotations

import math
import os
from datetime import UTC, datetime
from statistics import median
from typing import Any

LEARNING_LOOP_CUTOVER_ENV = "LEARNING_LOOP_CUTOVER"

# Shared SQL fragment for the learning-eligibility predicate. MUST stay in
# lockstep with learning_eligible() below (parity enforced by tests). Bind
# :learning_loop_cutover to learning_loop_cutover_iso(); when the cutover is
# unset the loop is not cut over and NOTHING is eligible (fail closed) —
# callers must short-circuit on learning_loop_cutover() is None before using
# this fragment, or bind an impossible sentinel.
LEARNING_ELIGIBLE_SQL = (
    "metrics_eligible = 1"
    " AND history_source = 'metric_history'"
    " AND published_at IS NOT NULL"
    " AND julianday(published_at) >= julianday(:learning_loop_cutover)"
    " AND lineage_v2_valid = 1"
)


def learning_eligible_sql(prefix: str = "") -> str:
    """Positional-parameter (?) form of LEARNING_ELIGIBLE_SQL.

    Append learning_loop_cutover_iso() to the query params for the single
    placeholder. Callers MUST fail closed (return no rows) when
    learning_loop_cutover_iso() is None instead of using this fragment.
    """
    return (
        f"{prefix}metrics_eligible = 1"
        f" AND {prefix}history_source = 'metric_history'"
        f" AND {prefix}published_at IS NOT NULL"
        f" AND julianday({prefix}published_at) >= julianday(?)"
        f" AND {prefix}lineage_v2_valid = 1"
    )


def learning_loop_cutover() -> datetime | None:
    """Parse LEARNING_LOOP_CUTOVER (ISO timestamp, set at deploy)."""
    raw = (os.environ.get(LEARNING_LOOP_CUTOVER_ENV) or "").strip()
    if not raw:
        return None
    return _parse_time(raw)


def learning_loop_cutover_iso() -> str | None:
    cutover = learning_loop_cutover()
    if cutover is None:
        return None
    return cutover.isoformat()


def learning_eligible(
    snapshot: dict[str, Any], *, cutover: datetime | None = None
) -> bool:
    """THE eligibility predicate for ALL learning readers.

    Forward-only counting via explicit cutover: metrics_eligible=1 AND
    history_source='metric_history' AND published_at non-null AND
    published_at >= LEARNING_LOOP_CUTOVER AND lineage_v2_valid=1.
    Fail closed: unset/unparseable cutover or published_at => ineligible.
    Keep in lockstep with LEARNING_ELIGIBLE_SQL.
    """
    return not learning_ineligibility_reasons(snapshot, cutover=cutover)


def learning_ineligibility_reasons(
    snapshot: dict[str, Any], *, cutover: datetime | None = None
) -> list[str]:
    """Explain the shared predicate without creating a second eligibility rule."""
    reasons: list[str] = []
    if _flag_int(_snapshot_value(snapshot, "metrics_eligible", "metricsEligible")) != 1:
        reasons.append("metrics_not_eligible")
    if (
        _snapshot_value(snapshot, "history_source", "historySource") or ""
    ) != "metric_history":
        reasons.append("fallback_history_source")
    published_at = _parse_time(_snapshot_value(snapshot, "published_at", "publishedAt"))
    if published_at is None:
        reasons.append("null_published_at")
    if cutover is None:
        cutover = learning_loop_cutover()
    if cutover is None:
        reasons.append("cutover_unset")
    elif published_at is not None and published_at < cutover:
        reasons.append("pre_cutover")
    if _flag_int(_snapshot_value(snapshot, "lineage_v2_valid", "lineageV2Valid")) != 1:
        reasons.append("manual_or_invalid_lineage_v2")
    return reasons


def _snapshot_value(snapshot: dict[str, Any], snake: str, camel: str) -> Any:
    return snapshot[snake] if snake in snapshot else snapshot.get(camel)


def _flag_int(value: Any) -> int:
    if value is True:
        return 1
    if value is False or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


PRIOR_RELATIVE_REWARD = 1.0
PRIOR_STRENGTH = 5.0
RECENCY_HALF_LIFE_DAYS = 21.0
DEFAULT_REWARD_BASELINE = 0.35
MIN_ACCOUNT_BASELINE_SAMPLES = 2
EXPLORATION_FLOOR = 0.15
EXPLORATION_MIN_EFFECTIVE_TRIALS = 5.0
SCORING_VERSION = "account_normalized_decay_shrinkage.v1"


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
    baselines: dict[str, float] = {}
    for account, values in rewards.items():
        if len(values) < MIN_ACCOUNT_BASELINE_SAMPLES:
            continue
        baseline = median(values)
        if _positive_finite(baseline):
            baselines[account] = float(baseline)
    return baselines


def snapshot_normalized_reward(
    snapshot: dict[str, Any], baselines: dict[str, float]
) -> float:
    """Return the unshrunk per-snapshot reward relative to its account baseline."""
    reward = snapshot_reward(snapshot)
    if reward is None:
        raise ValueError("snapshot has no measurable exposure")
    account = str(
        snapshot.get("instagramAccountId") or snapshot.get("accountId") or ""
    ).strip()
    baseline = baselines.get(account)
    if not _positive_finite(baseline):
        baseline = DEFAULT_REWARD_BASELINE
    return reward / baseline


def account_reward_baseline_provenance(
    snapshots: list[dict[str, Any]], *, computed_at: str
) -> dict[str, dict[str, Any]]:
    """Describe the exact baseline a new Reference outcome stamp will freeze."""
    rewards: dict[str, list[float]] = {}
    for snapshot in latest_snapshots_by_post(snapshots):
        account = str(
            snapshot.get("instagramAccountId") or snapshot.get("accountId") or ""
        ).strip()
        if not account:
            continue
        reward = snapshot_reward(snapshot)
        if reward is not None:
            rewards.setdefault(account, []).append(reward)
    result: dict[str, dict[str, Any]] = {}
    for account, values in rewards.items():
        raw_median = median(values) if values else None
        uses_account_median = (
            len(values) >= MIN_ACCOUNT_BASELINE_SAMPLES
            and raw_median is not None
            and _positive_finite(raw_median)
        )
        baseline = raw_median if uses_account_median else DEFAULT_REWARD_BASELINE
        result[account] = {
            "account": account,
            "medianValue": float(baseline),
            "sampleN": len(values),
            "computedAt": computed_at,
            "source": "account_median" if uses_account_median else "default_prior",
        }
        if len(values) >= MIN_ACCOUNT_BASELINE_SAMPLES and not uses_account_median:
            result[account]["baselineMissingReason"] = (
                "zero_or_nonfinite_account_median"
            )
    return result


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
            "scoringVersion": SCORING_VERSION,
            "score": None,
            "effectiveSampleSize": 0.0,
            "priorRelativeReward": PRIOR_RELATIVE_REWARD,
            "priorStrength": PRIOR_STRENGTH,
            "recencyHalfLifeDays": RECENCY_HALF_LIFE_DAYS,
            "defaultRewardBaseline": DEFAULT_REWARD_BASELINE,
        }
    parsed_times = [
        parsed
        for parsed in (
            _parse_time(snapshot.get("snapshotAt")) for snapshot in snapshots
        )
        if parsed is not None
    ]
    now = reference_now or (max(parsed_times) if parsed_times else datetime.now(UTC))
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
        weight = recency_weight(snapshot.get("snapshotAt"), now=now)
        if weight <= 0:
            unmeasured += 1
            continue
        relative_reward = snapshot_normalized_reward(snapshot, account_baselines)
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
            "scoringVersion": SCORING_VERSION,
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
        "scoringVersion": SCORING_VERSION,
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
    exposure = _first_positive_number(
        metrics.get("reach"),
        metrics.get("impressions"),
        metrics.get("views"),
    )
    if not exposure or exposure <= 0:
        return None
    engagement = sum(
        max(0.0, _number(metrics.get(key)) or 0.0)
        for key in ("likes", "comments", "shares", "saves")
    )
    engagement_rate = engagement / exposure
    return math.log1p(exposure) * engagement_rate


def recency_weight(value: Any, *, now: datetime) -> float:
    parsed = _parse_time(value)
    if parsed is None:
        return 0.0
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
    # Garbage-in guard: bools are not counts, and NaN/inf would propagate
    # through rewards into weighted means and scores (NaN poisons every
    # comparison downstream). Treat all of them as "not a number".
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    return None


def _positive_finite(value: Any) -> bool:
    number = _number(value)
    return number is not None and number > 0


def _first_positive_number(*values: Any) -> float | None:
    for value in values:
        parsed = _number(value)
        if parsed is not None and parsed > 0:
            return parsed
    return None
