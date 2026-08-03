"""Matched-pair reporting for supervised observed-profile experiments."""

from __future__ import annotations

import hashlib
import json
import math
import random
import sqlite3
from datetime import UTC, datetime
from statistics import median
from typing import Any

from pipeline_contracts import validate_experiment_assignment_receipt

from .learning_governance import (
    canonical_learning_eligibility,
    register_experiment_interpretation,
    register_experiment_measurement,
)

OBSERVED_MEASUREMENT_PLAN = {
    "schema": "creator_os.observed_profile_measurement_plan.v1",
    "primary": "24h reach; views only when reach is unavailable on both arms",
    "confirmatory": "72h reach; views only when reach is unavailable on both arms",
    "secondary": [
        "impressions",
        "averageWatchTime",
        "completionRate",
        "retentionRate",
        "shares",
        "saves",
        "engagementRate",
    ],
    "guardrails": {
        "metrics": ["averageWatchTime", "engagementRate"],
        "maximumMedianRegression": 0.10,
        "minimumAvailableMetrics": 1,
    },
    "normalization": "trailing same-account equal-age median",
    "comparison": "normalized treatment/control lift within parent-family pair",
    "exclusions": [
        "publication_ambiguity",
        "lineage_mismatch",
        "unequal_age",
        "fixture_or_fallback",
        "metric_revision_unreconciled",
        "same_primary_metric_unavailable",
    ],
}

OBSERVED_PROFILE_SEQUENCE = (
    "mirror_crop_tone@1",
    "tilt_crop_dark@1",
    "light_editorial@1",
    "opening_trim@1",
)
OBSERVED_SPLIT_PROFILES = OBSERVED_PROFILE_SEQUENCE


