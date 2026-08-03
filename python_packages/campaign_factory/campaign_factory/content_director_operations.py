"""Schedule, experiment, execution, review, and lineage operations for content plans."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .content_director import (
    PlanningRequest,
    _json,
    _now,
    build_plan,
    load_plan,
    persist_plan,
)
from .content_director import (
    _fingerprint as plan_fingerprint,
)
from .learning_governance import register_experiment_design
from .observed_experiment_reporting import (
    BLOCKED_ASSIGNMENT_METHOD,
    BLOCKED_MEASUREMENT_PLAN,
    EXPERIMENT_FACTORS,
    OBSERVED_MEASUREMENT_PLAN,
    OBSERVED_PROFILE_SEQUENCE,
    select_observed_profile,
)
from .production_lane import plan_production_batch, run_production_batch

OBSERVATION_BUCKETS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "72h": timedelta(hours=72),
}
REVIEW_ACTIONS = frozenset(
    {
        "APPROVE",
        "REJECT",
        "REQUEST_SMALL_EDIT",
        "REPLACE_AUDIO",
        "REGENERATE",
        "DEFER",
        "CANCEL",
    }
)
EXPERIMENT_VARIABLES = frozenset(
    {
        "source_family",
        "hook_family",
        "prompt_pattern",
        "audio_profile",
        "posting_window",
        "observed_profile",
        *EXPERIMENT_FACTORS,
    }
)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _learned_posting_hour(
    conn: sqlite3.Connection, account_handle: str, weekday: int
) -> dict[str, Any] | None:
    account = conn.execute(
        "SELECT id FROM accounts WHERE handle = ? ORDER BY id LIMIT 1",
        (account_handle,),
    ).fetchone()
    account_ids = [account_handle]
    if account and str(account["id"]) != account_handle:
        account_ids.append(str(account["id"]))
    placeholders = ",".join("?" for _ in account_ids)
    row = conn.execute(
        f"""
        SELECT hour, SUM(sample_size) AS sample_size,
               ROUND(SUM(performance_score * sample_size) * 1.0 /
                     SUM(sample_size), 4) AS performance_score
        FROM account_posting_windows
        WHERE account_id IN ({placeholders}) AND weekday = ?
          AND sample_size > 0 AND performance_score IS NOT NULL
        GROUP BY hour
        HAVING SUM(sample_size) >= 3
        ORDER BY performance_score DESC, sample_size DESC, hour
        LIMIT 1
        """,
        (*account_ids, weekday),
    ).fetchone()
    if not row:
        return None
    return {
        "hour": int(row["hour"]),
        "sampleSize": int(row["sample_size"]),
        "performanceScore": float(row["performance_score"]),
    }


def propose_schedule(
    conn: sqlite3.Connection,
    plan_id: str,
    *,
    apply: bool,
    blackout_dates: frozenset[str] = frozenset(),
    minimum_gap_hours: int = 20,
) -> dict[str, Any]:
    """Propose deterministic per-account windows; never schedules externally."""
    plan = load_plan(conn, plan_id)
    zone = ZoneInfo(plan["timezone"])
    horizon_start = datetime.fromisoformat(plan["horizon"]["start"]).date()
    next_day_by_account: dict[str, int] = {}
    previous_by_account: dict[str, datetime] = {}
    proposals: list[dict[str, Any]] = []
    for item in plan["items"]:
        account = str(item["target_account"])
        day_offset = next_day_by_account.get(account, 0)
        while True:
            candidate_date = horizon_start + timedelta(days=day_offset)
            learned = _learned_posting_hour(conn, account, candidate_date.weekday())
            candidate = datetime.combine(
                candidate_date,
                time(
                    hour=(
                        int(learned["hour"])
                        if learned
                        else 12
                        if candidate_date.weekday() >= 5
                        else 18
                    ),
                    minute=30,
                ),
                tzinfo=zone,
            )
            previous = previous_by_account.get(account)
            if candidate_date.isoformat() in blackout_dates or (
                previous is not None
                and candidate - previous < timedelta(hours=minimum_gap_hours)
            ):
                day_offset += 1
                continue
            break
        layer = (
            "measured_account_posting_window"
            if learned
            else "safe_deterministic_default"
        )
        source: str | dict[str, Any] = (
            {
                **learned,
                "weekday": candidate_date.weekday(),
                "memoryTable": "account_posting_windows",
            }
            if learned
            else "machine_local_content_director_policy"
        )
        proposal = {
            "schema": "creator_os.schedule_proposal.v1",
            "planId": plan["planId"],
            "planItemId": item["id"],
            "targetAccount": account,
            "timezone": plan["timezone"],
            "windowStart": candidate.isoformat(),
            "windowEnd": (candidate + timedelta(minutes=30)).isoformat(),
            "minimumGapHours": minimum_gap_hours,
            "sourceLayer": layer,
            "sourceEvidence": source,
            "learnedTiming": learned is not None,
            "threadsdashboardFinalAuthority": True,
            "status": "PROPOSED",
        }
        proposals.append(proposal)
        previous_by_account[account] = candidate
        next_day_by_account[account] = day_offset + 1
        if apply:
            conn.execute(
                """
                UPDATE creative_plan_items
                SET proposed_window_json = ?, updated_at = ?
                WHERE id = ? AND proposed_window_json = '{}'
                """,
                (_json(proposal), _now(), item["id"]),
            )
    if apply:
        conn.commit()
    return {
        "schema": "creator_os.schedule_proposal_set.v1",
        "planId": plan["planId"],
        "dryRun": not apply,
        "proposals": proposals,
        "externalSchedulesCreated": 0,
    }


def design_experiment(
    conn: sqlite3.Connection,
    *,
    plan_id: str,
    changed_variable: str,
    variants: tuple[str, ...],
    hypothesis: str,
    apply: bool,
    assignment_method: str = "deterministic_alternation",
) -> dict[str, Any]:
    if changed_variable not in EXPERIMENT_VARIABLES:
        raise ValueError(f"unsupported experiment variable: {changed_variable}")
    if len(set(variants)) != 2:
        raise ValueError("an initial experiment requires exactly two distinct variants")
    plan = load_plan(conn, plan_id)
    blocked = assignment_method == BLOCKED_ASSIGNMENT_METHOD
    if blocked and changed_variable not in EXPERIMENT_FACTORS:
        raise ValueError(
            f"blocked experiment does not support factor: {changed_variable}"
        )
    items = plan["items"] if blocked else plan["items"][:2]
    if len(items) < 2:
        raise ValueError("experiment requires at least two plan items")
    if blocked and len(items) % 2:
        raise ValueError("blocked experiment requires an even number of plan items")
    if blocked:
        account_counts: dict[str, int] = {}
        for item in items:
            account = str(item["target_account"])
            account_counts[account] = account_counts.get(account, 0) + 1
        if any(count % 2 for count in account_counts.values()):
            raise ValueError(
                "blocked experiment requires paired plan items within every account"
            )
    legacy_observed = assignment_method == "cross_account_blocked_rotation.v1"
    if legacy_observed and changed_variable != "observed_profile":
        raise ValueError("cross-account rotation requires observed_profile")
    observed = changed_variable == "observed_profile" and (legacy_observed or blocked)
    profile_decision = None
    if observed:
        if legacy_observed and len({item["target_account"] for item in items}) != 2:
            raise ValueError("observed-profile experiment requires two accounts")
        if variants == ("control", "auto"):
            profile_decision = select_observed_profile(
                conn,
                creator=str(plan["creator"]),
                content_intent=str(items[0]["content_intent"]),
                source_asset_id=items[0]["source_asset_id"],
                purpose="experiment",
            )
            selected = profile_decision["selectedProfile"]
            if selected is None:
                raise ValueError(
                    f"no observed profile is eligible: {profile_decision['mode']}"
                )
            variants = ("control", str(selected))
        if variants[0] != "control" or not variants[1].endswith("@1"):
            raise ValueError(
                "observed-profile variants must be control and one @1 profile"
            )
        if variants[1] not in OBSERVED_PROFILE_SEQUENCE:
            raise ValueError(f"unsupported observed profile: {variants[1]}")
        sequence_index = OBSERVED_PROFILE_SEQUENCE.index(variants[1])
        if apply and sequence_index:
            previous = OBSERVED_PROFILE_SEQUENCE[sequence_index - 1]
            decided = conn.execute(
                """
                SELECT 1 FROM creative_plan_experiments
                WHERE changed_variable = 'observed_profile'
                  AND json_extract(variants_json, '$[1]') = ?
                  AND creator = ?
                  AND status = 'DECIDED'
                LIMIT 1
                """,
                (previous, plan["creator"]),
            ).fetchone()
            skipped_by_eligibility = bool(
                profile_decision
                and previous in profile_decision.get("blockedProfiles", {})
            )
            if not decided and not skipped_by_eligibility:
                raise ValueError(
                    f"previous observed-profile experiment is not decided: {previous}"
                )
    elif not blocked and len({item["target_account"] for item in items}) != 1:
        raise ValueError("experiment variants must use the same account")
    if len({item["content_intent"] for item in items}) != 1:
        raise ValueError("experiment variants must use the same content intent")
    seed = int(_fingerprint([plan_id, changed_variable, variants])[:8], 16)
    experiment_id = f"pexp_{_fingerprint([plan_id, changed_variable, variants])[:16]}"
    controlled_universe = {
        "creator",
        "account",
        "content_intent",
        "observation_cohort",
        "publication_window",
    }
    if blocked:
        controlled_universe.update(EXPERIMENT_FACTORS)
    controlled = sorted(controlled_universe - {changed_variable})
    assignments = (
        [
            {
                "planItemId": item["id"],
                "variant": None,
                "experimentClass": "PENDING_BLOCKED_ROTATION",
            }
            for item in items
        ]
        if legacy_observed or blocked
        else [
            {
                "planItemId": item["id"],
                "variant": variants[index],
                "experimentClass": "CONTROL" if index == 0 else "CONTROLLED_VARIATION",
            }
            for index, item in enumerate(items)
        ]
    )
    receipt = {
        "schema": "creator_os.plan_experiment.v1",
        "experimentId": experiment_id,
        "planId": plan["planId"],
        "creator": plan["creator"],
        "accountScope": sorted({item["target_account"] for item in items}),
        "contentIntent": items[0]["content_intent"],
        "hypothesis": hypothesis,
        "controlledVariables": controlled,
        "changedVariable": changed_variable,
        "variants": list(variants),
        "assignmentMethod": assignment_method,
        "deterministicSeed": seed,
        "requiredObservationCohort": (
            "24h_primary_72h_confirmatory" if legacy_observed or blocked else "24h"
        ),
        "minimumSampleWarning": (
            "fewer than three matched pairs are insufficient"
            if legacy_observed or blocked
            else "two items show an observed difference only; not causal proof"
        ),
        "measurementPlan": (
            BLOCKED_MEASUREMENT_PLAN
            if blocked
            else OBSERVED_MEASUREMENT_PLAN
            if legacy_observed
            else None
        ),
        "profileDecision": profile_decision,
        "operationalBlockers": (
            ["exact_track_reuse_policy_exception_required"]
            if blocked and changed_variable == "audio_track"
            else []
        ),
        "assignments": assignments,
        "status": "PROPOSED",
    }
    if apply:
        now = _now()
        conn.execute(
            """
            INSERT OR IGNORE INTO creative_plan_experiments (
              id, plan_version_id, creator, account_scope_json, content_intent,
              hypothesis, controlled_variables_json, changed_variable,
              variants_json, assignment_method, deterministic_seed,
              publication_windows_json, required_observation_cohort,
              minimum_sample_warning, status, outcome_links_json,
              interpretation_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, 'PROPOSED',
                      '[]', ?, ?, ?)
            """,
            (
                experiment_id,
                plan["planId"],
                plan["creator"],
                _json(receipt["accountScope"]),
                receipt["contentIntent"],
                hypothesis,
                _json(controlled),
                changed_variable,
                _json(variants),
                receipt["assignmentMethod"],
                seed,
                receipt["requiredObservationCohort"],
                receipt["minimumSampleWarning"],
                _json(
                    {
                        "measurementPlan": receipt["measurementPlan"],
                        "profileDecision": profile_decision,
                        "operationalBlockers": receipt["operationalBlockers"],
                    }
                )
                if legacy_observed or blocked
                else "{}",
                now,
                now,
            ),
        )
        for assignment in assignments:
            if legacy_observed or blocked:
                continue
            conn.execute(
                """
                UPDATE creative_plan_items
                SET experiment_id = ?, experiment_variant = ?,
                    exploration_class = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    experiment_id,
                    assignment["variant"],
                    assignment["experimentClass"],
                    now,
                    assignment["planItemId"],
                ),
            )
        register_experiment_design(conn, receipt)
        conn.commit()
    return {**receipt, "dryRun": not apply}


