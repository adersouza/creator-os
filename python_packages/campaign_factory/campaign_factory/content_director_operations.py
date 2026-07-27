"""Schedule, experiment, execution, review, and lineage operations for content plans."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .content_director import _json, _now, load_plan
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
    }
)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def propose_schedule(
    conn: sqlite3.Connection,
    plan_id: str,
    *,
    apply: bool,
    blackout_dates: frozenset[str] = frozenset(),
    minimum_gap_hours: int = 20,
) -> dict[str, Any]:
    """Propose deterministic, non-overlapping windows; never schedules externally."""
    plan = load_plan(conn, plan_id)
    zone = ZoneInfo(plan["timezone"])
    cursor = datetime.combine(
        datetime.fromisoformat(plan["horizon"]["start"]).date(),
        time(hour=18, minute=30),
        tzinfo=zone,
    )
    by_account: dict[str, datetime] = {}
    proposals: list[dict[str, Any]] = []
    for item in plan["items"]:
        account = str(item["target_account"])
        candidate = max(cursor, by_account.get(account, cursor))
        while candidate.date().isoformat() in blackout_dates:
            candidate += timedelta(days=1)
        if candidate.weekday() >= 5:
            candidate = candidate.replace(hour=12, minute=30)
        layer = "safe_deterministic_default"
        source = "machine_local_content_director_policy"
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
            "learnedTiming": False,
            "threadsdashboardFinalAuthority": True,
            "status": "PROPOSED",
        }
        proposals.append(proposal)
        by_account[account] = candidate + timedelta(hours=minimum_gap_hours)
        cursor += timedelta(days=1)
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
) -> dict[str, Any]:
    if changed_variable not in EXPERIMENT_VARIABLES:
        raise ValueError(f"unsupported experiment variable: {changed_variable}")
    if len(set(variants)) != 2:
        raise ValueError("an initial experiment requires exactly two distinct variants")
    plan = load_plan(conn, plan_id)
    items = plan["items"][:2]
    if len(items) < 2:
        raise ValueError("experiment requires at least two plan items")
    if len({item["target_account"] for item in items}) != 1:
        raise ValueError("experiment variants must use the same account")
    if len({item["content_intent"] for item in items}) != 1:
        raise ValueError("experiment variants must use the same content intent")
    seed = int(_fingerprint([plan_id, changed_variable, variants])[:8], 16)
    experiment_id = f"pexp_{_fingerprint([plan_id, changed_variable, variants])[:16]}"
    controlled = sorted(
        {
            "creator",
            "account",
            "content_intent",
            "observation_cohort",
            "publication_window",
        }
        - {changed_variable}
    )
    assignments = [
        {"planItemId": item["id"], "variant": variants[index]}
        for index, item in enumerate(items)
    ]
    receipt = {
        "schema": "creator_os.plan_experiment.v1",
        "experimentId": experiment_id,
        "planId": plan["planId"],
        "creator": plan["creator"],
        "accountScope": [items[0]["target_account"]],
        "contentIntent": items[0]["content_intent"],
        "hypothesis": hypothesis,
        "controlledVariables": controlled,
        "changedVariable": changed_variable,
        "variants": list(variants),
        "assignmentMethod": "deterministic_alternation",
        "deterministicSeed": seed,
        "requiredObservationCohort": "24h",
        "minimumSampleWarning": "two items show an observed difference only; not causal proof",
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '24h', ?, 'PROPOSED',
                      '[]', '{}', ?, ?)
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
                receipt["minimumSampleWarning"],
                now,
                now,
            ),
        )
        for assignment in assignments:
            conn.execute(
                """
                UPDATE creative_plan_items
                SET experiment_id = ?, experiment_variant = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    experiment_id,
                    assignment["variant"],
                    now,
                    assignment["planItemId"],
                ),
            )
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
    if apply and (signed_spend_credits is None or signed_spend_credits <= 0):
        raise PermissionError("signed spend authorization is required")
    if apply and estimated > float(signed_spend_credits):
        raise PermissionError("eligible estimated spend exceeds signed authorization")

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
                max_total_credits=float(signed_spend_credits) - actual,
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
        cohort = {
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