def select_observed_profile(
    conn: sqlite3.Connection,
    *,
    creator: str,
    content_intent: str,
    source_asset_id: str | None = None,
    media_metadata: dict[str, Any] | None = None,
    purpose: str = "experiment",
) -> dict[str, Any]:
    """Choose the next treatment from measured history without bypassing review."""
    if purpose not in {"experiment", "production"}:
        raise ValueError("observed profile purpose must be experiment or production")
    notes: dict[str, Any] = {}
    if source_asset_id:
        source = conn.execute(
            "SELECT notes, media_type FROM source_assets WHERE id = ?",
            (source_asset_id,),
        ).fetchone()
        if source:
            notes = _json_object(source["notes"])
            notes.setdefault("mediaType", source["media_type"])
    traits = {**notes, **(media_metadata or {})}
    synchronized = content_intent.lower() in {
        "talking",
        "dance",
        "motion_copy",
        "recreate_reel",
    } or any(
        bool(traits.get(key))
        for key in ("synchronizedContent", "referenceTalking", "lipSync")
    )
    burned_caption = any(
        bool(traits.get(key)) for key in ("burnedCaption", "captionBurned")
    )
    visible_text = burned_caption or any(
        bool(traits.get(key)) for key in ("visibleText", "ocrTextPresent")
    )
    media_type = str(traits.get("mediaType") or traits.get("media_type") or "").lower()
    eligible = [] if synchronized or burned_caption else list(OBSERVED_PROFILE_SEQUENCE)
    blockers: dict[str, list[str]] = {}
    if synchronized:
        blockers = {
            profile: ["synchronized_content_ineligible"]
            for profile in OBSERVED_PROFILE_SEQUENCE
        }
    elif burned_caption:
        blockers = {
            profile: ["source_burned_caption_ineligible"]
            for profile in OBSERVED_PROFILE_SEQUENCE
        }
    if visible_text and "mirror_crop_tone@1" in eligible:
        eligible.remove("mirror_crop_tone@1")
        blockers["mirror_crop_tone@1"] = ["source_visible_text_blocks_mirror"]
    if media_type != "video" and "opening_trim@1" in eligible:
        eligible.remove("opening_trim@1")
        blockers["opening_trim@1"] = ["passive_video_required"]

    history = conn.execute(
        """
        SELECT id, status, variants_json, interpretation_json, created_at
        FROM creative_plan_experiments
        WHERE creator = ? AND content_intent = ?
          AND changed_variable = 'observed_profile'
        ORDER BY created_at, id
        """,
        (creator, content_intent),
    ).fetchall()
    records: list[dict[str, Any]] = []
    for row in history:
        variants = json.loads(row["variants_json"] or "[]")
        profile = variants[1] if len(variants) == 2 else None
        if profile not in OBSERVED_PROFILE_SEQUENCE:
            continue
        interpretation = _json_object(row["interpretation_json"])
        decision = interpretation.get("operatorDecision")
        records.append(
            {
                "experimentId": str(row["id"]),
                "profile": profile,
                "status": str(row["status"]),
                "decision": (
                    str(decision.get("decision"))
                    if isinstance(decision, dict) and decision.get("decision")
                    else None
                ),
            }
        )

    adopted = next(
        (
            record["profile"]
            for record in reversed(records)
            if record["decision"] == "adopt" and record["profile"] in eligible
        ),
        None,
    )
    active = next(
        (
            record["profile"]
            for record in reversed(records)
            if record["status"] != "DECIDED" and record["profile"] in eligible
        ),
        None,
    )
    decided = {record["profile"] for record in records if record["status"] == "DECIDED"}
    stopped = any(record["decision"] == "stop" for record in records)
    if purpose == "production":
        selected = adopted
        mode = "operator_adopted" if adopted else "normal_control"
    elif stopped:
        selected = None
        mode = "operator_stopped"
    else:
        selected = active or next(
            (profile for profile in eligible if profile not in decided), None
        )
        mode = "continue_active" if active else "next_unmeasured"
        if selected is None:
            mode = "sequence_complete"
    receipt = {
        "schema": "campaign_factory.observed_profile_policy.v1",
        "creator": creator,
        "contentIntent": content_intent,
        "sourceAssetId": source_asset_id,
        "purpose": purpose,
        "selectedProfile": selected,
        "mode": mode,
        "normalControlRequired": purpose == "experiment" and selected is not None,
        "treatmentRequired": purpose == "experiment" and selected is not None,
        "eligibleProfiles": eligible,
        "blockedProfiles": blockers,
        "history": records,
        "fingerprint": "",
    }
    receipt["fingerprint"] = _sha256(receipt)
    return receipt