def plan_execution(
    conn: sqlite3.Connection,
    factory: Any,
    *,
    plan_id: str,
    apply: bool,
    signed_spend_credits: float | None,
    runner: Callable[..., dict[str, Any]] = run_production_batch,
) -> dict[str, Any]:
    """Delegate eligible items to the existing production lane, one retained job each."""
    plan = load_plan(conn, plan_id)
    eligible_states = {"APPROVED", "GENERATION_READY"}
    eligible = [
        item
        for item in plan["items"]
        if item["execution_state"] in eligible_states
        and not item["blocking_reasons"]
        and not json.loads(item["generation_identity_json"])
    ]
    blocked = [
        {
            "planItemId": item["id"],
            "state": item["execution_state"],
            "reasons": item["blocking_reasons"]
            or (
                ["already_completed"]
                if json.loads(item["generation_identity_json"])
                else ["not_generation_ready"]
            ),
        }
        for item in plan["items"]
        if item not in eligible
    ]
    estimated = sum(
        float(json.loads(item["estimated_cost_json"]).get("credits") or 0)
        for item in eligible
    )
    spend_limit = 0.0
    if apply:
        if signed_spend_credits is None or signed_spend_credits <= 0:
            raise PermissionError("signed spend authorization is required")
        spend_limit = signed_spend_credits
        if estimated > spend_limit:
            raise PermissionError(
                "eligible estimated spend exceeds signed authorization"
            )

    jobs: list[dict[str, Any]] = []
    actual = 0.0
    for item in eligible:
        kwargs = {
            "factory": factory,
            "creator": item["creator"],
            "intent": item["content_intent"],
            "count": 1,
            "execution": "cloud",
            "accounts": item["target_account"],
            "audio_preference": item["audio_policy"],
            "selected_source_asset_ids": (item["source_asset_id"],),
        }
        result = (
            runner(
                **kwargs,
                apply=True,
                max_total_credits=spend_limit - actual,
            )
            if apply
            else plan_production_batch(**kwargs)
        )
        receipt = {
            "schema": "creator_os.plan_item_generation.v1",
            "planId": plan["planId"],
            "planItemId": item["id"],
            "sourceAssetId": item["source_asset_id"],
            "normalProductionBatch": result,
            "dryRun": not apply,
        }
        jobs.append(receipt)
        if apply:
            quoted = float(result.get("quotedProviderCredits") or 0)
            actual += float(result.get("actualProviderCredits") or quoted)
            conn.execute(
                """
                UPDATE creative_plan_items
                SET generation_identity_json = ?, execution_state = ?, updated_at = ?
                WHERE id = ? AND generation_identity_json = '{}'
                """,
                (
                    _json(receipt),
                    "REVIEW_READY" if result.get("completed") else "RECONCILING",
                    _now(),
                    item["id"],
                ),
            )
    if apply:
        conn.commit()
    return {
        "schema": "creator_os.plan_execution.v1",
        "planId": plan["planId"],
        "dryRun": not apply,
        "eligibleItems": [item["id"] for item in eligible],
        "blockedItems": blocked,
        "estimatedProviderCalls": len(eligible),
        "estimatedCredits": estimated,
        "signedSpendAuthorization": signed_spend_credits,
        "jobs": jobs,
        "idempotency": "completed items are never submitted again",
    }