def select_observed_profile_for_asset(
    conn: sqlite3.Connection,
    *,
    rendered_asset_id: str,
    purpose: str = "experiment",
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT r.source_asset_id, r.metadata_json, r.media_type, m.slug AS creator
        FROM rendered_assets r
        JOIN source_assets s ON s.id = r.source_asset_id
        JOIN models m ON m.id = s.model_id
        WHERE r.id = ?
        """,
        (rendered_asset_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"rendered asset not found: {rendered_asset_id}")
    metadata = _json_object(row["metadata_json"])
    metadata.setdefault("mediaType", row["media_type"])
    content_intent = str(
        metadata.get("contentIntent")
        or metadata.get("motionIntent")
        or "passive_selfie"
    ).lower()
    if content_intent in {"ambient", "calm", "passive"}:
        content_intent = "passive_selfie"
    return select_observed_profile(
        conn,
        creator=str(row["creator"]),
        content_intent=content_intent,
        source_asset_id=str(row["source_asset_id"]),
        media_metadata=metadata,
        purpose=purpose,
    )


def resolve_observed_profile_for_asset(
    conn: sqlite3.Connection,
    *,
    rendered_asset_id: str,
    profile: str | None,
) -> tuple[str | None, dict[str, Any] | None]:
    if profile != "auto":
        return profile, None
    experiment = select_observed_profile_for_asset(
        conn, rendered_asset_id=rendered_asset_id, purpose="experiment"
    )
    production = select_observed_profile_for_asset(
        conn, rendered_asset_id=rendered_asset_id, purpose="production"
    )
    decision = (
        experiment
        if experiment["mode"] == "continue_active"
        or production["selectedProfile"] is None
        else production
    )
    selected = decision["selectedProfile"]
    if selected is None:
        raise ValueError(f"no observed profile is eligible: {decision['mode']}")
    return str(selected), decision


def observed_experiment_report(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    record_interpretation: bool = False,
) -> dict[str, Any]:
    experiment = conn.execute(
        "SELECT * FROM creative_plan_experiments WHERE id = ?", (experiment_id,)
    ).fetchone()
    if not experiment:
        raise ValueError(f"experiment not found: {experiment_id}")
    if experiment["assignment_method"] != "cross_account_blocked_rotation.v1":
        raise ValueError(
            "experiment is not an observed-profile matched-pair experiment"
        )
    if experiment["changed_variable"] != "observed_profile":
        raise ValueError("observed-profile experiment changed variable is invalid")
    controlled = set(json.loads(experiment["controlled_variables_json"] or "[]"))
    if controlled != {
        "creator",
        "account",
        "content_intent",
        "observation_cohort",
        "publication_window",
    }:
        raise ValueError("observed-profile experiment controls are invalid")
    variants = json.loads(experiment["variants_json"] or "[]")
    if (
        len(variants) != 2
        or variants[0] != "control"
        or variants[1] not in OBSERVED_PROFILE_SEQUENCE
    ):
        raise ValueError("observed-profile experiment variants are invalid")
    predeclared = _json_object(experiment["interpretation_json"]).get("measurementPlan")
    if predeclared != OBSERVED_MEASUREMENT_PLAN:
        raise ValueError("observed-profile measurement plan was not predeclared")
    events = conn.execute(
        """
        SELECT e.plan_item_id, e.receipt_json
        FROM creative_plan_item_events e
        JOIN creative_plan_items i ON i.id = e.plan_item_id
        WHERE e.event_type = 'experiment_assignment'
          AND i.experiment_id = ?
        ORDER BY e.created_at, e.plan_item_id
        """,
        (experiment_id,),
    ).fetchall()
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for event in events:
        receipt = json.loads(event["receipt_json"])
        validate_experiment_assignment_receipt(receipt)
        if receipt.get("experimentId") != experiment_id:
            raise ValueError("experiment assignment receipt does not match experiment")
        grouped.setdefault(str(receipt["pairId"]), []).append(
            (str(event["plan_item_id"]), receipt)
        )
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    experiment_asset_ids = {
        str(receipt["assignedAssetId"])
        for rows in grouped.values()
        for _, receipt in rows
    }
    for pair_id, rows in sorted(grouped.items()):
        pair, reasons = _matched_pair(
            conn,
            pair_id=pair_id,
            rows=rows,
            experiment_asset_ids=experiment_asset_ids,
            observation_bucket="24h",
        )
        confirmatory, confirmatory_reasons = _matched_pair(
            conn,
            pair_id=pair_id,
            rows=rows,
            experiment_asset_ids=experiment_asset_ids,
            observation_bucket="72h",
        )
        reasons.extend(f"confirmatory_{reason}" for reason in confirmatory_reasons)
        if reasons:
            excluded.append({"pairId": pair_id, "reasons": reasons})
        elif pair is not None and confirmatory is not None:
            pair["confirmatory72h"] = confirmatory
            included.append(pair)
    lifts = [float(pair["primaryLift"]) for pair in included]
    primary_metrics = sorted({str(pair["primaryMetric"]) for pair in included})
    median_lift = median(lifts) if lifts else None
    positive_percentage = (
        sum(1 for lift in lifts if lift > 0) / len(lifts) if lifts else None
    )
    interval = (
        _bootstrap_interval(lifts, seed=_sha256([experiment_id, lifts]))
        if lifts
        else None
    )
    guardrails = _guardrail_summary(included)
    confirmatory_lifts = [
        float(pair["confirmatory72h"]["primaryLift"]) for pair in included
    ]
    confirmatory_median = median(confirmatory_lifts) if confirmatory_lifts else None
    confirmatory_positive_percentage = (
        sum(1 for lift in confirmatory_lifts if lift > 0) / len(confirmatory_lifts)
        if confirmatory_lifts
        else None
    )
    confirmatory_pass = bool(
        confirmatory_median is not None
        and confirmatory_median > 0
        and confirmatory_positive_percentage is not None
        and confirmatory_positive_percentage >= 0.60
    )
    accounts = {
        str(arm["accountId"])
        for pair in included
        for arm in (pair["control"], pair["treatment"])
    }
    interpretation = _interpretation(
        pair_count=len(included),
        account_count=len(accounts),
        median_lift=median_lift,
        positive_percentage=positive_percentage,
        interval=interval,
        guardrails_pass=guardrails["pass"],
        confirmatory_pass=confirmatory_pass,
    )
    report = {
        "schema": "creator_os.observed_profile_experiment_report.v1",
        "experimentId": experiment_id,
        "profile": variants[1],
        "measurementPlan": OBSERVED_MEASUREMENT_PLAN,
        "primaryMetricPolicy": "24h_reach_else_views_on_both_arms",
        "confirmatoryMetricPolicy": "72h_reach_else_views_on_both_arms",
        "includedPairCount": len(included),
        "excludedPairCount": len(excluded),
        "primaryMetricsUsed": primary_metrics,
        "medianPairedLift": _round(median_lift),
        "positivePairPercentage": _round(positive_percentage),
        "bootstrap95": (
            {"lower": _round(interval[0]), "upper": _round(interval[1])}
            if interval
            else None
        ),
        "guardrails": guardrails,
        "confirmatory72h": {
            "medianPairedLift": _round(confirmatory_median),
            "positivePairPercentage": _round(confirmatory_positive_percentage),
            "pass": confirmatory_pass,
        },
        "accountCount": len(accounts),
        "interpretation": interpretation,
        "pairs": included,
        "exclusions": excluded,
        "automaticProductionExpansion": False,
        "fingerprint": "",
    }
    report["fingerprint"] = _sha256(report)
    if record_interpretation:
        conn.execute(
            """
            UPDATE creative_plan_experiments
            SET interpretation_json = ?, status = 'MEASURED', updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(report, ensure_ascii=False, sort_keys=True),
                datetime.now(UTC).isoformat(),
                experiment_id,
            ),
        )
        register_experiment_measurement(
            conn,
            experiment_id=experiment_id,
            report=report,
        )
        conn.commit()
    return report


def record_observed_experiment_decision(
    conn: sqlite3.Connection,
    *,
    experiment_id: str,
    operator: str,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    normalized = decision.strip().lower()
    if normalized not in {"continue_sequence", "stop", "adopt", "reject"}:
        raise ValueError("unsupported observed experiment decision")
    row = conn.execute(
        "SELECT * FROM creative_plan_experiments WHERE id = ?", (experiment_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"experiment not found: {experiment_id}")
    interpretation = _json_object(row["interpretation_json"])
    if (
        interpretation.get("schema")
        != "creator_os.observed_profile_experiment_report.v1"
    ):
        raise ValueError("record a measured experiment report before deciding")
    if normalized == "adopt" and (
        _json_object(interpretation.get("interpretation")).get("status")
        != "operator_review_eligible"
    ):
        raise ValueError("only an operator-review-eligible result can be adopted")
    variants = json.loads(row["variants_json"] or "[]")
    profile = variants[1] if len(variants) == 2 else None
    receipt = {
        "schema": "creator_os.observed_profile_experiment_decision.v1",
        "experimentId": experiment_id,
        "operator": operator,
        "decision": normalized,
        "reason": reason,
        "reportFingerprint": interpretation["fingerprint"],
        "productionUsageChanged": normalized == "adopt",
        "adoptedProfile": profile if normalized == "adopt" else None,
        "decidedAt": datetime.now(UTC).isoformat(),
    }
    interpretation["operatorDecision"] = receipt
    conn.execute(
        """
        UPDATE creative_plan_experiments
        SET interpretation_json = ?, status = 'DECIDED', updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(interpretation, ensure_ascii=False, sort_keys=True),
            receipt["decidedAt"],
            experiment_id,
        ),
    )
    register_experiment_interpretation(
        conn,
        experiment_id=experiment_id,
        decision=receipt,
    )
    conn.commit()
    return receipt


def _matched_pair(
    conn: sqlite3.Connection,
    *,
    pair_id: str,
    rows: list[tuple[str, dict[str, Any]]],
    experiment_asset_ids: set[str],
    observation_bucket: str = "72h",
) -> tuple[dict[str, Any] | None, list[str]]:
    if len(rows) != 2:
        return None, ["pair_assignment_incomplete"]
    by_role = {receipt["role"]: (item_id, receipt) for item_id, receipt in rows}
    if set(by_role) != {"control", "treatment"}:
        return None, ["pair_roles_invalid"]
    observations: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for role, (plan_item_id, receipt) in by_role.items():
        cohort = conn.execute(
            """
            SELECT * FROM creative_plan_metric_cohorts
            WHERE plan_item_id = ? AND observation_bucket = ?
            """,
            (plan_item_id, observation_bucket),
        ).fetchone()
        if not cohort or not cohort["snapshot_id"]:
            reasons.append(f"{role}_{observation_bucket}_snapshot_missing")
            continue
        snapshot = conn.execute(
            "SELECT * FROM performance_snapshots WHERE id = ?",
            (cohort["snapshot_id"],),
        ).fetchone()
        if not snapshot:
            reasons.append(f"{role}_snapshot_missing")
            continue
        snapshot = dict(snapshot)
        snapshot_reasons = _snapshot_exclusion_reasons(
            conn,
            snapshot,
            receipt,
            required_observation_bucket=f"approximately_{observation_bucket}",
        )
        reasons.extend(f"{role}_{reason}" for reason in snapshot_reasons)
        observations[role] = {
            "planItemId": plan_item_id,
            "receipt": receipt,
            "cohort": dict(cohort),
            "snapshot": snapshot,
        }
    if reasons or set(observations) != {"control", "treatment"}:
        return None, sorted(set(reasons))
    ages = [
        int(observations[role]["cohort"]["post_age_seconds"] or 0)
        for role in ("control", "treatment")
    ]
    if min(ages) <= 0 or abs(ages[0] - ages[1]) > 300:
        return None, ["unequal_age_observations"]
    control_snapshot = observations["control"]["snapshot"]
    treatment_snapshot = observations["treatment"]["snapshot"]
    reaches = (
        control_snapshot.get("reach"),
        treatment_snapshot.get("reach"),
    )
    if all(value is not None for value in reaches):
        primary = "reach"
    elif (
        all(value is None for value in reaches)
        and control_snapshot.get("views") is not None
        and treatment_snapshot.get("views") is not None
    ):
        primary = "views"
    else:
        return None, ["same_primary_metric_unavailable"]
    arms: dict[str, dict[str, Any]] = {}
    for role, observation in observations.items():
        snapshot = observation["snapshot"]
        account_id = str(
            snapshot.get("account_id")
            or snapshot.get("instagram_account_id")
            or observation["receipt"]["accountId"]
        )
        baseline = _account_baseline(
            conn,
            account_id=account_id,
            metric=primary,
            before=str(snapshot["published_at"]),
            excluded_asset_ids=experiment_asset_ids,
            observation_bucket=observation_bucket,
        )
        if baseline is None:
            reasons.append(f"{role}_account_baseline_missing")
            continue
        value = float(snapshot[primary])
        secondary = _secondary_values(snapshot)
        normalized_secondary: dict[str, dict[str, float | None]] = {}
        for metric, secondary_value in secondary.items():
            secondary_baseline = (
                _account_secondary_baseline(
                    conn,
                    account_id=account_id,
                    metric=metric,
                    before=str(snapshot["published_at"]),
                    excluded_asset_ids=experiment_asset_ids,
                    observation_bucket=observation_bucket,
                )
                if secondary_value is not None
                else None
            )
            normalized_secondary[metric] = {
                "value": secondary_value,
                "baseline": secondary_baseline,
                "normalized": (
                    secondary_value / secondary_baseline
                    if secondary_value is not None and secondary_baseline
                    else None
                ),
            }
        arms[role] = {
            "accountId": account_id,
            "assetId": observation["receipt"]["assignedAssetId"],
            "snapshotId": snapshot["id"],
            "postAgeSeconds": observation["cohort"]["post_age_seconds"],
            "primaryValue": value,
            "primaryBaseline": baseline,
            "normalizedPrimary": value / baseline,
            "averageWatchTime": _average_watch_time(snapshot),
            "engagementRate": _engagement_rate(snapshot),
            "secondary": normalized_secondary,
        }
    if reasons:
        return None, sorted(set(reasons))
    primary_lift = (
        arms["treatment"]["normalizedPrimary"] / arms["control"]["normalizedPrimary"]
    ) - 1.0
    for metric in ("averageWatchTime", "engagementRate"):
        for role in ("control", "treatment"):
            secondary = arms[role]["secondary"][metric]
            arms[role][f"{metric}Baseline"] = secondary["baseline"]
            arms[role][f"normalized{metric[0].upper()}{metric[1:]}"] = secondary[
                "normalized"
            ]
    guardrail_lifts = {}
    for metric in ("AverageWatchTime", "EngagementRate"):
        control = arms["control"][f"normalized{metric}"]
        treatment = arms["treatment"][f"normalized{metric}"]
        guardrail_lifts[metric[0].lower() + metric[1:]] = (
            (treatment / control) - 1.0
            if control not in {None, 0} and treatment is not None
            else None
        )
    secondary_lifts = {}
    for metric in OBSERVED_MEASUREMENT_PLAN["secondary"]:
        control = arms["control"]["secondary"][metric]["normalized"]
        treatment = arms["treatment"]["secondary"][metric]["normalized"]
        secondary_lifts[metric] = (
            (treatment / control) - 1.0
            if control not in {None, 0} and treatment is not None
            else None
        )
    return (
        {
            "pairId": pair_id,
            "observationBucket": observation_bucket,
            "parentFamilyId": rows[0][1]["parentFamilyId"],
            "primaryMetric": primary,
            "primaryLift": _round(primary_lift),
            "control": _rounded_arm(arms["control"]),
            "treatment": _rounded_arm(arms["treatment"]),
            "guardrailLifts": {
                key: _round(value) for key, value in guardrail_lifts.items()
            },
            "secondaryLifts": {
                key: _round(value) for key, value in secondary_lifts.items()
            },
        },
        [],
    )


def _snapshot_exclusion_reasons(
    conn: sqlite3.Connection | dict[str, Any],
    snapshot: dict[str, Any],
    receipt: dict[str, Any] | None = None,
    required_observation_bucket: str = "approximately_72h",
) -> list[str]:
    if receipt is None:
        if not isinstance(conn, dict):
            raise TypeError("legacy exclusion check requires a snapshot dictionary")
        snapshot_row = conn
        receipt_row = snapshot
        governance_conn: sqlite3.Connection | None = None
    else:
        if not isinstance(conn, sqlite3.Connection):
            raise TypeError("governed exclusion check requires a SQLite connection")
        snapshot_row = snapshot
        receipt_row = receipt
        governance_conn = conn
    reasons: list[str] = []
    if snapshot_row.get("metrics_eligible") != 1:
        reasons.append("metrics_ineligible")
    if snapshot_row.get("history_source") != "metric_history":
        reasons.append("fallback_history")
    if snapshot_row.get("lineage_v2_valid") != 1:
        reasons.append("lineage_invalid")
    if snapshot_row.get("rendered_asset_id") != receipt_row["assignedAssetId"]:
        reasons.append("assigned_asset_mismatch")
    if snapshot_row.get("content_hash") != receipt_row["assignedAssetSha256"]:
        reasons.append("assigned_sha_mismatch")
    if not snapshot_row.get("published_at") or not snapshot_row.get("post_id"):
        reasons.append("publication_ambiguity")
    raw = _json_object(snapshot_row.get("raw_json"))
    if _recursive_truthy(raw, "fixture", "is_fixture", "fallback_used"):
        reasons.append("fixture_or_fallback")
    revision = _recursive_value(raw, "revision_status", "metric_revision_status")
    if revision and str(revision).lower() not in {"reconciled", "final"}:
        reasons.append("metric_revision_unreconciled")
    if _recursive_truthy(raw, "publication_ambiguity", "ambiguous_publication"):
        reasons.append("publication_ambiguity")
    if governance_conn is not None:
        governance = canonical_learning_eligibility(
            governance_conn,
            snapshot_row,
            include_base_learning=False,
            required_observation_bucket=required_observation_bucket,
        )
        reasons.extend(str(reason) for reason in governance["reasons"])
    return sorted(set(reasons))


def _account_baseline(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    metric: str,
    before: str,
    excluded_asset_ids: set[str],
    observation_bucket: str,
) -> float | None:
    rows = _trailing_rows(
        conn,
        account_id=account_id,
        before=before,
        observation_bucket=observation_bucket,
    )
    values = [
        float(row[metric])
        for row in rows
        if row.get("rendered_asset_id") not in excluded_asset_ids
        and row.get(metric) is not None
        and float(row[metric]) > 0
    ]
    return median(values) if values else None


def _account_secondary_baseline(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    metric: str,
    before: str,
    excluded_asset_ids: set[str],
    observation_bucket: str,
) -> float | None:
    values: list[float] = []
    for row in _trailing_rows(
        conn,
        account_id=account_id,
        before=before,
        observation_bucket=observation_bucket,
    ):
        if row.get("rendered_asset_id") in excluded_asset_ids:
            continue
        value = _secondary_values(row).get(metric)
        if value is not None and value > 0:
            values.append(value)
    return median(values) if values else None


def _secondary_values(snapshot: dict[str, Any]) -> dict[str, float | None]:
    raw = _json_object(snapshot.get("raw_json"))
    return {
        "impressions": _number(snapshot.get("impressions")),
        "averageWatchTime": _average_watch_time(snapshot),
        "completionRate": _rate(
            _recursive_value(
                raw,
                "completion_rate",
                "completionRate",
                "reels_completion_rate",
            )
        ),
        "retentionRate": _rate(
            _recursive_value(
                raw,
                "retention_rate",
                "retentionRate",
                "reels_retention_rate",
            )
        ),
        "shares": _number(snapshot.get("shares")),
        "saves": _number(snapshot.get("saves")),
        "engagementRate": _engagement_rate(snapshot),
    }


def _trailing_rows(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    before: str,
    observation_bucket: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM performance_snapshots
        WHERE COALESCE(account_id, instagram_account_id) = ?
          AND published_at < ?
          AND metrics_eligible = 1
          AND history_source = 'metric_history'
          AND lineage_v2_valid = 1
        ORDER BY snapshot_at DESC
        """,
        (account_id, before),
    ).fetchall()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        published = _parse_time(item.get("published_at"))
        observed = _parse_time(item.get("snapshot_at"))
        if not published or not observed:
            continue
        age_hours = (observed - published).total_seconds() / 3600
        target_hours = 24 if observation_bucket == "24h" else 72
        tolerance = 4
        if not target_hours - tolerance <= age_hours <= target_hours + tolerance:
            continue
        latest.setdefault(str(item["post_id"]), item)
    return list(latest.values())[:30]


def _average_watch_time(snapshot: dict[str, Any]) -> float | None:
    raw = _json_object(snapshot.get("raw_json"))
    direct = _recursive_value(
        raw, "ig_reels_avg_watch_time", "average_watch_time", "avg_watch_time"
    )
    if direct is not None:
        value = _number(direct)
        if value is not None:
            return value / 1000 if value > 1000 else value
    total = _number(snapshot.get("watch_time_seconds"))
    views = _number(snapshot.get("views"))
    return total / views if total is not None and views and views > 0 else None


def _engagement_rate(snapshot: dict[str, Any]) -> float | None:
    raw = _json_object(snapshot.get("raw_json"))
    direct = _number(_recursive_value(raw, "engagement_rate", "engagementRate"))
    if direct is not None:
        return direct / 100 if direct > 1 else direct
    denominator = _number(snapshot.get("reach")) or _number(snapshot.get("views"))
    if not denominator or denominator <= 0:
        return None
    engagement = sum(
        _number(snapshot.get(field)) or 0
        for field in ("likes", "comments", "shares", "saves")
    )
    return engagement / denominator


def _guardrail_summary(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {}
    available = False
    passed = True
    for metric in ("averageWatchTime", "engagementRate"):
        values = [
            float(pair["guardrailLifts"][metric])
            for pair in pairs
            if pair["guardrailLifts"].get(metric) is not None
        ]
        metric_median = median(values) if values else None
        metric_pass = metric_median is None or metric_median >= -0.10
        available = available or bool(values)
        passed = passed and metric_pass
        metrics[metric] = {
            "availablePairs": len(values),
            "medianLift": _round(metric_median),
            "pass": metric_pass if values else None,
        }
    return {
        "required": "no median regression greater than 10 percent",
        "atLeastOneAvailable": available,
        "pass": bool(available and passed),
        "metrics": metrics,
    }


def _interpretation(
    *,
    pair_count: int,
    account_count: int,
    median_lift: float | None,
    positive_percentage: float | None,
    interval: tuple[float, float] | None,
    guardrails_pass: bool,
    confirmatory_pass: bool = True,
) -> dict[str, Any]:
    status = "inconclusive"
    if pair_count < 3:
        status = "insufficient"
    elif pair_count < 5:
        status = "early_advisory"
    elif (
        pair_count < 10
        and median_lift is not None
        and median_lift >= 0.20
        and positive_percentage is not None
        and positive_percentage >= 0.70
        and guardrails_pass
        and confirmatory_pass
    ):
        status = "preliminary"
    elif (
        pair_count >= 10
        and account_count >= 3
        and median_lift is not None
        and median_lift >= 0.10
        and positive_percentage is not None
        and positive_percentage >= 0.60
        and interval is not None
        and interval[0] > 0
        and guardrails_pass
        and confirmatory_pass
    ):
        status = "operator_review_eligible"
    return {
        "status": status,
        "operatorDecisionRequired": True,
        "productionUsageChanged": False,
        "confirmatoryPass": confirmatory_pass,
    }


def _bootstrap_interval(
    values: list[float], *, seed: str, iterations: int = 4000
) -> tuple[float, float]:
    rng = random.Random(int(seed[:16], 16))
    samples = sorted(
        median(rng.choices(values, k=len(values))) for _ in range(iterations)
    )
    return (
        samples[math.floor(0.025 * (iterations - 1))],
        samples[math.ceil(0.975 * (iterations - 1))],
    )


def _rounded_arm(arm: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _round(value) if isinstance(value, float) else value
        for key, value in arm.items()
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _recursive_value(value: Any, *keys: str) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        for child in value.values():
            found = _recursive_value(child, *keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _recursive_value(child, *keys)
            if found is not None:
                return found
    return None


def _recursive_truthy(value: Any, *keys: str) -> bool:
    return bool(_recursive_value(value, *keys))


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate(value: Any) -> float | None:
    result = _number(value)
    if result is None:
        return None
    return result / 100 if result > 1 else result


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