def review_plan_item(
    conn: sqlite3.Connection,
    *,
    plan_item_id: str,
    action: str,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    normalized = action.upper()
    if normalized not in REVIEW_ACTIONS:
        raise ValueError(f"unsupported review action: {action}")
    row = conn.execute(
        "SELECT * FROM creative_plan_items WHERE id = ?", (plan_item_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"plan item not found: {plan_item_id}")
    target = {
        "APPROVE": "CREATIVE_APPROVED",
        "REJECT": "REJECTED",
        "REQUEST_SMALL_EDIT": "REVIEW_READY",
        "REPLACE_AUDIO": "REVIEW_READY",
        "REGENERATE": "GENERATION_READY",
        "DEFER": "REVIEW_READY",
        "CANCEL": "CANCELLED",
    }[normalized]
    receipt = {
        "schema": "creator_os.plan_item_review.v1",
        "planItemId": plan_item_id,
        "operator": operator,
        "action": normalized,
        "reason": reason,
        "granularity": "output_only",
        "doesNotReject": [
            "source",
            "prompt_family",
            "intent",
            "provider",
            "capability",
        ],
        "at": _now(),
    }
    conn.execute(
        """
        UPDATE creative_plan_items
        SET execution_state = ?, review_identity_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (target, _json(receipt), _now(), plan_item_id),
    )
    conn.execute(
        """
        INSERT INTO creative_plan_item_events (
          id, plan_item_id, from_state, to_state, event_type, actor,
          reason, receipt_json, created_at
        ) VALUES (?, ?, ?, ?, 'operator_review', ?, ?, ?, ?)
        """,
        (
            f"pitevt_{_fingerprint(receipt)[:16]}",
            plan_item_id,
            row["execution_state"],
            target,
            operator,
            reason,
            _json(receipt),
            _now(),
        ),
    )
    conn.commit()
    return receipt


def create_metric_cohorts(
    conn: sqlite3.Connection,
    *,
    plan_item_id: str,
    published_at: datetime,
) -> list[dict[str, Any]]:
    if published_at.tzinfo is None:
        raise ValueError("published_at must be timezone-aware")
    now = _now()
    cohorts: list[dict[str, Any]] = []
    for bucket, offset in OBSERVATION_BUCKETS.items():
        cohort: dict[str, Any] = {
            "id": f"pmc_{_fingerprint([plan_item_id, bucket])[:16]}",
            "planItemId": plan_item_id,
            "observationBucket": bucket,
            "expectedEarliestAt": (published_at.astimezone(UTC) + offset)
            .isoformat()
            .replace("+00:00", "Z"),
            "observationState": "MISSING",
            "learningEligible": bucket in {"24h", "72h"},
        }
        conn.execute(
            """
            INSERT OR IGNORE INTO creative_plan_metric_cohorts (
              id, plan_item_id, observation_bucket, expected_earliest_at,
              actual_observed_at, post_age_seconds, observation_state,
              snapshot_id, learning_eligible, created_at, updated_at
            ) VALUES (?, ?, ?, ?, NULL, NULL, 'MISSING', NULL, ?, ?, ?)
            """,
            (
                cohort["id"],
                plan_item_id,
                bucket,
                cohort["expectedEarliestAt"],
                int(cohort["learningEligible"]),
                now,
                now,
            ),
        )
        cohorts.append(cohort)
    conn.commit()
    return cohorts


def export_manifest_preview(conn: sqlite3.Connection, plan_id: str) -> dict[str, Any]:
    """Build an identity-complete preview. This function never exports or schedules."""
    plan = load_plan(conn, plan_id)
    items: list[dict[str, Any]] = []
    for item in plan["items"]:
        if item["execution_state"] not in {"CREATIVE_APPROVED", "EXPORT_READY"}:
            continue
        generation = json.loads(item["generation_identity_json"])
        items.append(
            {
                "planId": plan["creativePlanId"],
                "planVersionId": plan["planId"],
                "planItemId": item["id"],
                "creator": item["creator"],
                "account": item["target_account"],
                "contentIntent": item["content_intent"],
                "sourceAssetId": item["source_asset_id"],
                "generationIdentity": generation,
                "audioIdentity": json.loads(item["audio_profile_json"]),
                "experimentId": item["experiment_id"],
                "experimentVariant": item["experiment_variant"],
                "scheduleProposal": json.loads(item["proposed_window_json"]),
                "approval": json.loads(item["review_identity_json"]),
                "threadsdashboardVerificationRequired": [
                    "hmac_identity",
                    "exact_final_media_sha256",
                    "account_authorization",
                ],
            }
        )
    manifest = {
        "schema": "creator_os.approved_plan_export_preview.v1",
        "planVersionId": plan["planId"],
        "items": items,
        "dryRun": True,
        "exportsCreated": 0,
        "schedulesCreated": 0,
    }
    manifest["fingerprint"] = _fingerprint(manifest)
    return manifest


def plan_status(conn: sqlite3.Connection, plan_id: str) -> dict[str, Any]:
    """Return one bounded, read-only control-tower view for a plan."""
    before = conn.total_changes
    plan = load_plan(conn, plan_id)
    states: dict[str, int] = {}
    missing_metrics = 0
    spent = 0.0
    for item in plan["items"]:
        state = str(item["execution_state"])
        states[state] = states.get(state, 0) + 1
        generation = json.loads(item["generation_identity_json"])
        batch = generation.get("normalProductionBatch") or {}
        spent += float(
            batch.get("actualProviderCredits")
            or batch.get("quotedProviderCredits")
            or 0
        )
        missing_metrics += conn.execute(
            """
            SELECT count(*) FROM creative_plan_metric_cohorts
            WHERE plan_item_id = ? AND observation_state = 'MISSING'
            """,
            (item["id"],),
        ).fetchone()[0]
    experiments = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, content_intent, changed_variable, status,
                   required_observation_cohort
            FROM creative_plan_experiments
            WHERE plan_version_id = ? AND status NOT IN ('COMPLETED', 'CANCELLED')
            ORDER BY created_at, id
            LIMIT 100
            """,
            (plan["planId"],),
        ).fetchall()
    ]
    result = {
        "schema": "creator_os.plan_status.v1",
        "planId": plan["planId"],
        "creator": plan["creator"],
        "objective": plan["objective"],
        "autonomyMode": plan["autonomyMode"],
        "planStatus": plan["status"],
        "stateCounts": states,
        "whatShouldBeCreated": states.get("APPROVED", 0)
        + states.get("GENERATION_READY", 0),
        "generating": states.get("GENERATING", 0) + states.get("RECONCILING", 0),
        "readyForReview": states.get("REVIEW_READY", 0),
        "creativeApproved": states.get("CREATIVE_APPROVED", 0),
        "waitingForExport": states.get("EXPORT_READY", 0),
        "scheduled": states.get("SCHEDULED", 0),
        "published": states.get("PUBLISHED", 0)
        + states.get("MEASURING", 0)
        + states.get("LEARNED", 0),
        "failedOrBlocked": states.get("BLOCKED", 0) + states.get("REJECTED", 0),
        "safeToRetry": [
            item["id"]
            for item in plan["items"]
            if item["execution_state"] in {"GENERATION_READY", "RECONCILING"}
            and not json.loads(item["generation_identity_json"])
        ],
        "missingMetricCohorts": missing_metrics,
        "activeExperiments": experiments,
        "learningChangedItems": plan["decisionReceipt"]
        .get("learning", {})
        .get("changedItems", []),
        "estimatedCredits": plan["estimatedSpend"].get("credits"),
        "authorizedCredits": plan["signedSpendCeiling"],
        "actualOrReconciledCredits": round(spent, 4),
        "runtimeSha": os.environ.get(
            "CREATOR_OS_RUNTIME_SHA", "unknown_not_bound_to_process"
        ),
        "readOnly": True,
    }
    if conn.total_changes != before:
        raise RuntimeError("status surface attempted a database mutation")
    return result


def list_plans(
    conn: sqlite3.Connection,
    *,
    creator: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("plan list limit must be between 1 and 100")
    params: list[object] = []
    where = ""
    if creator:
        where = "WHERE creator = ?"
        params.append(creator.strip().lower())
    params.append(limit)
    rows = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT id, creative_plan_id, version, creator, horizon_start,
                   horizon_end, objective, autonomy_mode, status, updated_at
            FROM creative_plan_versions
            {where}
            ORDER BY updated_at DESC, id
            LIMIT ?
            """,
            params,
        ).fetchall()
    ]
    return {
        "schema": "creator_os.plan_list.v1",
        "creator": creator,
        "limit": limit,
        "plans": rows,
        "readOnly": True,
    }


def replan(
    conn: sqlite3.Connection,
    *,
    plan_id: str,
    apply: bool,
) -> dict[str, Any]:
    """Create a successor version while retaining completed and published evidence."""
    previous = load_plan(conn, plan_id)
    start = datetime.fromisoformat(previous["horizon"]["start"]).date()
    end = datetime.fromisoformat(previous["horizon"]["end"]).date()
    request = PlanningRequest(
        creator=previous["creator"],
        horizon_days=(end - start).days + 1,
        accounts=tuple(str(row["handle"]) for row in previous["accounts"]),
        objective=previous["objective"],
        output_count=int(previous["requestedOutputCount"]),
        timezone=previous["timezone"],
        autonomy_mode=previous["autonomyMode"],
        max_credits=previous["signedSpendCeiling"],
        start_date=start,
    )
    candidate = build_plan(conn, request)
    retained_states = {
        "REVIEW_READY",
        "CREATIVE_APPROVED",
        "EXPORT_READY",
        "EXPORTED",
        "SCHEDULE_READY",
        "SCHEDULED",
        "PUBLISHING",
        "PUBLISHED",
        "MEASURING",
        "LEARNED",
    }
    retained: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    for old, new in zip(previous["items"], candidate["items"], strict=False):
        if old["execution_state"] in retained_states:
            retained.append(
                {
                    "previousPlanItemId": old["id"],
                    "itemIndex": old["item_index"],
                    "state": old["execution_state"],
                    "reason": "completed_or_publication_lineage_retained",
                }
            )
        changed_fields = [
            field
            for field, old_value, new_value in (
                ("source", old["source_asset_id"], new["sourceAssetId"]),
                ("intent", old["content_intent"], new["contentIntent"]),
                ("account", old["target_account"], new["targetAccount"]),
                ("prompt", old["prompt_text"], new["prompt"]),
            )
            if old_value != new_value
        ]
        if changed_fields:
            changes.append(
                {
                    "previousPlanItemId": old["id"],
                    "itemIndex": old["item_index"],
                    "changedFields": changed_fields,
                    "reason": "current scoped inventory_or_evidence_changed",
                }
            )
    replan_context = {
        "replanOf": previous["planId"],
        "previousInputFingerprint": previous["inputFingerprint"],
        "candidateInputFingerprint": candidate["inputFingerprint"],
        "retained": retained,
        "changes": changes,
    }
    candidate["previousPlanVersionId"] = previous["planId"]
    candidate["decisionReceipt"]["replan"] = replan_context
    candidate["inputFingerprint"] = plan_fingerprint(replan_context)
    candidate["planId"] = f"plan_{candidate['inputFingerprint'][:16]}"
    result: dict[str, Any] = {
        "schema": "creator_os.content_plan_replan.v1",
        "dryRun": not apply,
        "previousPlanId": previous["planId"],
        "candidate": candidate,
        "retainedItems": retained,
        "changedItems": changes,
        "providerCalls": 0,
        "exports": 0,
        "schedules": 0,
        "publications": 0,
    }
    if not apply:
        return result
    stored = persist_plan(conn, candidate)
    for retained_item in retained:
        old = next(
            item
            for item in previous["items"]
            if item["id"] == retained_item["previousPlanItemId"]
        )
        new = conn.execute(
            """
            SELECT id FROM creative_plan_items
            WHERE plan_version_id = ? AND item_index = ?
            """,
            (stored["planId"], old["item_index"]),
        ).fetchone()
        if new is None:
            continue
        conn.execute(
            """
            UPDATE creative_plan_items
            SET execution_state = ?, generation_identity_json = ?,
                review_identity_json = ?, export_identity_json = ?,
                publication_identity_json = ?, metric_cohort_identity_json = ?,
                learning_outcome_identity_json = ?, experiment_id = ?,
                experiment_variant = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                old["execution_state"],
                old["generation_identity_json"],
                old["review_identity_json"],
                old["export_identity_json"],
                old["publication_identity_json"],
                old["metric_cohort_identity_json"],
                old["learning_outcome_identity_json"],
                old["experiment_id"],
                old["experiment_variant"],
                _now(),
                new["id"],
            ),
        )
    conn.commit()
    return {**result, "candidate": load_plan(conn, stored["planId"]), "written": True}
